"""HTTP 接口（响应形状对齐 v2 契约）。

- `GET  /api/books` / `GET /api/books/{book_id}`：v2 BookPackage
- `GET  /api/books/{book_id}/query-sets[/{query_set_id}]`：v2 QuerySet（脚本不再在 book.json 里）
- `GET  /api/books/{book_id}/capability`：v2 CapabilityReport
- `POST /api/interact`：v2 InteractionRequest -> InteractionResponse
- `POST /api/qa`：`kind=qa` 的兼容别名
- `GET  /api/jobs/{job_id}` 等：v2 Job
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.app.capability import build_capability_report, write_capability_report
from backend.app.conductor import describe_tools, run_interaction
from backend.app.ingest import ingest_book
from backend.app.ingest_jobs import IngestionJobManager
from backend.app.jobs import JobManager, JobNotFoundError, JobStore
from backend.app.knowledge import load_qa_cards
from backend.app.generation_runner import PipelineGenerationRunner
from backend.app.models import (
    AnnotationTargetType,
    InteractionKind,
    InteractionRequest,
    InteractionResponse,
)
from backend.app.session_log import latest_eval_run, read_traces, read_turns
from backend.app.store import (
    BookNotFoundError,
    BookStore,
    InvalidBookPackageError,
)
from backend.app.validation import ContractError
from backend.app.plans import (
    load_generation_result,
    load_scene_plan,
    load_story_plan,
    load_timeline,
)
from pipeline.annotations import (
    create_annotation,
    load_annotations,
    load_review_items,
)
from pipeline.models.registry import load_config, status as provider_status
from pipeline.tts import edge_tts_available


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
# 默认和 pipeline 共用 data/books：两条链路写同一份 v2 book.json，
# 否则 API 看不到 pipeline 产出的书（TEAM_DIVISION §12.3 耦合点 1）。
BOOK_ROOT = Path(
    os.environ.get("DREAMYTALE_BOOK_ROOT", REPOSITORY_ROOT / "data" / "books")
).resolve()
JOB_STORE_PATH = Path(
    os.environ.get("DREAMYTALE_JOB_STORE", REPOSITORY_ROOT / "temp" / "jobs.json")
).resolve()
UPLOAD_ROOT = Path(
    os.environ.get("DREAMYTALE_UPLOAD_ROOT", REPOSITORY_ROOT / "temp" / "uploads")
).resolve()


class IngestRequest(BaseModel):
    archive_path: str
    book_key: str
    force: bool = False
    render_scale: float = Field(default=2.0, gt=0, le=4)


class AnnotationRequest(BaseModel):
    target_type: AnnotationTargetType
    target_id: str
    field: str
    value: Any
    reviewer: str = Field(min_length=1)
    reason: str | None = None
    old_value: Any | None = None


app = FastAPI(
    title="DreamyTale Backend",
    version="2.0.0",
    description="Book package, generation job and interaction API for DreamyTale.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

books = BookStore(BOOK_ROOT)
job_store = JobStore(JOB_STORE_PATH)
jobs = JobManager(
    job_store,
    runner=PipelineGenerationRunner(),
)
ingestions = IngestionJobManager(
    job_store,
    BOOK_ROOT,
    UPLOAD_ROOT,
)


def _error(status_code: int, code: str, message: str, details: object = None) -> JSONResponse:
    content: dict[str, object] = {"code": code, "message": message}
    if details is not None:
        content["details"] = details
    return JSONResponse(status_code=status_code, content={"error": content})


@app.exception_handler(BookNotFoundError)
async def handle_book_not_found(_request, exc: BookNotFoundError) -> JSONResponse:
    return _error(404, "book_not_found", str(exc))


@app.exception_handler(InvalidBookPackageError)
async def handle_invalid_book(
    _request,
    exc: InvalidBookPackageError,
) -> JSONResponse:
    return _error(
        422,
        "invalid_book_package",
        str(exc),
        exc.errors,
    )


@app.exception_handler(JobNotFoundError)
async def handle_job_not_found(_request, exc: JobNotFoundError) -> JSONResponse:
    return _error(404, "job_not_found", str(exc))


@app.exception_handler(ContractError)
async def handle_contract_error(_request, exc: ContractError) -> JSONResponse:
    return _error(
        422,
        "invalid_data_contract",
        "book package does not satisfy the data contract",
        exc.errors,
    )


@app.exception_handler(RequestValidationError)
async def handle_request_validation(
    _request,
    exc: RequestValidationError,
) -> JSONResponse:
    return _error(
        422,
        "invalid_request",
        "request body does not satisfy the data contract",
        [
            "{}: {}".format(
                ".".join(str(part) for part in item.get("loc", ())),
                item.get("msg", "invalid value"),
            )
            for item in exc.errors()
        ],
    )


@app.exception_handler(FileNotFoundError)
async def handle_file_not_found(_request, exc: FileNotFoundError) -> JSONResponse:
    return _error(404, "file_not_found", str(exc))


@app.exception_handler(FileExistsError)
async def handle_file_exists(_request, exc: FileExistsError) -> JSONResponse:
    return _error(409, "book_already_exists", str(exc))


@app.exception_handler(ValueError)
async def handle_value_error(_request, exc: ValueError) -> JSONResponse:
    return _error(422, "invalid_request", str(exc))


@app.exception_handler(OSError)
async def handle_storage_error(_request, exc: OSError) -> JSONResponse:
    return _error(503, "storage_unavailable", str(exc))


@app.get("/")
def service_info() -> dict[str, str]:
    return {
        "service": "DreamyTale Backend",
        "schema_version": "2.0.0",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/books")
def list_books() -> list[dict[str, object]]:
    summaries = []
    for book_id in books.list_book_ids():
        package = books.load(book_id)
        summaries.append(
            {
                "book_id": package.book_id,
                "title": package.title,
                "source_name": package.source_name,
                "language": package.language,
                "languages": list(package.languages),
                "content_type": package.content_type.value,
                "source_type": package.source_type.value,
                "page_count": package.page_count,
                "status": package.status.value,
                "query_set_ids": list(package.query_set_ids),
                "capabilities_path": package.capabilities_path,
                "created_at": package.created_at.isoformat() if package.created_at else None,
                "updated_at": package.updated_at.isoformat() if package.updated_at else None,
            }
        )
    return summaries


@app.get("/api/books/{book_id}")
def get_book(book_id: str) -> dict[str, object]:
    return books.load(book_id).model_dump(mode="json")


@app.get("/api/books/{book_id}/query-sets")
def list_query_sets(book_id: str) -> list[str]:
    books.load(book_id)
    return books.list_query_set_ids(book_id)


@app.get("/api/books/{book_id}/query-sets/{query_set_id}")
def get_query_set(book_id: str, query_set_id: str) -> dict[str, object]:
    return books.load_query_set(book_id, query_set_id).model_dump(mode="json")


@app.get("/api/books/{book_id}/capability")
def get_capability(book_id: str) -> dict[str, object]:
    package = books.load(book_id)
    package_root = books.root / book_id
    report = build_capability_report(package, package_root)
    write_capability_report(report, package_root)
    _record_capabilities_path(package_root, "derived/capability.json")
    return report.model_dump(mode="json")


@app.get("/api/books/{book_id}/annotations")
def list_annotations(book_id: str) -> list[dict[str, object]]:
    books.load(book_id)
    package_root = books.root / book_id
    return [
        annotation.model_dump(mode="json")
        for annotation in load_annotations(book_id, package_root)
    ]


@app.post("/api/books/{book_id}/annotations", status_code=201)
def post_annotation(book_id: str, request: AnnotationRequest) -> dict[str, object]:
    package = books.load(book_id)
    package_root = books.root / book_id
    cards = (
        load_qa_cards(package_root)
        if request.target_type is AnnotationTargetType.qa_card
        else []
    )
    annotation, review = create_annotation(
        book_id,
        request.target_type,
        request.target_id,
        request.field,
        request.value,
        request.reviewer,
        reason=request.reason,
        old_value=request.old_value,
        package=package,
        cards=cards,
        package_root=package_root,
    )
    return {
        "annotation": annotation.model_dump(mode="json"),
        "conflict": review is not None,
        "review_item": review.model_dump(mode="json") if review else None,
    }


@app.get("/api/books/{book_id}/review-items")
def get_review_items(book_id: str) -> list[dict[str, object]]:
    books.load(book_id)
    package_root = books.root / book_id
    return [
        item.model_dump(mode="json")
        for item in load_review_items(book_id, package_root)
    ]


@app.get("/api/books/{book_id}/story-plan")
def get_story_plan(book_id: str) -> dict[str, object]:
    package = books.load(book_id)
    package_root = books.root / package.book_id
    story_plan = load_story_plan(package_root)
    return story_plan.model_dump(mode="json")


@app.get("/api/books/{book_id}/scene-plan")
def get_scene_plan(book_id: str) -> dict[str, object]:
    package = books.load(book_id)
    package_root = books.root / package.book_id
    scene_plan = load_scene_plan(package_root)
    return scene_plan.model_dump(mode="json")

@app.get("/api/books/{book_id}/generation-result")
def get_generation_result(book_id: str) -> dict[str, object]:
    package = books.load(book_id)
    package_root = books.root / package.book_id
    result = load_generation_result(package_root)
    return result.model_dump(mode="json")


@app.get("/api/books/{book_id}/timeline")
def get_timeline(book_id: str) -> dict[str, object]:
    package = books.load(book_id)
    package_root = books.root / package.book_id
    return load_timeline(package_root)

@app.get("/api/books/{book_id}/assets/{asset_path:path}")
def get_book_asset(book_id: str, asset_path: str) -> FileResponse:
    return FileResponse(books.resolve_asset(book_id, asset_path))


@app.post("/api/books/ingest")
async def ingest(request: IngestRequest) -> dict[str, object]:
    archive_path = Path(request.archive_path).expanduser().resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(f"archive not found: {archive_path}")
    package_root = await run_in_threadpool(
        ingest_book,
        archive_path,
        request.book_key,
        BOOK_ROOT,
        render_scale=request.render_scale,
        force=request.force,
    )
    return books.load(package_root.name).model_dump(mode="json")


@app.post("/api/books/ingest/upload", status_code=202)
async def ingest_upload(
    archive: UploadFile = File(...),
    book_key: str = Form(...),
    force: bool = Form(False),
    render_scale: float = Form(2.0),
) -> dict[str, object]:
    filename = archive.filename or ""
    if not filename.lower().endswith(".zip"):
        raise ValueError("archive must be a ZIP file")

    job = await run_in_threadpool(
        ingestions.submit_upload,
        archive.file,
        filename,
        book_key,
        force=force,
        render_scale=render_scale,
    )
    return job.model_dump(mode="json")


@app.post("/api/books/{book_id}/generate", status_code=202)
def generate(book_id: str) -> dict[str, object]:
    books.load(book_id)
    return jobs.submit(book_id).model_dump(mode="json")


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, object]:
    return jobs.store.get(job_id).model_dump(mode="json")


@app.post("/api/interact", response_model=InteractionResponse)
def interact(request: InteractionRequest) -> InteractionResponse:
    """v2 交互入口：在线 Conductor 选工具执行，每轮落 Turn + Trace。"""
    package = books.load(request.book_id)
    return run_interaction(
        request,
        package,
        books.package_root(request.book_id),
        data_root=books.root.parent,
    )


@app.post("/api/qa", response_model=InteractionResponse)
def qa(request: InteractionRequest) -> InteractionResponse:
    """兼容别名：等价于 `POST /api/interact` 且 `kind=qa`。"""
    payload = request.model_dump()
    payload["kind"] = InteractionKind.qa
    package = books.load(request.book_id)
    return run_interaction(
        InteractionRequest.model_validate(payload),
        package,
        books.package_root(request.book_id),
        data_root=books.root.parent,
    )


@app.get("/api/tools")
def list_tools() -> list[dict[str, str]]:
    """在线工具注册表：前端“链路”面板直接展示这份清单。"""
    return describe_tools()


@app.get("/api/providers")
def list_providers() -> list[dict[str, object]]:
    """Configured model providers and whether they are usable right now."""
    config = load_config()
    rows: list[dict[str, object]] = []
    for item in provider_status(config):
        section = config.get(item.kind, {}) or {}
        # The runtime name (e.g. "chat_llm") is not always the config key
        # ("openai_compatible"); fall back to the section's own option block.
        options = section.get(item.provider) or section.get("openai_compatible") or {}
        rows.append(
            {
                "kind": item.kind,
                "provider": item.provider,
                "available": item.available,
                "detail": item.detail,
                "model": str(
                    options.get("model")
                    or options.get("model_env")
                    or ""
                ),
                "base_url": str(options.get("base_url") or ""),
            }
        )
    rows.append(
        {
            "kind": "tts",
            "provider": "edge_tts",
            "available": edge_tts_available(),
            "detail": "" if edge_tts_available() else "edge-tts not installed",
            "model": "zh-CN-XiaoyiNeural / en-US-AriaNeural",
            "base_url": "",
        }
    )
    return rows


@app.get("/api/books/{book_id}/turns")
def get_turns(
    book_id: str,
    session_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    books.load(book_id)
    return read_turns(
        book_id,
        data_root=books.root.parent,
        session_id=session_id,
        limit=max(1, min(limit, 200)),
    )


@app.get("/api/books/{book_id}/traces")
def get_traces(
    book_id: str,
    session_id: str | None = None,
    limit: int = 30,
) -> list[dict[str, object]]:
    books.load(book_id)
    return read_traces(
        book_id,
        data_root=books.root.parent,
        session_id=session_id,
        limit=max(1, min(limit, 100)),
    )


@app.get("/api/eval/latest")
def get_latest_eval() -> dict[str, object]:
    """最近一次 `python -m pipeline eval` 的 run.json；没有就返回空对象。"""
    return latest_eval_run(REPOSITORY_ROOT) or {}


def _record_capabilities_path(package_root: Path, relative: str) -> None:
    """能力报告落盘后把路径记回 book.json，保持两个产物一致。"""
    manifest_path = package_root / "book.json"
    if not manifest_path.is_file():
        return
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if data.get("capabilities_path") == relative:
        return
    data["capabilities_path"] = relative
    manifest_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app.api:app", host="127.0.0.1", port=8000, reload=True)

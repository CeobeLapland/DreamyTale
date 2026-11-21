from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from backend.app.ingest_jobs import IngestionJobManager
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.app.ingest import ingest_book
from backend.app.jobs import JobManager, JobNotFoundError, JobStore
from backend.app.store import (
    BookNotFoundError,
    BookStore,
    InvalidBookPackageError,
)
from backend.app.validation import ContractError


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BOOK_ROOT = Path(
    os.environ.get("DREAMYTALE_BOOK_ROOT", REPOSITORY_ROOT / "temp" / "books")
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


class QARequestModel(BaseModel):
    book_id: str
    page_index: int = Field(ge=1)
    current_time_ms: int = Field(ge=0)
    hotspot_id: str | None = None
    question_text: str | None = None
    audio_path: str | None = None


app = FastAPI(
    title="DreamyTale Backend",
    version="0.1.0",
    description="Book package, generation job and QA API for DreamyTale.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

books = BookStore(BOOK_ROOT)
job_store = JobStore(JOB_STORE_PATH)
jobs = JobManager(job_store)
ingestions = IngestionJobManager(
    job_store,
    BOOK_ROOT,
    UPLOAD_ROOT,
)


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


@app.exception_handler(BookNotFoundError)
async def handle_book_not_found(_request, exc: BookNotFoundError) -> JSONResponse:
    return _error(404, "book_not_found", str(exc))


@app.exception_handler(InvalidBookPackageError)
async def handle_invalid_book(
    _request,
    exc: InvalidBookPackageError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "invalid_book_package",
                "message": str(exc),
                "details": exc.errors,
            }
        },
    )


@app.exception_handler(JobNotFoundError)
async def handle_job_not_found(_request, exc: JobNotFoundError) -> JSONResponse:
    return _error(404, "job_not_found", str(exc))


@app.exception_handler(ContractError)
async def handle_contract_error(_request, exc: ContractError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "invalid_data_contract",
                "message": "book package does not satisfy the data contract",
                "details": exc.errors,
            }
        },
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
                "page_count": package.page_count,
            }
        )
    return summaries


@app.get("/api/books/{book_id}")
def get_book(book_id: str) -> dict[str, object]:
    return books.load(book_id).to_dict()


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
    return books.load(package_root.name).to_dict()

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
    return job.to_dict()

@app.post("/api/books/{book_id}/generate", status_code=202)
def generate(book_id: str) -> dict[str, object]:
    books.load(book_id)
    return jobs.submit(book_id).to_dict()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, object]:
    return jobs.store.get(job_id).to_dict()


@app.post("/api/qa")
def qa(_request: QARequestModel) -> JSONResponse:
    return _error(
        503,
        "qa_not_configured",
        "QA runtime is not configured; provide a QA adapter before enabling this endpoint",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app.api:app", host="127.0.0.1", port=8000, reload=True)

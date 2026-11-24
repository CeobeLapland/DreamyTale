"""Deterministic multi-agent orchestration for the offline content pipeline.

This follows `docs/ARCHITECTURE.md` §3.2: agents do not chat, they hand over
structured artifacts in a fixed dependency graph. The orchestrator owns stage
registration, dependency order, retries, timeouts, cache, the generation
manifest and the trace.

The stage functions themselves are unchanged; this module wraps them. That is
deliberate: `pipeline/story.py` etc. can still be run alone with the old CLI.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from contracts.models import (
    GenerationManifest,
    ManifestArtifact,
    ManifestStage,
    Trace,
    TraceStage,
)

from .config import DATA, DEFAULT_DPI, ROOT, BookSpec

MANIFEST = Path("derived") / "manifest.json"
TRACE_ROOT = DATA.parent / "traces"
STAGE_VERSION = "v1"


class OrchestrationError(RuntimeError):
    """A required stage failed; the job should be marked failed."""

    def __init__(self, message: str, report: "RunReport") -> None:
        super().__init__(message)
        self.report = report


@dataclass
class StageOutcome:
    outputs: list[str] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    prompt_version: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    degraded: bool = False
    error_code: str | None = None
    detail: str = ""
    skipped: bool = False


@dataclass(frozen=True)
class Stage:
    name: str
    agent: str
    job_stage: str
    depends_on: tuple[str, ...]
    run: Callable[[BookSpec], StageOutcome]
    outputs: tuple[str, ...]
    required: bool = True
    retries: int = 0
    timeout_s: int = 900
    version: str = STAGE_VERSION
    extra_inputs: tuple[str, ...] = ()


@dataclass
class RunStage:
    name: str
    agent: str
    status: str
    ms: int = 0
    cached: bool = False
    degraded: bool = False
    detail: str = ""
    error_code: str | None = None
    output_hash: str | None = None


@dataclass
class RunReport:
    book_id: str
    status: str
    stages: list[RunStage]
    manifest_path: str | None
    trace_path: str | None
    seconds: float
    cached: int = 0
    degraded: int = 0
    failed: str | None = None


# ---------------------------------------------------------------------------
# Stage wrappers: the existing pipeline functions, unchanged.
# ---------------------------------------------------------------------------


def _run_ingest(spec: BookSpec) -> StageOutcome:
    from .ingest import ingest_book

    book = ingest_book(spec, dpi=DEFAULT_DPI)
    return StageOutcome(
        outputs=["book.json"],
        provider="local",
        model="pymupdf/pdfium",
        params={"pages": book.page_count},
        detail=f"pages={book.page_count}",
    )


def _run_scripts(spec: BookSpec) -> StageOutcome:
    try:
        script = spec.script_path
    except FileNotFoundError:
        return StageOutcome(
            skipped=True,
            detail="no script for this book",
        )
    from .query_sets import parse_script

    query_set = parse_script(spec)
    return StageOutcome(
        outputs=[f"query_sets/{query_set.query_set_id}.json"],
        provider="local",
        model="script-parser-v1",
        params={"items": len(query_set.items)},
        detail=f"items={len(query_set.items)}",
    )


def _run_ocr(spec: BookSpec) -> StageOutcome:
    from .models import build_ocr
    from .understanding import run_ocr_all

    provider = build_ocr()
    report = (run_ocr_all([spec], provider) or [{}])[0]
    available = bool(report.get("available"))
    return StageOutcome(
        outputs=["book.json"],
        provider=provider.name,
        model=getattr(provider, "model", "") or provider.name,
        params={
            "pages": report.get("pages_processed", 0),
            "accepted": report.get("accepted", 0),
            "errors": len(report.get("errors", [])),
        },
        degraded=not available,
        error_code=None if available else "OCR_UNAVAILABLE",
        detail=f"accepted={report.get('accepted', 0)}",
    )


def _run_vlm(spec: BookSpec) -> StageOutcome:
    from .models import build_vlm
    from .narrative import run_vlm_all

    provider = build_vlm()
    report = (run_vlm_all([spec], provider) or [{}])[0]
    available = bool(report.get("available"))
    return StageOutcome(
        outputs=["derived/understanding/narrative.jsonl"],
        provider=provider.name,
        model=getattr(provider, "model", "") or provider.name,
        params={
            "auto": report.get("pages_processed", 0),
            "human": report.get("pages_human", 0),
            "errors": len(report.get("errors", [])),
        },
        degraded=not available,
        error_code=None if available else "VLM_UNAVAILABLE",
        detail=f"auto={report.get('pages_processed', 0)} human={report.get('pages_human', 0)}",
    )


def _run_story(spec: BookSpec) -> StageOutcome:
    from .models import build_llm
    from .story import PROMPT_VERSION, run_story

    llm = build_llm()
    report = run_story(spec, llm)
    skipped = bool(report.get("skipped"))
    fallback = int(report.get("pages_fallback", 0) or 0)
    return StageOutcome(
        outputs=["derived/story/story_plan.json"],
        provider=llm.name,
        model=getattr(llm, "model", "") or llm.name,
        prompt_version=PROMPT_VERSION,
        params={
            "llm_pages": report.get("pages_llm", 0),
            "fallback_pages": fallback,
            "characters": report.get("characters", 0),
        },
        degraded=skipped or fallback > 0,
        error_code="STORY_SKIPPED" if skipped else ("STORY_FALLBACK" if fallback else None),
        detail=str(report.get("reason") or f"fallback={fallback}"),
    )


def _run_scene(spec: BookSpec) -> StageOutcome:
    from .scene import run_scene

    report = run_scene(spec)
    return StageOutcome(
        outputs=[
            "derived/scene/scene_plan.json",
            "derived/scene/timeline.json",
        ],
        provider="local",
        model="scene-planner-v1",
        prompt_version="scene-v1",
        params={
            "pages": report.get("pages", 0),
            "scenes": report.get("scenes", 0),
            "total_ms": report.get("total_ms", 0),
        },
        detail=f"scenes={report.get('scenes', 0)}",
    )


def _run_tts(spec: BookSpec) -> StageOutcome:
    from .tts import run_tts

    report = run_tts(spec)
    available = bool(report.get("available"))
    return StageOutcome(
        outputs=["derived/audio/narration"],
        provider="edge_tts" if available else "null",
        model="edge-tts" if available else "none",
        params={
            "files": len(report.get("files", [])),
            "errors": len(report.get("errors", [])),
        },
        degraded=not available or bool(report.get("errors")),
        error_code=None if available else "TTS_UNAVAILABLE",
        detail=f"files={len(report.get('files', []))}",
    )


def _run_retime(spec: BookSpec) -> StageOutcome:
    from .retime import retime_book

    report = retime_book(spec)
    return StageOutcome(
        outputs=["derived/scene/timeline.json"],
        provider="local",
        model="retime-v1",
        params={
            "changed_pages": report.get("changed_pages", 0),
            "total_ms": report.get("total_ms", 0),
        },
        detail=f"changed={report.get('changed_pages', 0)}",
    )


def _run_index(spec: BookSpec) -> StageOutcome:
    from .index import build_index

    report = build_index(spec)
    return StageOutcome(
        outputs=[
            "derived/index/search_index.json",
            "derived/index/scene_index.json",
        ],
        provider="local",
        model="index-v1",
        params={
            "entries": report.get("entries", 0),
            "scenes": report.get("scenes", 0),
        },
        detail=f"entries={report.get('entries', 0)}",
    )


def _run_knowledge(spec: BookSpec) -> StageOutcome:
    query_sets = sorted((DATA / spec.book_id / "query_sets").glob("*.json"))
    if not query_sets:
        return StageOutcome(skipped=True, detail="no query set")
    from .knowledge import build_knowledge
    from .models import build_llm

    llm = build_llm()
    report = build_knowledge(spec, llm=llm if llm.available() else None)
    return StageOutcome(
        outputs=[
            "derived/knowledge/cards.jsonl",
            "derived/knowledge/uncovered.json",
        ],
        provider=llm.name if llm.available() else "page-text",
        model=getattr(llm, "model", "") if llm.available() else "page-text",
        params={
            "cards": report.get("cards", 0),
            "uncovered": report.get("uncovered", 0),
        },
        detail=f"cards={report.get('cards', 0)} uncovered={report.get('uncovered', 0)}",
    )


def _run_hotspots(spec: BookSpec) -> StageOutcome:
    query_sets = sorted((DATA / spec.book_id / "query_sets").glob("*.json"))
    if not query_sets:
        return StageOutcome(skipped=True, detail="no query set")
    from .hotspots import build_hotspots
    from .models import build_vlm

    vlm = build_vlm()
    report = build_hotspots(spec, vlm=vlm if vlm.available() else None)
    unresolved = list(report.get("unresolved", []) or [])
    return StageOutcome(
        outputs=["book.json"],
        provider=vlm.name if vlm.available() else "text-layer",
        model=getattr(vlm, "model", "") if vlm.available() else "text-layer",
        params={
            "targets": report.get("targets", 0),
            "hotspots": report.get("hotspots", 0),
            "unresolved": len(unresolved),
        },
        degraded=bool(unresolved),
        error_code="HOTSPOTS_UNRESOLVED" if unresolved else None,
        detail=f"hotspots={report.get('hotspots', 0)} unresolved={len(unresolved)}",
    )


def _run_video(spec: BookSpec) -> StageOutcome:
    from .video import run_video

    report = run_video(spec)
    if not report.get("book_video"):
        raise RuntimeError("video pipeline produced no book video")
    return StageOutcome(
        outputs=[
            "derived/video/book.mp4",
            "derived/generation_result.json",
        ],
        provider="local",
        model="page-animation-v1",
        params={
            "scenes": report.get("scenes", 0),
            "pages": report.get("pages", 0),
            "errors": len(report.get("errors", [])),
        },
        degraded=bool(report.get("errors")),
        error_code="VIDEO_PARTIAL" if report.get("errors") else None,
        detail=f"pages={report.get('pages', 0)}",
    )


def _run_compose(spec: BookSpec) -> StageOutcome:
    from .final import render_final

    report = render_final(spec)
    if not Path(report["final_video"]).is_file():
        raise RuntimeError("final composition produced no MP4")
    audio_pages = int(report.get("audio_pages", 0) or 0)
    return StageOutcome(
        outputs=[
            "derived/video/final.mp4",
            "derived/video/subtitles.srt",
        ],
        provider="local",
        model="ffmpeg-or-cv2",
        params={
            "frames": report.get("frames", 0),
            "subtitles": report.get("subtitle_entries", 0),
            "audio_pages": audio_pages,
        },
        degraded=audio_pages == 0,
        error_code="NO_AUDIO" if audio_pages == 0 else None,
        detail=f"subtitles={report.get('subtitle_entries', 0)} audio_pages={audio_pages}",
    )


def _run_critic(spec: BookSpec) -> StageOutcome:
    from .critic import run_critic

    report = run_critic(spec)
    warnings = list(report.get("warnings", []) or [])
    errors = [
        item
        for item in warnings
        if item.get("code") in {"video_missing", "timeline_invalid"}
    ]
    stats = report.get("stats", {}) or {}
    return StageOutcome(
        outputs=["derived/critic/report.json"],
        provider="local",
        model="critic-v1",
        params={
            "pages": stats.get("pages", 0),
            "scenes": stats.get("scenes", 0),
            "audio_pages": stats.get("audio_pages", 0),
            "warnings": len(warnings),
            "errors": len(errors),
        },
        degraded=bool(warnings),
        error_code="CRITIC_WARNINGS" if warnings else None,
        detail=f"warnings={len(warnings)} errors={len(errors)}",
    )


# ---------------------------------------------------------------------------
# Stage registry: one row per agent handoff.
# ---------------------------------------------------------------------------

STAGES: tuple[Stage, ...] = (
    Stage(
        "ingest", "Librarian", "ingest", (), _run_ingest, ("book.json",),
        required=True, retries=0, timeout_s=900,
    ),
    Stage(
        "scripts", "Librarian", "ingest", ("ingest",), _run_scripts,
        ("query_sets",), required=False, retries=0, timeout_s=300,
    ),
    Stage(
        "ocr", "Reader", "ocr", ("ingest",), _run_ocr, ("book.json",),
        required=False, retries=1, timeout_s=900,
    ),
    Stage(
        "vlm", "Reader", "vlm", ("ingest",), _run_vlm,
        ("derived/understanding/narrative.jsonl",),
        required=False, retries=1, timeout_s=900,
    ),
    Stage(
        "story", "Storyteller", "story", ("vlm",), _run_story,
        ("derived/story/story_plan.json",),
        required=True, retries=1, timeout_s=900,
        extra_inputs=("book.json",),
    ),
    Stage(
        "scene", "Director", "scene", ("story",), _run_scene,
        ("derived/scene/scene_plan.json", "derived/scene/timeline.json"),
        required=True, retries=0, timeout_s=300,
    ),
    Stage(
        "tts", "VoiceActor", "tts", ("story",), _run_tts,
        ("derived/audio/narration",), required=False, retries=1, timeout_s=900,
    ),
    Stage(
        "retime", "VoiceActor", "tts", ("tts", "scene"), _run_retime,
        ("derived/scene/timeline.json",), required=False, retries=0, timeout_s=300,
    ),
    Stage(
        "index", "Curator", "index", ("scene", "vlm"), _run_index,
        ("derived/index/search_index.json", "derived/index/scene_index.json"),
        required=True, retries=0, timeout_s=300,
        extra_inputs=("book.json",),
    ),
    Stage(
        "knowledge", "Curator", "index", ("index", "story", "scripts"), _run_knowledge,
        ("derived/knowledge/cards.jsonl", "derived/knowledge/uncovered.json"),
        required=False, retries=1, timeout_s=900,
        extra_inputs=("book.json",),
    ),
    Stage(
        "hotspots", "Curator", "index", ("scripts", "ocr", "vlm"), _run_hotspots,
        ("book.json",), required=False, retries=1, timeout_s=900,
    ),
    Stage(
        "video", "Animator", "video", ("scene", "retime"), _run_video,
        ("derived/video/book.mp4", "derived/generation_result.json"),
        required=True, retries=0, timeout_s=1800,
    ),
    Stage(
        "compose", "Compose", "compose", ("video", "retime"), _run_compose,
        ("derived/video/final.mp4", "derived/video/subtitles.srt"),
        required=True, retries=0, timeout_s=900,
    ),
    Stage(
        "critic", "Critic", "compose", ("compose",), _run_critic,
        ("derived/critic/report.json",),
        required=False, retries=0, timeout_s=120,
    ),
)

STAGES_BY_NAME = {stage.name: stage for stage in STAGES}
STAGE_ORDER = [stage.name for stage in STAGES]


# ---------------------------------------------------------------------------
# Hashing, cache and manifest helpers.
# ---------------------------------------------------------------------------


def _sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def _path_sha(path: Path) -> str:
    if path.is_file():
        return _file_sha(path)
    if path.is_dir():
        items = [
            (str(item.relative_to(path)).replace("\\", "/"), _file_sha(item))
            for item in sorted(path.rglob("*"))
            if item.is_file()
        ]
        return _sha(items)
    return ""


def _book_root(spec: BookSpec) -> Path:
    return DATA / spec.book_id


def _global_input_hash(spec: BookSpec) -> str:
    """Inputs that are not produced by the pipeline itself.

    `book.json` is deliberately excluded: stages rewrite it (OCR, hotspots),
    and including it would make every stage miss its own cache.
    """
    root = _book_root(spec)
    return _sha(
        {
            "source": _path_sha(root / "source"),
            "query_sets": _path_sha(root / "query_sets"),
            "manual": _path_sha(root / "manual"),
            "manual_narrative": _path_sha(root / "manual" / "narrative.json"),
            "manual_annotations": _path_sha(root / "manual" / "annotations.jsonl"),
            "config": _path_sha(ROOT / "config" / "models.yaml"),
        }
    )


def _outputs_exist(spec: BookSpec, paths: tuple[str, ...] | list[str]) -> bool:
    root = _book_root(spec)
    for relative in paths:
        path = root / relative
        if path.is_dir():
            if not any(item.is_file() for item in path.rglob("*")):
                return False
        elif not path.is_file():
            return False
    return True


def _output_hash(spec: BookSpec, paths: tuple[str, ...] | list[str]) -> str:
    root = _book_root(spec)
    return _sha(
        [
            [relative, _path_sha(root / relative)]
            for relative in paths
            if (root / relative).exists()
        ]
    )


def _stage_key(
    spec: BookSpec,
    stage: Stage,
    keys: dict[str, str],
    existing: GenerationManifest | None,
    global_hash: str,
) -> str:
    parents: dict[str, str] = {}
    for parent in stage.depends_on:
        key = keys.get(parent)
        if not key and existing is not None:
            key = next(
                (str(item.params.get("stage_key") or "") for item in existing.stages if item.name == parent),
                "",
            )
        parents[parent] = key
    extras = {relative: _path_sha(_book_root(spec) / relative) for relative in stage.extra_inputs}
    return _sha(
        {
            "global": global_hash,
            "parents": parents,
            "extras": extras,
            "version": stage.version,
            "job_stage": stage.job_stage,
        }
    )


def _existing_stage(
    existing: GenerationManifest | None,
    name: str,
) -> ManifestStage | None:
    if existing is None:
        return None
    return next((item for item in existing.stages if item.name == name), None)


def _cache_hit(
    spec: BookSpec,
    stage: Stage,
    key: str,
    existing: GenerationManifest | None,
    *,
    force: bool,
) -> bool:
    if force:
        return False
    # Never re-run ingest over an existing book just because an older manifest
    # did not record the stage: re-ingest would wipe OCR/narrative/hotspots.
    # A source change is an explicit `--force --from ingest`.
    if stage.name == "ingest":
        return (_book_root(spec) / "book.json").is_file()
    previous = _existing_stage(existing, stage.name)
    if previous is None:
        return False
    if str(previous.params.get("stage_key") or "") != key:
        return False
    return _outputs_exist(spec, stage.outputs)


def _load_manifest(path: Path) -> GenerationManifest | None:
    if not path.is_file():
        return None
    try:
        return GenerationManifest.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except Exception:  # noqa: BLE001 - a corrupt manifest must not block a rerun
        return None


def _artifacts_for(spec: BookSpec, paths: tuple[str, ...] | list[str]) -> list[ManifestArtifact]:
    root = _book_root(spec)
    artifacts: list[ManifestArtifact] = []
    for relative in paths:
        path = root / relative
        if path.is_file():
            artifacts.append(ManifestArtifact(path=relative, sha256=_file_sha(path)))
        elif path.is_dir():
            for item in sorted(path.rglob("*")):
                if item.is_file():
                    artifacts.append(
                        ManifestArtifact(
                            path=str(item.relative_to(root)).replace("\\", "/"),
                            sha256=_file_sha(item),
                        )
                    )
    return artifacts


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _manifest_status(records: list[ManifestStage]) -> str:
    if any(record.status == "failed" for record in records):
        return "failed"
    if any(record.degraded for record in records):
        return "degraded"
    return "completed"


def _write_manifest(
    spec: BookSpec,
    existing: GenerationManifest | None,
    records: list[ManifestStage],
    artifacts: list[ManifestArtifact],
    input_hash: str,
) -> tuple[Path, str]:
    by_name = {item.name: item for item in (existing.stages if existing else [])}
    for record in records:
        by_name[record.name] = record
    ordered = [by_name[name] for name in STAGE_ORDER if name in by_name]
    artifact_by_path = {
        item.path: item for item in (existing.artifacts if existing else [])
    }
    for artifact in artifacts:
        artifact_by_path[artifact.path] = artifact

    generation_version = (existing.generation_version + 1) if existing else 1
    status = _manifest_status(ordered)
    manifest = GenerationManifest(
        manifest_id=f"manifest-{spec.book_id}-{generation_version:03d}",
        book_id=spec.book_id,
        generation_version=generation_version,
        input_hash=input_hash,
        stages=ordered,
        artifacts=sorted(artifact_by_path.values(), key=lambda item: item.path),
        model_versions={
            item.name: (item.model or item.provider) for item in ordered
        },
        prompt_versions={
            item.name: item.prompt_version
            for item in ordered
            if item.prompt_version
        },
        created_at=_now(),
        status=status,
    )
    path = _book_root(spec) / MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path, status


def _write_trace(
    spec: BookSpec,
    report: RunReport,
    manifest_path: Path | None,
) -> Path:
    trace_id = (
        f"trace-{spec.book_id}-{_now().strftime('%Y%m%d-%H%M%S')}-"
        f"{uuid.uuid4().hex[:6]}"
    )
    trace = Trace(
        trace_id=trace_id,
        kind="generation",
        input={"book_id": spec.book_id, "stages": [stage.name for stage in report.stages]},
        stages=[
            TraceStage(
                name=stage.name,
                ms=stage.ms,
                ok=stage.status not in {"failed"},
            )
            for stage in report.stages
        ],
        result={
            "status": report.status,
            "manifest_path": str(manifest_path) if manifest_path else None,
            "cached": report.cached,
            "degraded": report.degraded,
            "failed": report.failed,
        },
        latency_ms=int(report.seconds * 1000),
        output_hash=_file_sha(manifest_path) if manifest_path and manifest_path.is_file() else None,
        created_at=_now(),
    )
    day = _now().strftime("%Y-%m-%d")
    path = TRACE_ROOT / day / f"{trace_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(trace.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Execution.
# ---------------------------------------------------------------------------


def select_stages(
    from_stage: str | None = None,
    to_stage: str | None = None,
) -> list[Stage]:
    if from_stage and from_stage not in STAGES_BY_NAME:
        raise ValueError(f"unknown --from stage: {from_stage}")
    if to_stage and to_stage not in STAGES_BY_NAME:
        raise ValueError(f"unknown --to stage: {to_stage}")
    start = STAGE_ORDER.index(from_stage) if from_stage else 0
    end = STAGE_ORDER.index(to_stage) + 1 if to_stage else len(STAGE_ORDER)
    if start >= end:
        raise ValueError("--from must come before --to")
    return [STAGES_BY_NAME[name] for name in STAGE_ORDER[start:end]]


def _execute_stage(stage: Stage, spec: BookSpec) -> StageOutcome:
    attempts = stage.retries + 1
    last_error: BaseException | None = None
    for attempt in range(attempts):
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(stage.run, spec)
        try:
            return future.result(timeout=stage.timeout_s)
        except FutureTimeoutError:
            last_error = TimeoutError(
                f"{stage.name} timed out after {stage.timeout_s}s"
            )
        except Exception as exc:  # noqa: BLE001 - retried below
            last_error = exc
        finally:
            # A timed-out thread cannot be killed on Windows; the provider
            # timeouts are the hard stop. The orchestrator records the failure.
            pool.shutdown(wait=False, cancel_futures=True)
        if attempt < attempts - 1:
            time.sleep(0.5 * (attempt + 1))
    assert last_error is not None
    raise last_error


def run_book(
    spec: BookSpec,
    *,
    from_stage: str | None = None,
    to_stage: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    progress: Callable[[str, float], None] | None = None,
) -> RunReport:
    """Run the registered DAG for one book.

    `progress` receives the coarse `JobStage` name and a 0–1 fraction.
    `dry_run` only reports cache state; it never calls a stage.
    """
    started = time.perf_counter()
    stages = select_stages(from_stage, to_stage)
    book_root = _book_root(spec)
    manifest_path = book_root / MANIFEST
    existing = _load_manifest(manifest_path)
    global_hash = _global_input_hash(spec)

    keys: dict[str, str] = {}
    if existing is not None:
        for item in existing.stages:
            keys[item.name] = str(item.params.get("stage_key") or "")

    run_stages: list[RunStage] = []
    records: list[ManifestStage] = []
    artifacts: list[ManifestArtifact] = []
    cached_count = 0
    degraded_count = 0
    failed_stage: str | None = None

    for index, stage in enumerate(stages):
        key = _stage_key(spec, stage, keys, existing, global_hash)
        keys[stage.name] = key
        # Re-ingesting an existing book rewrites book.json and would destroy
        # OCR/narrative/hotspots. Make that an explicit `--from ingest --force`.
        force_stage = force and not (
            stage.name == "ingest" and from_stage != "ingest"
        )
        cached = _cache_hit(spec, stage, key, existing, force=force_stage)

        if dry_run:
            previous = _existing_stage(existing, stage.name)
            status = "cached" if cached else "miss"
            if cached and previous is not None and previous.status == "skipped":
                status = "skipped"
            run_stages.append(
                RunStage(
                    name=stage.name,
                    agent=stage.agent,
                    status=status,
                    cached=cached,
                    detail=f"key={key[:8]}",
                )
            )
            if progress:
                progress(stage.job_stage, (STAGE_ORDER.index(stage.name) + 1) / len(STAGE_ORDER))
            continue

        if cached:
            previous = _existing_stage(existing, stage.name)
            cached_count += 1
            if previous is not None and previous.degraded:
                degraded_count += 1
            record = previous if previous is not None else ManifestStage(
                name=stage.name,
                provider="local",
                model="existing-artifact",
                params={"stage_key": key},
                duration_ms=0,
                status="cached",
                degraded=False,
            )
            run_stages.append(
                RunStage(
                    name=stage.name,
                    agent=stage.agent,
                    status="cached",
                    cached=True,
                    degraded=record.degraded,
                    detail="cache hit",
                    error_code=record.error_code,
                    output_hash=record.output_hash,
                )
            )
            records.append(
                record.model_copy(
                    update={
                        "params": {**record.params, "stage_key": key, "cached": True},
                    }
                )
            )
            artifacts.extend(_artifacts_for(spec, stage.outputs))
            if progress:
                progress(stage.job_stage, (STAGE_ORDER.index(stage.name) + 1) / len(STAGE_ORDER))
            continue

        started_at = _now()
        stage_started = time.perf_counter()
        try:
            outcome = _execute_stage(stage, spec)
        except BaseException as exc:  # noqa: BLE001 - recorded, not swallowed
            elapsed = int((time.perf_counter() - stage_started) * 1000)
            error_code = getattr(exc, "code", None) or type(exc).__name__.upper()
            detail = f"{type(exc).__name__}: {exc}"[:200]
            failed_stage = stage.name
            records.append(
                ManifestStage(
                    name=stage.name,
                    provider="",
                    model="",
                    params={"stage_key": key},
                    started_at=started_at,
                    duration_ms=elapsed,
                    status="failed",
                    error_code=error_code,
                    degraded=False,
                    output_hash=None,
                )
            )
            run_stages.append(
                RunStage(
                    name=stage.name,
                    agent=stage.agent,
                    status="failed",
                    ms=elapsed,
                    detail=detail,
                    error_code=error_code,
                )
            )
            if progress:
                progress(stage.job_stage, (STAGE_ORDER.index(stage.name) + 1) / len(STAGE_ORDER))
            if stage.required:
                break
            degraded_count += 1
            continue

        elapsed = int((time.perf_counter() - stage_started) * 1000)
        status = "skipped" if outcome.skipped else ("degraded" if outcome.degraded else "completed")
        if outcome.degraded:
            degraded_count += 1
        outputs = outcome.outputs or list(stage.outputs)
        output_hash = _output_hash(spec, outputs) if not outcome.skipped else None
        records.append(
            ManifestStage(
                name=stage.name,
                provider=outcome.provider or "local",
                model=outcome.model or outcome.provider or "local",
                model_version=stage.version,
                prompt_version=outcome.prompt_version,
                params={"stage_key": key, **outcome.params},
                seed=None,
                started_at=started_at,
                duration_ms=elapsed,
                status=status,
                error_code=outcome.error_code,
                degraded=outcome.degraded,
                output_hash=output_hash,
            )
        )
        run_stages.append(
            RunStage(
                name=stage.name,
                agent=stage.agent,
                status=status,
                ms=elapsed,
                degraded=outcome.degraded,
                detail=outcome.detail,
                error_code=outcome.error_code,
                output_hash=output_hash,
            )
        )
        if not outcome.skipped:
            artifacts.extend(_artifacts_for(spec, outputs))
        if progress:
            progress(stage.job_stage, (STAGE_ORDER.index(stage.name) + 1) / len(STAGE_ORDER))

    seconds = time.perf_counter() - started
    if dry_run:
        return RunReport(
            book_id=spec.book_id,
            status="dry-run",
            stages=run_stages,
            manifest_path=str(manifest_path),
            trace_path=None,
            seconds=seconds,
            cached=sum(1 for item in run_stages if item.cached),
        )

    final_manifest_path, manifest_status = _write_manifest(
        spec, existing, records, artifacts, global_hash
    )
    report = RunReport(
        book_id=spec.book_id,
        status=manifest_status,
        stages=run_stages,
        manifest_path=str(final_manifest_path),
        trace_path=None,
        seconds=seconds,
        cached=cached_count,
        degraded=degraded_count,
        failed=failed_stage,
    )
    trace_path = _write_trace(spec, report, final_manifest_path)
    report.trace_path = str(trace_path)
    if failed_stage:
        raise OrchestrationError(
            f"{spec.book_id}: required stage {failed_stage} failed",
            report,
        )
    return report

"""文件型 Job 队列，形状对齐契约 §10 的 v2 Job。

Job 的字段、状态枚举和错误码都以 `contracts.models.Job` 为准；这里只负责持久化
和状态流转，不自己定义第二套结构。
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Protocol

from backend.app.models import Job, JobStage, JobStatus


ProgressReporter = Callable[[str, float], None]

# 契约 §10 的阶段 -> 错误码映射。
STAGE_ERROR_CODES = {
    JobStage.ingest: "INGEST_RENDER_FAILED",
    JobStage.ocr: "OCR_FAILED",
    JobStage.vlm: "VLM_FAILED",
    JobStage.story: "STORY_FAILED",
    JobStage.scene: "SCENE_FAILED",
    JobStage.video: "VIDEO_FAILED",
    JobStage.tts: "TTS_FAILED",
    JobStage.compose: "COMPOSE_FAILED",
    JobStage.index: "INDEX_FAILED",
}
# 契约 §10 里标了不可重试的错误码。
NON_RETRYABLE_ERROR_CODES = {"INGEST_SOURCE_MISSING"}


class JobNotFoundError(LookupError):
    pass


class GenerationRunner(Protocol):
    def run(self, book_id: str, report: ProgressReporter) -> object | None: ...


class UnavailableGenerationRunner:
    def run(self, book_id: str, report: ProgressReporter) -> object | None:
        raise RuntimeError("generation pipeline is not configured")


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def error_code_for(stage: JobStage, exc: BaseException) -> str:
    if isinstance(exc, FileNotFoundError):
        return "INGEST_SOURCE_MISSING"
    return STAGE_ERROR_CODES.get(stage, "GENERATION_FAILED")


class JobStore:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _load_unlocked(self) -> dict[str, dict[str, object]]:
        if not self.path.is_file():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"job store must contain an object: {self.path}")
        return data

    def _write_unlocked(self, data: dict[str, dict[str, object]]) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def create(self, job: Job) -> Job:
        with self._lock:
            data = self._load_unlocked()
            if job.job_id in data:
                raise ValueError(f"duplicate job id: {job.job_id}")
            data[job.job_id] = job.model_dump(mode="json")
            self._write_unlocked(data)
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            data = self._load_unlocked()
        raw = data.get(job_id)
        if raw is None:
            raise JobNotFoundError(job_id)
        return Job.model_validate(raw)

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        progress: float | None = None,
        error: str | None = None,
        error_code: str | None = None,
        degraded: bool | None = None,
        retryable: bool | None = None,
        manifest_path: str | None = None,
        clear_error: bool = False,
    ) -> Job:
        if status is not None and status not in {item.value for item in JobStatus}:
            raise ValueError(f"invalid job status: {status}")
        if stage is not None and stage not in {item.value for item in JobStage}:
            raise ValueError(f"invalid job stage: {stage}")
        if progress is not None and not 0 <= progress <= 1:
            raise ValueError("job progress must be between 0 and 1")

        with self._lock:
            data = self._load_unlocked()
            raw = data.get(job_id)
            if raw is None:
                raise JobNotFoundError(job_id)
            if status is not None:
                raw["status"] = status
            if stage is not None:
                raw["stage"] = stage
            if progress is not None:
                raw["progress"] = progress
            if degraded is not None:
                raw["degraded"] = degraded
            if retryable is not None:
                raw["retryable"] = retryable
            if manifest_path is not None:
                raw["manifest_path"] = manifest_path
            if clear_error:
                raw["error"] = None
                raw["error_code"] = None
            elif error is not None:
                raw["error"] = error
            if error_code is not None:
                raw["error_code"] = error_code
            raw["updated_at"] = _utc_now().isoformat().replace("+00:00", "Z")
            self._write_unlocked(data)
        return Job.model_validate(raw)


class JobManager:
    def __init__(
        self,
        store: JobStore,
        runner: GenerationRunner | None = None,
    ) -> None:
        self.store = store
        self.runner = runner or UnavailableGenerationRunner()

    def submit(self, book_id: str, *, background: bool = True) -> Job:
        now = _utc_now()
        job = Job(
            job_id=self._new_job_id(book_id),
            book_id=book_id,
            status=JobStatus.queued,
            stage=JobStage.story,
            progress=0.0,
            created_at=now,
            updated_at=now,
        )
        self.store.create(job)
        if background:
            thread = threading.Thread(
                target=self._execute,
                args=(job.job_id, book_id),
                name=f"generation-{job.job_id}",
                daemon=True,
            )
            thread.start()
        else:
            self._execute(job.job_id, book_id)
        return self.store.get(job.job_id)

    def _execute(self, job_id: str, book_id: str) -> None:
        self.store.update(
            job_id,
            status=JobStatus.running.value,
            progress=0.01,
            clear_error=True,
        )

        stage = JobStage.story

        def report(stage_name: str, progress: float) -> None:
            nonlocal stage
            try:
                stage = JobStage(stage_name)
            except ValueError:
                return
            self.store.update(
                job_id,
                status=JobStatus.running.value,
                stage=stage.value,
                progress=progress,
            )

        try:
            result = self.runner.run(book_id, report)
        except Exception as exc:
            message = str(exc).strip() or exc.__class__.__name__
            code = error_code_for(stage, exc)
            self.store.update(
                job_id,
                status=JobStatus.failed.value,
                error=message,
                error_code=code,
                retryable=code not in NON_RETRYABLE_ERROR_CODES,
            )
            return
        manifest_path = getattr(result, "manifest_path", None)
        degraded = getattr(result, "status", "") == "degraded"
        self.store.update(
            job_id,
            status=JobStatus.degraded.value if degraded else JobStatus.completed.value,
            stage=JobStage.index.value,
            progress=1.0,
            degraded=degraded,
            manifest_path=manifest_path,
            clear_error=True,
        )

    @staticmethod
    def _new_job_id(book_id: str) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        safe_book_id = "".join(ch for ch in book_id if ch.isalnum()) or "book"
        return f"job-{safe_book_id}-{timestamp}-{uuid.uuid4().hex[:8]}"

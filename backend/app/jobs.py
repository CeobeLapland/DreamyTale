from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Protocol

from backend.app.models import Job


JOB_STATUSES = {"queued", "running", "completed", "failed", "cancelled"}
JOB_STAGES = {
    "ingest",
    "ocr",
    "vlm",
    "story",
    "scene",
    "video",
    "tts",
    "compose",
    "index",
}

ProgressReporter = Callable[[str, float], None]


class JobNotFoundError(LookupError):
    pass


class GenerationRunner(Protocol):
    def run(self, book_id: str, report: ProgressReporter) -> None: ...


class UnavailableGenerationRunner:
    def run(self, book_id: str, report: ProgressReporter) -> None:
        raise RuntimeError("generation pipeline is not configured")


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
            data[job.job_id] = job.to_dict()
            self._write_unlocked(data)
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            data = self._load_unlocked()
        raw = data.get(job_id)
        if raw is None:
            raise JobNotFoundError(job_id)
        return Job(**raw)

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        progress: float | None = None,
        error: str | None = None,
        clear_error: bool = False,
    ) -> Job:
        if status is not None and status not in JOB_STATUSES:
            raise ValueError(f"invalid job status: {status}")
        if stage is not None and stage not in JOB_STAGES:
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
            if clear_error:
                raw["error"] = None
            elif error is not None:
                raw["error"] = error
            raw["updated_at"] = _utc_now()
            self._write_unlocked(data)
        return Job(**raw)


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
            status="queued",
            stage="story",
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
            status="running",
            progress=0.01,
            clear_error=True,
        )

        def report(stage: str, progress: float) -> None:
            self.store.update(
                job_id,
                status="running",
                stage=stage,
                progress=progress,
            )

        try:
            self.runner.run(book_id, report)
        except Exception as exc:
            message = str(exc).strip() or exc.__class__.__name__
            self.store.update(
                job_id,
                status="failed",
                error=message,
            )
            return
        self.store.update(
            job_id,
            status="completed",
            stage="index",
            progress=1.0,
            clear_error=True,
        )

    @staticmethod
    def _new_job_id(book_id: str) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        safe_book_id = "".join(ch for ch in book_id if ch.isalnum()) or "book"
        return f"job-{safe_book_id}-{timestamp}-{uuid.uuid4().hex[:8]}"

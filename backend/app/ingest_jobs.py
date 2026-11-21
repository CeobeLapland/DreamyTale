"""上传压缩包 -> 后台 ingest 任务。

任务状态用契约 §10 的 v2 Job，失败时按契约给出可读 error 和阶段错误码。
"""

from __future__ import annotations

import shutil
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Callable

from backend.app.ingest import book_id_from_key, ingest_book
from backend.app.jobs import JobStore, error_code_for
from backend.app.models import Job, JobStage, JobStatus


class IngestionJobManager:
    def __init__(
        self,
        job_store: JobStore,
        output_root: Path,
        upload_root: Path,
        ingest: Callable[..., Path] = ingest_book,
    ) -> None:
        self.job_store = job_store
        self.output_root = output_root.resolve()
        self.upload_root = upload_root.resolve()
        self.upload_root.mkdir(parents=True, exist_ok=True)
        self.ingest = ingest
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def submit_upload(
        self,
        source: BinaryIO,
        filename: str,
        book_key: str,
        *,
        force: bool = False,
        render_scale: float = 2.0,
        background: bool = True,
    ) -> Job:
        if not filename.lower().endswith(".zip"):
            raise ValueError("archive must be a ZIP file")
        if not 0 < render_scale <= 4:
            raise ValueError("render_scale must be greater than 0 and at most 4")

        upload_path = self.upload_root / f"{uuid.uuid4().hex}.zip"
        with upload_path.open("wb") as target:
            shutil.copyfileobj(source, target)

        book_id = book_id_from_key(book_key)
        now = datetime.now(UTC).replace(microsecond=0)
        job = Job(
            job_id=f"job-{book_id}-{datetime.now(UTC):%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8]}",
            book_id=book_id,
            status=JobStatus.queued,
            stage=JobStage.ingest,
            progress=0.0,
            created_at=now,
            updated_at=now,
        )

        try:
            self.job_store.create(job)
        except Exception:
            upload_path.unlink(missing_ok=True)
            raise

        if background:
            threading.Thread(
                target=self._execute,
                args=(job.job_id, upload_path, book_key, force, render_scale),
                name=f"ingest-{job.job_id}",
                daemon=True,
            ).start()
        else:
            self._execute(job.job_id, upload_path, book_key, force, render_scale)

        return self.job_store.get(job.job_id)

    def _execute(
        self,
        job_id: str,
        upload_path: Path,
        book_key: str,
        force: bool,
        render_scale: float,
    ) -> None:
        self.job_store.update(
            job_id,
            status=JobStatus.running.value,
            stage=JobStage.ingest.value,
            progress=0.05,
            clear_error=True,
        )

        lock = self._book_lock(book_key)
        try:
            with lock:
                self.ingest(
                    upload_path,
                    book_key,
                    self.output_root,
                    render_scale=render_scale,
                    force=force,
                )
        except Exception as exc:
            message = str(exc).strip() or exc.__class__.__name__
            code = error_code_for(JobStage.ingest, exc)
            self.job_store.update(
                job_id,
                status=JobStatus.failed.value,
                error=message,
                error_code=code,
                retryable=code != "INGEST_SOURCE_MISSING",
            )
        else:
            self.job_store.update(
                job_id,
                status=JobStatus.completed.value,
                stage=JobStage.index.value,
                progress=1.0,
                clear_error=True,
            )
        finally:
            try:
                upload_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _book_lock(self, book_key: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(book_key, threading.Lock())

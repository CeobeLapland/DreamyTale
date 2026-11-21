import io
import tempfile
import unittest
from pathlib import Path

from backend.app.ingest_jobs import IngestionJobManager
from backend.app.jobs import JobStore
from backend.app.models import JobStatus


class IngestionJobManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.output_root = self.root / "books"
        self.upload_root = self.root / "uploads"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_runs_ingestion_and_removes_upload(self) -> None:
        def fake_ingest(
            archive_path: Path,
            book_key: str,
            output: Path,
            *,
            render_scale: float,
            force: bool,
        ) -> Path:
            package = output / "zh-01"
            package.mkdir(parents=True, exist_ok=True)
            return package

        jobs = IngestionJobManager(
            JobStore(self.root / "jobs.json"),
            self.output_root,
            self.upload_root,
            fake_ingest,
        )
        job = jobs.submit_upload(
            io.BytesIO(b"zip-content"),
            "sample.zip",
            "中文绘本01",
            background=False,
        )

        self.assertEqual("zh-01", job.book_id)
        self.assertEqual(JobStatus.completed, job.status)
        self.assertEqual(1.0, job.progress)
        self.assertEqual([], list(self.upload_root.iterdir()))

    def test_failure_records_error_code(self) -> None:
        def failing_ingest(
            archive_path: Path,
            book_key: str,
            output: Path,
            *,
            render_scale: float,
            force: bool,
        ) -> Path:
            raise FileNotFoundError("source pdf missing")

        jobs = IngestionJobManager(
            JobStore(self.root / "jobs.json"),
            self.output_root,
            self.upload_root,
            failing_ingest,
        )
        job = jobs.submit_upload(
            io.BytesIO(b"zip-content"),
            "sample.zip",
            "中文绘本01",
            background=False,
        )

        self.assertEqual(JobStatus.failed, job.status)
        self.assertEqual("INGEST_SOURCE_MISSING", job.error_code)
        self.assertFalse(job.retryable)
        self.assertIn("source pdf missing", job.error)


if __name__ == "__main__":
    unittest.main()

import io
import tempfile
import unittest
from pathlib import Path

from backend.app.ingest_jobs import IngestionJobManager
from backend.app.jobs import JobStore


class IngestionJobManagerTests(unittest.TestCase):
    def test_runs_ingestion_and_removes_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_root = root / "books"
            upload_root = root / "uploads"

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
                JobStore(root / "jobs.json"),
                output_root,
                upload_root,
                fake_ingest,
            )
            job = jobs.submit_upload(
                io.BytesIO(b"zip-content"),
                "sample.zip",
                "中文绘本01",
                background=False,
            )

            self.assertEqual("zh-01", job.book_id)
            self.assertEqual("completed", job.status)
            self.assertEqual(1.0, job.progress)
            self.assertEqual([], list(upload_root.iterdir()))


if __name__ == "__main__":
    unittest.main()
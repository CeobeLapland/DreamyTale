import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import api
from backend.app.ingest_jobs import IngestionJobManager
from backend.app.jobs import JobManager, JobStore


class UploadApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.original_jobs = api.jobs
        self.original_ingestions = api.ingestions

        self.job_store = JobStore(self.root / "jobs.json")
        api.jobs = JobManager(self.job_store)

        def fake_ingest(
            archive_path: Path,
            book_key: str,
            output_root: Path,
            *,
            render_scale: float,
            force: bool,
        ) -> Path:
            self.assertTrue(archive_path.is_file())
            package = output_root / "zh-01"
            package.mkdir(parents=True, exist_ok=True)
            return package

        api.ingestions = IngestionJobManager(
            self.job_store,
            self.root / "books",
            self.root / "uploads",
            fake_ingest,
        )
        self.client = TestClient(api.app)

    def tearDown(self) -> None:
        api.jobs = self.original_jobs
        api.ingestions = self.original_ingestions
        self.temporary.cleanup()

    def test_accepts_zip_and_creates_import_job(self) -> None:
        response = self.client.post(
            "/api/books/ingest/upload",
            files={
                "archive": ("sample.zip", b"fake-zip", "application/zip"),
            },
            data={
                "book_key": "中文绘本01",
                "force": "false",
                "render_scale": "2.0",
            },
        )

        self.assertEqual(202, response.status_code)
        job_id = response.json()["job_id"]

        deadline = time.monotonic() + 2
        job = response.json()
        while time.monotonic() < deadline:
            job = self.client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)

        self.assertEqual("zh-01", job["book_id"])
        self.assertEqual("completed", job["status"])
        self.assertEqual(1.0, job["progress"])


if __name__ == "__main__":
    unittest.main()
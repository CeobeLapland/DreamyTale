import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import api
from backend.app.jobs import JobManager, JobStore
from backend.app.store import BookStore


def _write_package(root: Path) -> None:
    package_root = root / "zh-99"
    (package_root / "pages").mkdir(parents=True)
    (package_root / "audio").mkdir()
    (package_root / "source").mkdir()
    (package_root / "pages" / "001.png").write_bytes(b"not inspected by validation")
    (package_root / "audio" / "001.wav").write_bytes(b"not inspected by validation")
    (package_root / "source" / "book.pdf").write_bytes(b"pdf")
    (package_root / "source" / "script.txt").write_text("01. 播放", encoding="utf-8")
    package = {
        "schema_version": "1.0.0",
        "book_id": "zh-99",
        "source_name": "中文绘本99",
        "title": "测试绘本",
        "language": "zh-CN",
        "pdf_path": "source/book.pdf",
        "script_path": "source/script.txt",
        "page_count": 1,
        "pages": [
            {
                "index": 1,
                "image_path": "pages/001.png",
                "text": "",
                "text_source": "embedded_pdf",
                "width_pt": 100.0,
                "height_pt": 100.0,
                "width_px": 200,
                "height_px": 200,
                "text_spans": [],
                "hotspots": [],
            }
        ],
        "steps": [
            {
                "number": 1,
                "instruction": "播放",
                "mandatory": True,
                "audio_path": "audio/001.wav",
                "actions": [
                    {
                        "action_id": "step-001-a01",
                        "type": "control",
                        "text": "播放",
                        "mandatory": True,
                        "target": None,
                    }
                ],
            }
        ],
        "click_targets": [],
    }
    (package_root / "book.json").write_text(
        json.dumps(package, ensure_ascii=False),
        encoding="utf-8",
    )


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        _write_package(root / "books")
        self.original_books = api.books
        self.original_jobs = api.jobs
        api.books = BookStore(root / "books")
        api.jobs = JobManager(JobStore(root / "jobs.json"))
        self.client = TestClient(api.app)

    def tearDown(self) -> None:
        api.books = self.original_books
        api.jobs = self.original_jobs
        self.temporary.cleanup()

    def test_health_and_book_listing(self) -> None:
        self.assertEqual({"status": "ok"}, self.client.get("/health").json())
        response = self.client.get("/api/books")
        self.assertEqual(200, response.status_code)
        self.assertEqual("zh-99", response.json()[0]["book_id"])

    def test_returns_typed_book_package(self) -> None:
        response = self.client.get("/api/books/zh-99")
        self.assertEqual(200, response.status_code)
        self.assertEqual("1.0.0", response.json()["schema_version"])
        self.assertEqual("step-001-a01", response.json()["steps"][0]["actions"][0]["action_id"])

    def test_serves_package_assets(self) -> None:
        response = self.client.get("/api/books/zh-99/assets/pages/001.png")
        self.assertEqual(200, response.status_code)
        self.assertEqual(b"not inspected by validation", response.content)

    def test_generate_endpoint_creates_job(self) -> None:
        response = self.client.post("/api/books/zh-99/generate")
        self.assertEqual(202, response.status_code)
        job_id = response.json()["job_id"]
        job_response = self.client.get(f"/api/jobs/{job_id}")
        self.assertEqual(200, job_response.status_code)
        self.assertIn(job_response.json()["status"], {"queued", "running", "failed"})

    def test_missing_book_uses_structured_error(self) -> None:
        response = self.client.get("/api/books/missing")
        self.assertEqual(404, response.status_code)
        self.assertEqual("book_not_found", response.json()["error"]["code"])

    def test_missing_archive_uses_structured_error(self) -> None:
        response = self.client.post(
            "/api/books/ingest",
            json={
                "archive_path": str(Path(self.temporary.name) / "missing.zip"),
                "book_key": "中文绘本01",
            },
        )
        self.assertEqual(404, response.status_code)
        self.assertEqual("file_not_found", response.json()["error"]["code"])

    def test_job_storage_failure_uses_structured_error(self) -> None:
        with patch.object(api.jobs, "submit", side_effect=OSError("read only")):
            response = self.client.post("/api/books/zh-99/generate")
        self.assertEqual(503, response.status_code)
        self.assertEqual("storage_unavailable", response.json()["error"]["code"])

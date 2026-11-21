import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import api
from backend.app.jobs import JobManager, JobStore
from backend.app.store import BookStore
from backend.tests.fixtures import write_package


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        write_package(root / "books")
        self.original_books = api.books
        self.original_jobs = api.jobs
        api.books = BookStore(root / "books")
        api.jobs = JobManager(JobStore(root / "jobs.json"))
        self.client = TestClient(api.app)

    def tearDown(self) -> None:
        api.books = self.original_books
        api.jobs = self.original_jobs
        self.temporary.cleanup()

    def test_health_and_service_info(self) -> None:
        self.assertEqual({"status": "ok"}, self.client.get("/health").json())
        info = self.client.get("/").json()
        self.assertEqual("2.0.0", info["schema_version"])

    def test_book_listing_is_v2(self) -> None:
        response = self.client.get("/api/books")
        self.assertEqual(200, response.status_code)
        summary = response.json()[0]
        self.assertEqual("zh-99", summary["book_id"])
        self.assertEqual("2.0.0", self.client.get("/api/books/zh-99").json()["schema_version"])
        self.assertEqual("narrative", summary["content_type"])
        self.assertEqual("pdf", summary["source_type"])
        self.assertEqual("ingested", summary["status"])
        self.assertEqual(["zh-99-script-v1"], summary["query_set_ids"])

    def test_book_detail_is_v2(self) -> None:
        response = self.client.get("/api/books/zh-99")
        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("2.0.0", payload["schema_version"])
        self.assertNotIn("steps", payload)
        self.assertNotIn("script_path", payload)
        self.assertNotIn("click_targets", payload)
        self.assertEqual("source/book.pdf", payload["source_path"])
        page = payload["pages"][0]
        self.assertIn("sha256", page)
        self.assertIn("render", page)
        self.assertEqual("span-zh-99-001-001", page["text_spans"][0]["span_id"])

    def test_query_set_endpoint_returns_v2(self) -> None:
        listing = self.client.get("/api/books/zh-99/query-sets")
        self.assertEqual(200, listing.status_code)
        self.assertEqual(["zh-99-script-v1"], listing.json())

        response = self.client.get("/api/books/zh-99/query-sets/zh-99-script-v1")
        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("2.0.0", payload["schema_version"])
        self.assertEqual("control", payload["items"][0]["actions"][0]["kind"])

    def test_capability_endpoint_returns_report(self) -> None:
        response = self.client.get("/api/books/zh-99/capability")
        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("2.0.0", payload["schema_version"])
        self.assertEqual("zh-99", payload["book_id"])
        self.assertEqual(1, payload["pages_total"])
        self.assertEqual(1, payload["pages_with_text"])
        self.assertEqual(1, payload["hotspots"])
        self.assertIn("coverage", payload)
        self.assertIn("limitations", payload)
        self.assertTrue(
            (Path(self.temporary.name) / "books" / "zh-99" / "derived" / "capability.json").is_file()
        )

    def test_interact_control_returns_action(self) -> None:
        response = self.client.post(
            "/api/interact",
            json={
                "book_id": "zh-99",
                "session_id": "sess-1",
                "kind": "control",
                "input": {"text": "播放"},
            },
        )
        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("ok", payload["status"])
        self.assertEqual("play", payload["action"]["type"])
        self.assertEqual("zh-99", payload["book_id"])
        self.assertEqual("sess-1", payload["session_id"])
        self.assertIn("latency", payload)
        self.assertIn("total", payload["latency"])

    def test_interact_qa_falls_back_without_runtime(self) -> None:
        response = self.client.post(
            "/api/interact",
            json={
                "book_id": "zh-99",
                "session_id": "sess-1",
                "kind": "qa",
                "input": {"text": "他们在搭什么？"},
            },
        )
        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("fallback", payload["status"])
        self.assertEqual("guide", payload["answer"]["tier"])
        self.assertEqual("none", payload["action"]["type"])
        self.assertIsNotNone(payload["error"])
        self.assertFalse(payload["error"]["retryable"])

    def test_qa_alias_forces_qa_kind(self) -> None:
        response = self.client.post(
            "/api/qa",
            json={
                "book_id": "zh-99",
                "session_id": "sess-1",
                "kind": "control",
                "input": {"text": "播放"},
            },
        )
        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("qa", payload["kind"])
        self.assertEqual("fallback", payload["status"])

    def test_interact_rejects_invalid_body(self) -> None:
        response = self.client.post(
            "/api/interact",
            json={
                "book_id": "zh-99",
                "session_id": "sess-1",
                "kind": "qa",
            },
        )
        self.assertEqual(422, response.status_code)
        self.assertEqual("invalid_request", response.json()["error"]["code"])

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

    def test_serves_package_assets(self) -> None:
        response = self.client.get("/api/books/zh-99/assets/pages/001.png")
        self.assertEqual(200, response.status_code)
        self.assertEqual(b"not inspected by validation", response.content)

    def test_generate_endpoint_creates_v2_job(self) -> None:
        response = self.client.post("/api/books/zh-99/generate")
        self.assertEqual(202, response.status_code)
        job = response.json()
        self.assertEqual("zh-99", job["book_id"])
        self.assertIn("error_code", job)
        self.assertIn("degraded", job)
        self.assertIn("retryable", job)
        self.assertIn("manifest_path", job)

        job_response = self.client.get(f"/api/jobs/{job['job_id']}")
        self.assertEqual(200, job_response.status_code)
        self.assertIn(job_response.json()["status"], {"queued", "running", "failed"})

    def test_job_storage_failure_uses_structured_error(self) -> None:
        with patch.object(api.jobs, "submit", side_effect=OSError("read only")):
            response = self.client.post("/api/books/zh-99/generate")
        self.assertEqual(503, response.status_code)
        self.assertEqual("storage_unavailable", response.json()["error"]["code"])

    def test_book_json_is_rewritten_with_capabilities_path(self) -> None:
        self.client.get("/api/books/zh-99/capability")
        manifest = Path(self.temporary.name) / "books" / "zh-99" / "book.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual("derived/capability.json", payload["capabilities_path"])


if __name__ == "__main__":
    unittest.main()

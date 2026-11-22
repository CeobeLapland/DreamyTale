import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import api
from backend.app.models import BookGenerationResult
from backend.app.store import BookStore
from backend.tests.fixtures import BOOK_ID, write_package


class GenerationArtifactApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.books_root = Path(self.temporary.name) / "books"
        self.package_root = write_package(self.books_root)
        (self.package_root / "derived" / "scene").mkdir(parents=True)

        result = BookGenerationResult(
            book_id=BOOK_ID,
            generation_version=1,
            status="completed",
            full_video_path="derived/video/book.mp4",
            timeline_path="derived/scene/timeline.json",
            manifest_path="derived/manifest.json",
            created_at=datetime(2026, 11, 22, tzinfo=UTC),
        )
        (self.package_root / "derived" / "generation_result.json").write_text(
            result.model_dump_json(indent=2),
            encoding="utf-8",
        )
        (self.package_root / "derived" / "scene" / "timeline.json").write_text(
            json.dumps(
                {
                    "schema_version": "2.0.0",
                    "book_id": BOOK_ID,
                    "pages": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        self.original_books = api.books
        api.books = BookStore(self.books_root)
        self.client = TestClient(api.app)

    def tearDown(self) -> None:
        api.books = self.original_books
        self.temporary.cleanup()

    def test_returns_generation_result(self) -> None:
        response = self.client.get(
            f"/api/books/{BOOK_ID}/generation-result"
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual("completed", response.json()["status"])
        self.assertEqual(
            "derived/video/book.mp4",
            response.json()["full_video_path"],
        )

    def test_returns_timeline(self) -> None:
        response = self.client.get(f"/api/books/{BOOK_ID}/timeline")
        self.assertEqual(200, response.status_code)
        self.assertEqual("2.0.0", response.json()["schema_version"])
        self.assertEqual(BOOK_ID, response.json()["book_id"])


if __name__ == "__main__":
    unittest.main()
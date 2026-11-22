import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import api
from backend.app.models import (
    Beat,
    FactSource,
    GenerationStatus,
    PageMap,
    PageStory,
    Scene,
    ScenePlan,
    StoryPlan,
)
from backend.app.store import BookStore
from backend.tests.fixtures import BOOK_ID, write_package


class GenerationPlanApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.books_root = Path(self.temporary.name) / "books"
        self.package_root = write_package(self.books_root)
        (self.package_root / "derived" / "story").mkdir(parents=True)
        (self.package_root / "derived" / "scene").mkdir(parents=True)

        now = datetime(2026, 11, 21, tzinfo=UTC)
        story = StoryPlan(
            book_id=BOOK_ID,
            language="zh-CN",
            title="测试绘本",
            logline="两个孩子一起搭积木",
            pages=[
                PageStory(
                    page_index=1,
                    beats=[
                        Beat(
                            beat_id="beat-zh-99-001-001",
                            description="两人一起搭积木",
                            narration="小满和花花一起搭积木。",
                            entities=["小满", "花花", "积木"],
                            duration_ms=3000,
                        )
                    ],
                )
            ],
            model="mock",
            prompt_version="v1",
            source_hash="0" * 64,
            created_at=now,
        )
        scene_plan = ScenePlan(
            book_id=BOOK_ID,
            plan_version=1,
            page_map=[
                PageMap(
                    page_index=1,
                    scene_ids=["scene-zh-99-001-001"],
                    start_ms=0,
                    end_ms=3000,
                )
            ],
            scenes=[
                Scene(
                    scene_id="scene-zh-99-001-001",
                    page_index=1,
                    beat_id="beat-zh-99-001-001",
                    start_ms=0,
                    end_ms=3000,
                    caption="两人一起搭积木",
                    aliases=["搭积木", "积木城堡"],
                    entities=["小满", "花花"],
                    action="搭建",
                    prompt="儿童绘本风格，两个孩子在室内搭积木",
                    seed=1,
                    source=FactSource.human,
                    status=GenerationStatus.ok,
                )
            ],
            model="mock",
            prompt_version="v1",
            source_hash="0" * 64,
            created_at=now,
        )

        (self.package_root / "derived" / "story" / "story_plan.json").write_text(
            story.model_dump_json(indent=2),
            encoding="utf-8",
        )
        (self.package_root / "derived" / "scene" / "scene_plan.json").write_text(
            scene_plan.model_dump_json(indent=2),
            encoding="utf-8",
        )

        self.original_books = api.books
        api.books = BookStore(self.books_root)
        self.client = TestClient(api.app)

    def tearDown(self) -> None:
        api.books = self.original_books
        self.temporary.cleanup()

    def test_returns_story_plan(self) -> None:
        response = self.client.get(f"/api/books/{BOOK_ID}/story-plan")
        self.assertEqual(200, response.status_code)
        self.assertEqual("2.0.0", response.json()["schema_version"])
        self.assertEqual(1, len(response.json()["pages"]))

    def test_returns_scene_plan(self) -> None:
        response = self.client.get(f"/api/books/{BOOK_ID}/scene-plan")
        self.assertEqual(200, response.status_code)
        self.assertEqual(1, len(response.json()["scenes"]))
        self.assertEqual("scene-zh-99-001-001", response.json()["scenes"][0]["scene_id"])

    def test_missing_plan_returns_404(self) -> None:
        (self.package_root/ "derived"/ "scene"/ "scene_plan.json").unlink()
        response = self.client.get(f"/api/books/{BOOK_ID}/scene-plan")
        self.assertEqual(404, response.status_code)
        self.assertEqual("file_not_found", response.json()["error"]["code"])

    def test_invalid_plan_returns_422(self) -> None:
        path = (self.package_root / "derived"/ "story"/ "story_plan.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["schema_version"] = "1.0.0"
        path.write_text(json.dumps(data), encoding="utf-8")

        response = self.client.get(f"/api/books/{BOOK_ID}/story-plan")
        self.assertEqual(422, response.status_code)
        self.assertEqual("invalid_request", response.json()["error"]["code"])


if __name__ == "__main__":
    unittest.main()
"""Annotation API + runtime overlay tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import api
from backend.app.store import BookStore
from backend.tests.fixtures import write_package
from contracts.models import content_hash


def _write_card(root: Path) -> None:
    card = {
        "card_id": "card-zh-99-001",
        "book_id": "zh-99",
        "kind": "qa",
        "intent": "identify",
        "scope": "page",
        "langs": ["zh"],
        "question_canonical": "测试问题？",
        "variants": ["测试问题？", "测试问题", "这是什么？", "这是什么", "测试"],
        "entities": ["测试"],
        "answers": {
            "zh": {"strong": "旧答案", "weak": "旧弱答案", "guide": "旧引导"}
        },
        "evidence": [{"page_index": 1, "bbox_px": [10, 10, 50, 30], "quote": "测试"}],
        "video_anchor": None,
        "priority": 1,
        "source": "auto",
        "version": 1,
        "status": "active",
        "hash": "",
        "created_at": "2026-11-24T00:00:00Z",
    }
    card["hash"] = content_hash(card)
    path = root / "zh-99" / "derived" / "knowledge" / "cards.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(card, ensure_ascii=False) + "\n", encoding="utf-8")


class AnnotationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        write_package(root / "books")
        _write_card(root / "books")
        self.original_books = api.books
        api.books = BookStore(root / "books")
        self.client = TestClient(api.app)

    def tearDown(self) -> None:
        api.books = self.original_books
        self.temporary.cleanup()

    def _annotate(self, **payload):
        body = {"reviewer": "B", **payload}
        return self.client.post("/api/books/zh-99/annotations", json=body)

    def test_hotspot_bbox_override_changes_a_click(self) -> None:
        response = self._annotate(
            target_type="hotspot",
            target_id="hotspot-zh-99-001-001",
            field="bbox_px",
            value=[1, 2, 3, 4],
            reason="tighten",
        )
        self.assertEqual(201, response.status_code)
        self.assertFalse(response.json()["conflict"])

        clicked = self.client.post(
            "/api/interact",
            json={
                "book_id": "zh-99",
                "session_id": "s",
                "kind": "click",
                "input": {
                    "text": "识别点击对象",
                    "page_index": 1,
                    "click": {"x_px": 2, "y_px": 3},
                },
            },
        )
        self.assertEqual(200, clicked.status_code)
        body = clicked.json()
        self.assertEqual("ok", body["status"])
        self.assertEqual("hotspot-zh-99-001-001", body["action"]["hotspot_id"])

        listed = self.client.get("/api/books/zh-99/annotations").json()
        self.assertEqual(1, len(listed))
        self.assertEqual("bbox_px", listed[0]["field"])

    def test_conflict_is_queued(self) -> None:
        response = self._annotate(
            target_type="hotspot",
            target_id="hotspot-zh-99-001-001",
            field="label",
            value="新标签",
            old_value="错误的旧值",
        )
        self.assertEqual(201, response.status_code)
        self.assertTrue(response.json()["conflict"])

        review = self.client.get("/api/books/zh-99/review-items").json()
        self.assertEqual(1, len(review))
        self.assertEqual("conflict", review[0]["reason"])

    def test_qa_card_answer_override_wins_at_runtime(self) -> None:
        response = self._annotate(
            target_type="qa_card",
            target_id="card-zh-99-001",
            field="answers.zh.strong",
            value="人工答案",
        )
        self.assertEqual(201, response.status_code)

        answer = self.client.post(
            "/api/interact",
            json={
                "book_id": "zh-99",
                "session_id": "s",
                "kind": "qa",
                "input": {"text": "测试问题？", "language": "zh-CN"},
            },
        )
        self.assertEqual(200, answer.status_code)
        body = answer.json()
        self.assertEqual("ok", body["status"])
        self.assertEqual("人工答案", body["answer"]["text"])
        self.assertEqual("strong", body["answer"]["tier"])

    def test_unknown_target_is_rejected(self) -> None:
        response = self._annotate(
            target_type="hotspot",
            target_id="hotspot-does-not-exist",
            field="label",
            value="x",
        )
        self.assertEqual(422, response.status_code)


if __name__ == "__main__":
    unittest.main()

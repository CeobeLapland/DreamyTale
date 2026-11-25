import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from backend.app.interaction import handle_interaction
from backend.app.knowledge import find_qa_card, load_qa_cards
from backend.app.models import (
    AnswerTier,
    Evidence,
    FactSource,
    InteractionRequest,
    QaAnswers,
    QaCard,
    QaIntent,
    QaScope,
    Status,
    VideoAnchor,
)


class KnowledgeCardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.package_root = Path(self.temporary.name)
        (self.package_root / "derived" / "knowledge").mkdir(parents=True)

        self.card = QaCard(
            card_id="card-zh-01-001",
            book_id="zh-01",
            intent=QaIntent.plot,
            scope=QaScope.page,
            langs=["zh", "en"],
            question_canonical="他们在搭什么？",
            variants=[
                "他们在搭什么",
                "他们在搭什么东西？",
                "小满和花花在搭什么？",
                "孩子们在搭什么？",
                "他们正在搭什么？",
            ],
            entities=["小满", "花花", "积木城堡"],
            answers={
                "zh": QaAnswers(
                    strong="他们在搭积木城堡。",
                    weak="他们在搭积木。",
                    guide="请看画面中间的积木。",
                ),
                "en": QaAnswers(
                    strong="They are building a block castle.",
                    weak="They are playing with blocks.",
                    guide="Look at the blocks in the middle.",
                ),
            },
            evidence=[
                Evidence(page_index=2, quote="我们一起搭城堡"),
                Evidence(
                    page_index=2,
                    bbox_px=(30, 30, 160, 70),
                    span_id="span-zh-01-002-001",
                    quote="我们一起搭城堡",
                ),
            ],
            video_anchor=VideoAnchor(
                scene_id="scene-zh-01-002",
                start_ms=1000,
                end_ms=4000,
            ),
            priority=1,
            source=FactSource.human,
            version=1,
            status=Status.active,
            hash="a" * 16,
            created_at=datetime(2026, 11, 22, tzinfo=UTC),
        )

        path = self.package_root / "derived" / "knowledge" / "cards.jsonl"
        path.write_text(
            json.dumps(
                self.card.model_dump(mode="json"),
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_loads_and_matches_qa_card(self) -> None:
        cards = load_qa_cards(self.package_root)
        match = find_qa_card(cards, "小满和花花在搭什么？", "zh-CN")

        self.assertIsNotNone(match)
        self.assertEqual("他们在搭积木城堡。", match.answer)
        self.assertEqual(AnswerTier.strong, match.tier)

    def test_interaction_returns_card_answer(self) -> None:
        request = InteractionRequest.model_validate(
            {
                "book_id": "zh-01",
                "session_id": "session-1",
                "kind": "qa",
                "input": {
                    "text": "他们在搭什么？",
                    "language": "zh-CN",
                },
            }
        )

        response = handle_interaction(
            request,
            package=None,
            package_root=self.package_root,
        )

        self.assertEqual("ok", response.status)
        self.assertEqual("show_card", response.action.type.value)
        self.assertEqual("他们在搭积木城堡。", response.answer.text)
        self.assertEqual("scene-zh-01-002", response.answer.scene_id)
        self.assertEqual(1000, response.answer.time_ms)
        self.assertEqual((30, 30, 160, 70), response.answer.evidence[0].bbox_px)

    def test_missing_card_keeps_fallback(self) -> None:
        (self.package_root / "derived" / "knowledge" / "cards.jsonl").unlink()
        request = InteractionRequest.model_validate(
            {
                "book_id": "zh-01",
                "session_id": "session-1",
                "kind": "qa",
                "input": {"text": "这本书讲什么？"},
            }
        )

        response = handle_interaction(
            request,
            package=None,
            package_root=self.package_root,
        )

        self.assertEqual("fallback", response.status)
        self.assertEqual("qa_runtime_not_configured", response.error.code)


if __name__ == "__main__":
    unittest.main()
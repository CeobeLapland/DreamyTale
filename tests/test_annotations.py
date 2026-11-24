"""Human annotation overlay tests (no API, no models)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.app.validation import book_package_from_dict
from backend.tests.fixtures import valid_package
from contracts.models import AnnotationTargetType, QaCard, content_hash
from pipeline import annotations as module


def _card() -> QaCard:
    raw = {
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
    raw["hash"] = content_hash(raw)
    return QaCard.model_validate(raw)


class AnnotationOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        (root / "zh-99").mkdir(parents=True)
        self.patcher = mock.patch.object(module, "DATA", root)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(self.temporary.cleanup)
        self.package = book_package_from_dict(valid_package())

    def test_hotspot_bbox_override_is_applied_to_a_copy(self) -> None:
        annotation, review = module.create_annotation(
            "zh-99",
            AnnotationTargetType.hotspot,
            "hotspot-zh-99-001-001",
            "bbox_px",
            [1, 2, 3, 4],
            "B",
            reason="tighten",
            package=self.package,
        )

        self.assertIsNone(review)
        self.assertEqual([1, 2, 3, 4], annotation.value)
        effective = module.apply_annotations_to_package(self.package)
        hotspot = effective.pages[0].hotspots[0]
        self.assertEqual([1, 2, 3, 4], list(hotspot.bbox_px))
        # The auto package is untouched.
        self.assertEqual([20, 20, 100, 100], list(self.package.pages[0].hotspots[0].bbox_px))
        self.assertEqual(1, len(module.load_annotations("zh-99")))

    def test_conflict_goes_to_the_review_queue(self) -> None:
        _, review = module.create_annotation(
            "zh-99",
            AnnotationTargetType.hotspot,
            "hotspot-zh-99-001-001",
            "label",
            "新标签",
            "B",
            old_value="错误的旧值",
            package=self.package,
        )

        self.assertIsNotNone(review)
        queue = module.load_review_items("zh-99")
        self.assertEqual(1, len(queue))
        self.assertEqual("conflict", queue[0].reason.value)
        self.assertIn("错误的旧值", queue[0].notes or "")

    def test_qa_card_answer_override_wins(self) -> None:
        card = _card()
        annotation, _ = module.create_annotation(
            "zh-99",
            AnnotationTargetType.qa_card,
            card.card_id,
            "answers.zh.strong",
            "人工答案",
            "B",
            package=self.package,
            cards=[card],
        )

        self.assertEqual("人工答案", annotation.value)
        effective = module.apply_annotations_to_cards([card], book_id="zh-99")
        self.assertEqual("人工答案", effective[0].answers["zh"].strong)
        self.assertEqual("旧答案", card.answers["zh"].strong)

    def test_annotations_are_append_only(self) -> None:
        for value in ([1, 2, 3, 4], [2, 3, 4, 5]):
            module.create_annotation(
                "zh-99",
                AnnotationTargetType.hotspot,
                "hotspot-zh-99-001-001",
                "bbox_px",
                value,
                "B",
                package=self.package,
            )

        records = module.load_annotations("zh-99")
        self.assertEqual(2, len(records))
        active = module.active_annotations("zh-99")
        self.assertEqual(
            [2, 3, 4, 5],
            active[("hotspot", "hotspot-zh-99-001-001", "bbox_px")].value,
        )


if __name__ == "__main__":
    unittest.main()

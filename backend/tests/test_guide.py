"""引导式回答的测试。

契约 §6.2：`guide` 这一档必须三件事缺一不可——承认 + 翻页 + 反问，
并且禁止"抱歉，我无法回答"。`docs/ARCHITECTURE.md` §4.5：
qa 无命中 → 引用原句 → 引导。

分工：翻到哪一页是 pipeline 烘焙在卡里的事，运行时不做检索。
引导停在孩子正在看的那一页，引这一页的原句。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.app.guide import build_guide_answer, page_start_times
from backend.app.interaction import handle_interaction
from backend.app.models import AnswerTier, InteractionKind, InteractionRequest
from backend.app.validation import book_package_from_dict
from backend.tests.fixtures import valid_package


def _package_with_text(text: str = "小满在搭积木城堡，积木越搭越高。") -> dict:
    payload = valid_package()
    payload["pages"][0]["text"] = text
    payload["pages"][0]["text_spans"][0]["text"] = "小满在搭积木城堡"
    return payload


def _request(**overrides) -> InteractionRequest:
    payload = {
        "book_id": "zh-99",
        "session_id": "sess-1",
        "kind": "qa",
        "input": {"text": "积木是谁搭的？"},
    }
    payload.update(overrides)
    return InteractionRequest.model_validate(payload)


class GuideTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_timeline(self, package_root: Path) -> None:
        scene_dir = package_root / "derived" / "scene"
        scene_dir.mkdir(parents=True, exist_ok=True)
        (scene_dir / "timeline.json").write_text(
            json.dumps(
                {
                    "book_id": "zh-99",
                    "total_ms": 12000,
                    "pages": [
                        {"page_index": 1, "start_ms": 0, "end_ms": 6000},
                        {"page_index": 2, "start_ms": 6000, "end_ms": 12000},
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_guide_has_all_three_parts_and_no_apology(self) -> None:
        package = book_package_from_dict(_package_with_text())
        package_root = self.root / "zh-99"
        package_root.mkdir(parents=True)
        self._write_timeline(package_root)

        guide = build_guide_answer(
            package, package_root, "积木是谁搭的？", "zh-CN", current_page=1
        )

        self.assertIsNotNone(guide)
        # 承认：说清楚了没有直接答案
        self.assertIn("没有找到", guide.text)
        # 翻页：给出页码
        self.assertIn("第 1 页", guide.text)
        # 反问：把问题还给孩子
        self.assertIn("？", guide.text)
        # 禁止"抱歉，我无法回答"
        self.assertNotIn("抱歉", guide.text)
        self.assertNotIn("无法回答", guide.text)

    def test_guide_stays_on_the_page_the_child_is_looking_at(self) -> None:
        """运行时不做检索：停在孩子眼前这页，不自己猜。"""
        package = book_package_from_dict(_package_with_text())
        package_root = self.root / "zh-99"
        package_root.mkdir(parents=True)
        self._write_timeline(package_root)

        guide = build_guide_answer(
            package, package_root, "积木是谁搭的？", "zh-CN", current_page=1
        )

        self.assertIsNotNone(guide)
        self.assertEqual(1, guide.page_index)
        self.assertIn("第 1 页", guide.text)

    def test_guide_quotes_the_book_and_carries_evidence(self) -> None:
        package = book_package_from_dict(_package_with_text())
        package_root = self.root / "zh-99"
        package_root.mkdir(parents=True)
        self._write_timeline(package_root)

        guide = build_guide_answer(
            package, package_root, "积木是谁搭的？", "zh-CN", current_page=1
        )

        self.assertIsNotNone(guide)
        self.assertIn("小满", guide.text)
        self.assertEqual(1, guide.evidence[0].page_index)
        self.assertTrue(guide.evidence[0].quote)

    def test_guide_uses_book_absolute_time(self) -> None:
        package = book_package_from_dict(_package_with_text())
        package_root = self.root / "zh-99"
        package_root.mkdir(parents=True)
        self._write_timeline(package_root)

        guide = build_guide_answer(
            package, package_root, "积木是谁搭的？", "zh-CN", current_page=1
        )

        self.assertIsNotNone(guide)
        # 第一页从 0 开始，所以翻页时间就是 0；
        # 关键是这个时间来自 timeline 的页偏移，而不是场景内的相对时间。
        self.assertEqual(0, guide.time_ms)
        self.assertEqual({1: 0, 2: 6000}, page_start_times(package_root))

    def test_english_guide_is_in_english(self) -> None:
        package = book_package_from_dict(
            _package_with_text("Kuan builds a castle out of colorful blocks.")
        )
        package_root = self.root / "zh-99"
        package_root.mkdir(parents=True)
        self._write_timeline(package_root)

        guide = build_guide_answer(
            package, package_root, "Who built the castle?", "en", current_page=1
        )

        self.assertIsNotNone(guide)
        self.assertIn("could not find", guide.text)
        self.assertIn("page 1", guide.text)
        self.assertNotIn("抱歉", guide.text)

    def test_qa_without_card_returns_a_guide_not_a_dead_end(self) -> None:
        package = book_package_from_dict(_package_with_text())
        package_root = self.root / "zh-99"
        package_root.mkdir(parents=True)
        self._write_timeline(package_root)

        response = handle_interaction(_request(), package, package_root)

        # 有回答、有翻页动作、证据在页上——不是一句"没找到"。
        self.assertEqual("ok", response.status)
        self.assertEqual(AnswerTier.guide, response.answer.tier)
        self.assertEqual("seek", response.action.type.value)
        self.assertTrue(response.answer.evidence)
        self.assertIn("积木", response.answer.text)

    def test_guide_never_says_it_cannot_answer(self) -> None:
        package = book_package_from_dict(_package_with_text())
        package_root = self.root / "zh-99"
        package_root.mkdir(parents=True)
        self._write_timeline(package_root)

        response = handle_interaction(
            _request(kind=InteractionKind.qa), package, package_root
        )

        self.assertNotIn("抱歉", response.answer.text)
        self.assertNotIn("无法回答", response.answer.text)


if __name__ == "__main__":
    unittest.main()

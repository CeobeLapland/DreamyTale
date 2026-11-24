"""Runtime LLM answer grounding tests (fake model, no LM Studio)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline.models import VLMResult

from backend.app import llm_answer as module
from backend.app.llm_answer import build_llm_answer
from tests.test_core import make_book, make_page


class FakeProvider:
    name = "fake"
    model = "fake"

    def __init__(self, text: str) -> None:
        self.text = text

    def available(self) -> bool:
        return True

    def chat(self, prompt: str, system: str | None = None) -> VLMResult:
        return VLMResult(text=self.text)


class LLMAnswerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        (self.root / "derived" / "story").mkdir(parents=True)
        (self.root / "derived" / "story" / "story_plan.json").write_text(
            json.dumps(
                {"characters": [{"name": "小满"}, {"name": "花花"}]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.package = make_book(
            [
                make_page(1, "学而思阅读树儿童中文分级读物出版社"),
                make_page(2, "高高积木倒一地，花花很生气。"),
                make_page(3, "六块、七块、八块、九块，积木城堡没有倒。"),
            ]
        )

    def test_number_answer_must_be_supported_by_the_cited_sentence(self) -> None:
        grounded = module._ground(
            "她们搭了九块积木。", "她们搭了几块积木？", self.package, self.root
        )
        self.assertIsNotNone(grounded)
        self.assertEqual(3, grounded[0])

    def test_causal_answer_is_grounded_in_the_same_page(self) -> None:
        grounded = module._ground(
            "因为积木倒了，所以花花很生气。",
            "花花为什么生气？",
            self.package,
            self.root,
        )
        self.assertIsNotNone(grounded)
        self.assertEqual(2, grounded[0])

    def test_cause_that_does_not_appear_in_the_sentence_is_rejected(self) -> None:
        grounded = module._ground(
            "因为小满想和她一起过生日，所以花花很生气。",
            "花花为什么生气？",
            self.package,
            self.root,
        )
        self.assertIsNone(grounded)

    def test_title_page_is_not_used_as_evidence(self) -> None:
        grounded = module._ground(
            "学而思阅读树儿童中文分级读物出版社",
            "这本书的作者是谁？",
            self.package,
            self.root,
        )
        self.assertIsNone(grounded)

    def test_fake_model_answer_is_returned_with_evidence(self) -> None:
        with mock.patch.object(module, "_get_provider", return_value=FakeProvider("九块。")):
            answer = build_llm_answer(
                self.package, self.root, "她们搭了几块积木？", "zh-CN"
            )
        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertEqual("九块。", answer.text)
        self.assertEqual(3, answer.page_index)
        self.assertTrue(answer.evidence)

    def test_model_refusal_falls_back_to_guide(self) -> None:
        with mock.patch.object(module, "_get_provider", return_value=FakeProvider("不知道")):
            answer = build_llm_answer(self.package, self.root, "作者是谁？", "zh-CN")
        self.assertIsNone(answer)

    def test_author_is_answered_from_metadata(self) -> None:
        self.package.authors = ["张三"]
        answer = build_llm_answer(self.package, self.root, "这本书的作者是谁？", "zh-CN")
        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertIn("张三", answer.text)


if __name__ == "__main__":
    unittest.main()

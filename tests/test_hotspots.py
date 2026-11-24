"""Cross-lingual page routing for visual click targets."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from pipeline.hotspots import _candidate_page_with_llm


class FakeLLM:
    name = "fake_llm"

    def __init__(self, data: dict | None, available: bool = True) -> None:
        self.data = data
        self._available = available
        self.calls: list[str] = []

    def available(self) -> bool:
        return self._available

    def chat(self, prompt: str, json_schema=None):
        self.calls.append(prompt)
        return SimpleNamespace(text="{}", data=self.data)


PAGES = [
    {"index": 1, "text": "The title page.", "narrative": "A cinema entrance.", "entities": []},
    {"index": 2, "text": "Popcorn on the counter.", "narrative": "A movie poster on the wall.", "entities": []},
]


class PageRoutingTests(unittest.TestCase):
    def test_llm_picks_the_page_for_a_chinese_target(self) -> None:
        llm = FakeLLM({"page_index": 2, "found": True})

        page = _candidate_page_with_llm(llm, "电影海报", PAGES)

        self.assertIsNotNone(page)
        self.assertEqual(2, page["index"])
        self.assertEqual(1, len(llm.calls))
        self.assertIn("电影海报", llm.calls[0])
        self.assertIn("movie poster", llm.calls[0])

    def test_unfound_returns_none(self) -> None:
        llm = FakeLLM({"page_index": 0, "found": False})

        self.assertIsNone(_candidate_page_with_llm(llm, "不存在的东西", PAGES))

    def test_unavailable_llm_is_not_called(self) -> None:
        llm = FakeLLM({"page_index": 2, "found": True}, available=False)

        self.assertIsNone(_candidate_page_with_llm(llm, "电影海报", PAGES))
        self.assertEqual([], llm.calls)


if __name__ == "__main__":
    unittest.main()

"""Runtime cross-lingual page routing for seek."""

from __future__ import annotations

import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace

from backend.app import page_router


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


class PageRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "derived" / "understanding").mkdir(parents=True)
        (self.root / "derived" / "scene").mkdir(parents=True)
        (self.root / "derived" / "understanding" / "narrative.jsonl").write_text(
            json.dumps(
                {"page_index": 2, "status": "active", "text": "A movie poster on the wall."},
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        (self.root / "derived" / "scene" / "scene_plan.json").write_text(
            json.dumps(
                {
                    "scenes": [
                        {"page_index": 2, "scene_id": "scene-2", "caption": "A movie poster."}
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.package = SimpleNamespace(
            pages=[
                SimpleNamespace(index=1, text="Popcorn."),
                SimpleNamespace(index=2, text="A poster."),
            ]
        )
        self.addCleanup(self.temporary.cleanup)

    def _with_provider(self, provider: FakeLLM) -> None:
        patcher = unittest.mock.patch.object(page_router, "_provider", provider)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_routes_a_chinese_target_to_an_english_page(self) -> None:
        provider = FakeLLM({"page_index": 2, "found": True})
        self._with_provider(provider)

        page = page_router.route_page(self.package, self.root, "电影海报")

        self.assertEqual(2, page)
        self.assertEqual(1, len(provider.calls))
        self.assertIn("电影海报", provider.calls[0])
        self.assertIn("movie poster", provider.calls[0])

    def test_unfound_returns_none(self) -> None:
        self._with_provider(FakeLLM({"page_index": 0, "found": False}))

        self.assertIsNone(page_router.route_page(self.package, self.root, "不存在"))

    def test_unavailable_provider_is_not_called(self) -> None:
        provider = FakeLLM({"page_index": 2, "found": True}, available=False)
        self._with_provider(provider)

        self.assertIsNone(page_router.route_page(self.package, self.root, "电影海报"))
        self.assertEqual([], provider.calls)


if __name__ == "__main__":
    unittest.main()

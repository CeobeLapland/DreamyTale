"""Human correction tests. Run: python -m pytest tests/test_manual.py -v"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import manual
from pipeline.models.ollama_provider import OllamaProvider
from pipeline.models.registry import _make_vlm, build_vlm, status
from pipeline.narrative import build_page_records


class ManualNarrativeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        patcher = mock.patch.object(manual, "DATA", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def _seed(self) -> Path:
        return manual.seed_narrative_corrections(
            "zh-01",
            [
                {"page_index": 2, "text": "下雨天搭积木", "entities": ["小满"], "visible_text": []},
                {"page_index": 3, "text": "城堡搭到五块", "entities": [], "visible_text": []},
            ],
        )

    def test_seed_then_load_round_trip(self) -> None:
        path = self._seed()
        self.assertTrue(path.is_file())
        corrections = manual.load_narrative_corrections("zh-01")
        self.assertEqual(sorted(corrections), [2, 3])
        self.assertEqual(corrections[2]["text"], "下雨天搭积木")

    def test_reseed_keeps_human_edits(self) -> None:
        self._seed()
        corrections = manual.load_narrative_corrections("zh-01")
        corrections[2]["text"] = "人工改过的叙述"
        manual.save_narrative_corrections("zh-01", corrections)

        self._seed()
        reloaded = manual.load_narrative_corrections("zh-01")
        self.assertEqual(reloaded[2]["text"], "人工改过的叙述")

    def test_blank_text_is_not_a_correction(self) -> None:
        self._seed()
        path = manual.narrative_path("zh-01")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["pages"]["4"] = {"text": "   "}
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self.assertNotIn(4, manual.load_narrative_corrections("zh-01"))

    def test_missing_file_is_not_an_error(self) -> None:
        self.assertEqual(manual.load_narrative_corrections("no-such-book"), {})
        self.assertEqual(manual.load_annotations("no-such-book"), [])


class PageRecordTests(unittest.TestCase):
    def test_human_correction_wins_and_auto_is_superseded(self) -> None:
        old = {
            "page_index": 2,
            "book_id": "zh-01",
            "text": "VLM 说错了",
            "entities": [],
            "visible_text": [],
            "source": "vlm",
            "confidence": 0.5,
            "version": 1,
            "status": "active",
        }
        records = build_page_records(2, "zh-01", {"text": "人工写的"}, None, old)
        self.assertEqual(records[0]["source"], "human")
        self.assertEqual(records[0]["text"], "人工写的")
        self.assertEqual(records[0]["version"], 2)
        self.assertEqual(records[0]["status"], "active")
        self.assertEqual(records[1]["status"], "superseded")
        self.assertEqual(records[1]["text"], "VLM 说错了")

    def test_auto_record_replaces_previous_one(self) -> None:
        old = {
            "page_index": 2,
            "book_id": "zh-01",
            "text": "旧",
            "source": "vlm",
            "confidence": 0.5,
            "version": 1,
            "status": "active",
        }
        records = build_page_records(2, "zh-01", None, {"text": "新", "entities": [], "visible_text": []}, old)
        self.assertEqual(records[0]["source"], "vlm")
        self.assertEqual(records[0]["text"], "新")
        self.assertEqual(records[0]["version"], 2)
        self.assertEqual(records[1]["status"], "superseded")

    def test_no_new_data_keeps_previous_record(self) -> None:
        old = {
            "page_index": 2,
            "book_id": "zh-01",
            "text": "旧",
            "source": "vlm",
            "confidence": 0.5,
            "version": 1,
            "status": "active",
        }
        records = build_page_records(2, "zh-01", None, None, old)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "active")


class OllamaProviderTests(unittest.TestCase):
    def test_registry_builds_ollama_provider(self) -> None:
        config = {"vlm": {"provider": "ollama", "ollama": {"model": "qwen2.5vl:7b"}}}
        provider = _make_vlm("ollama", config["vlm"])
        self.assertIsInstance(provider, OllamaProvider)
        self.assertEqual(provider.name, "ollama")

    def test_build_vlm_falls_back_when_ollama_is_down(self) -> None:
        config = {
            "vlm": {
                "provider": "ollama",
                "ollama": {"base_url": "http://127.0.0.1:1", "model": "qwen2.5vl:7b"},
                "fallback": ["null"],
            }
        }
        provider = build_vlm(config)
        self.assertEqual(provider.name, "null")

    def test_unreachable_ollama_reports_reason(self) -> None:
        provider = OllamaProvider(base_url="http://127.0.0.1:1", model="qwen2.5vl:7b")
        self.assertFalse(provider.available())
        self.assertIn("ollama unreachable", provider.detail)

    def test_status_reports_configured_provider_not_null_fallback(self) -> None:
        config = {
            "vlm": {
                "provider": "ollama",
                "ollama": {"base_url": "http://127.0.0.1:1", "model": "qwen2.5vl:7b"},
                "fallback": ["null"],
            }
        }
        rows = status(config)
        vlm = next(row for row in rows if row.kind == "vlm")
        self.assertEqual(vlm.provider, "ollama")
        self.assertFalse(vlm.available)
        self.assertIn("ollama unreachable", vlm.detail)


if __name__ == "__main__":
    unittest.main()

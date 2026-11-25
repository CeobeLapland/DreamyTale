"""Answer-audio cache behaviour (no network)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.answer_tts import answer_audio_path, synthesize_answer


class AnswerTtsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def test_cached_file_is_returned_without_calling_tts(self) -> None:
        path = answer_audio_path(self.root, "积木城堡倒了。", "zh-CN")
        path.parent.mkdir(parents=True)
        path.write_bytes(b"mp3")

        with patch(
            "backend.app.answer_tts.edge_tts_available", return_value=False
        ):
            result = synthesize_answer(self.root, "积木城堡倒了。", "zh-CN")

        self.assertEqual(
            "derived/audio/answer/" + path.name,
            result,
        )

    def test_missing_dependency_returns_none(self) -> None:
        with patch(
            "backend.app.answer_tts.edge_tts_available", return_value=False
        ):
            self.assertIsNone(synthesize_answer(self.root, "新的回答", "zh-CN"))

    def test_empty_text_is_not_synthesized(self) -> None:
        self.assertIsNone(synthesize_answer(self.root, "   ", "zh-CN"))


if __name__ == "__main__":
    unittest.main()

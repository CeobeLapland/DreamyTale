"""ASR provider and shared prompt tests.

These do not load the Whisper model: the model is 1.6 GB and belongs to the
demo machine, not to CI. What is tested here is the contract around it:
unavailable states are honest, WAV decoding works, and the prompt contains
book words but never generic command words.
"""

from __future__ import annotations

import json
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from backend.app.validation import book_package_from_dict
from backend.tests.fixtures import valid_package
from pipeline.asr_prompt import answer_language, vocabulary_prompt
from pipeline.models.asr import FasterWhisperASR, NullASR, decode_audio


class ASRProviderTests(unittest.TestCase):
    def test_missing_model_is_unavailable_with_a_reason(self) -> None:
        provider = FasterWhisperASR(model="")
        self.assertFalse(provider.available())
        self.assertIn("not configured", provider.detail)

    def test_path_that_does_not_exist_is_unavailable(self) -> None:
        provider = FasterWhisperASR(model=str(Path(tempfile.gettempdir()) / "no-such-asr-model"))
        self.assertFalse(provider.available())
        self.assertIn("not found", provider.detail)

    def test_null_provider_never_pretends(self) -> None:
        provider = NullASR("no ASR")
        self.assertFalse(provider.available())
        with self.assertRaises(RuntimeError):
            provider.transcribe(Path("x.wav"))

    def test_decode_wav_to_mono_16k(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "silence.wav"
            with wave.open(str(path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(16000)
                handle.writeframes(np.zeros(16000, dtype="<i2").tobytes())

            audio = decode_audio(path)

            self.assertEqual(16000, len(audio))
            self.assertEqual(np.float32, audio.dtype)
            self.assertAlmostEqual(0.0, float(audio.max()))


class ASRPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.package = book_package_from_dict(valid_package())
        story = {
            "characters": [{"name": "小满", "aliases": ["小满满"]}],
            "pages": [
                {
                    "page_index": 1,
                    "beats": [{"entities": ["积木", "积木", "小房子"]}],
                }
            ],
        }
        scene = {"scenes": [{"aliases": ["积木城堡"]}]}
        (self.root / "derived" / "story").mkdir(parents=True)
        (self.root / "derived" / "scene").mkdir(parents=True)
        (self.root / "derived" / "story" / "story_plan.json").write_text(
            json.dumps(story, ensure_ascii=False), encoding="utf-8"
        )
        (self.root / "derived" / "scene" / "scene_plan.json").write_text(
            json.dumps(scene, ensure_ascii=False), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_prompt_has_book_words(self) -> None:
        prompt = vocabulary_prompt(self.package, self.root)
        self.assertIn("小满", prompt)
        self.assertIn("积木城堡", prompt)
        self.assertIn("城堡", prompt)  # hotspot label from the fixture

    def test_prompt_has_no_generic_command_words(self) -> None:
        """中文指令词会把英文 "Play" 带偏成中文句子。"""
        prompt = vocabulary_prompt(self.package, self.root)
        for word in ("播放", "暂停", "继续", "结束播放", "找到", "高亮", "查找"):
            self.assertNotIn(word, prompt)

    def test_prompt_is_bounded(self) -> None:
        self.assertLessEqual(len(vocabulary_prompt(self.package, self.root)), 180)

    def test_answer_language_maps_whisper_codes(self) -> None:
        self.assertEqual("zh-CN", answer_language("zh", "en"))
        self.assertEqual("en", answer_language("en", "zh-CN"))
        self.assertEqual("zh-CN", answer_language(None, "zh-CN"))
        self.assertEqual("fr", answer_language("fr", "zh-CN"))


if __name__ == "__main__":
    unittest.main()

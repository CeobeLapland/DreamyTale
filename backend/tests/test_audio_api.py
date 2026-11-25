"""Voice endpoint tests with a stubbed ASR provider.

The real provider loads a 1.6 GB model, so the endpoint is tested for routing
and honest failure instead: a spoken "暂停" must become a pause action even
though the browser labels every audio request as `qa`, and a missing model must
say so rather than pretend it heard something.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import api, c_demo
from backend.app.store import BookStore
from backend.tests.fixtures import write_package
from pipeline.models import ASRResult


class AudioInteractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        write_package(root / "books")
        self.original_api_books = api.books
        self.original_demo_books = c_demo.books
        store = BookStore(root / "books")
        api.books = store
        c_demo.books = store
        self.client = TestClient(c_demo.app)
        self.tts = patch(
            "backend.app.conductor.synthesize_answer", return_value=None
        )
        self.tts.start()
        self.addCleanup(self.tts.stop)

    def tearDown(self) -> None:
        api.books = self.original_api_books
        c_demo.books = self.original_demo_books
        self.temporary.cleanup()

    def _post(self, **overrides):
        payload = {
            "book_id": "zh-99",
            "session_id": "sess-audio",
            "kind": "qa",
            "input": {"language": "zh-CN"},
        }
        payload.update(overrides)
        return self.client.post(
            "/api/interact/audio",
            files={"audio": ("a.wav", b"RIFF-not-decoded", "audio/wav")},
            data={"request": json.dumps(payload, ensure_ascii=False)},
        )

    def test_speech_is_routed_by_its_text_not_by_the_declared_kind(self) -> None:
        with patch.object(
            c_demo, "recognize", return_value=(ASRResult(text="暂停", latency_ms=12), "")
        ):
            response = self._post()

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("control", body["kind"])
        self.assertEqual("pause", body["action"]["type"])
        self.assertEqual("暂停", body["transcript"])
        self.assertEqual(12, body["latency"]["asr"])
        self.assertEqual("ok", body["status"])

    def test_missing_asr_is_reported_not_disguised(self) -> None:
        with patch.object(
            c_demo, "recognize", return_value=(None, "ASR model not found")
        ):
            response = self._post()

        body = response.json()
        self.assertEqual("fallback", body["status"])
        self.assertIn("语音识别", body["answer"]["text"])
        self.assertIn("ASR model not found", body["answer"]["text"])
        self.assertIsNone(body["transcript"])

    def test_low_confidence_asks_for_a_repeat_instead_of_routing(self) -> None:
        with patch.object(
            c_demo,
            "recognize",
            return_value=(
                ASRResult(text="播放？", confidence=0.2, latency_ms=11),
                "",
            ),
        ):
            response = self._post()

        body = response.json()
        self.assertEqual("fallback", body["status"])
        self.assertEqual("low_confidence_asr", body["error"]["code"])
        self.assertEqual("none", body["action"]["type"])
        self.assertEqual("播放？", body["transcript"])
        self.assertIn("不太确定", body["answer"]["text"])

    def test_answer_audio_path_is_returned_when_tts_succeeds(self) -> None:
        with patch.object(
            c_demo,
            "recognize",
            return_value=(
                ASRResult(text="他们在搭什么？", confidence=0.9, latency_ms=10),
                "",
            ),
        ), patch(
            "backend.app.conductor.synthesize_answer",
            return_value="derived/audio/answer/test.mp3",
        ):
            response = self._post()

        body = response.json()
        self.assertEqual(
            "derived/audio/answer/test.mp3", body["answer"]["audio_path"]
        )
        self.assertIsNotNone(body["latency"]["tts"])


if __name__ == "__main__":
    unittest.main()

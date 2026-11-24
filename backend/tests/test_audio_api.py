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


if __name__ == "__main__":
    unittest.main()

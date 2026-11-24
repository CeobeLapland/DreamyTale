"""Critic checks generated assets without models or ffmpeg."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import critic
from pipeline.config import BookSpec


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class CriticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.book_root = self.root / "zh-99"
        self.spec = BookSpec("zh-99", "", "", "", "zh-CN", "narrative", "test")
        self.patcher = mock.patch.object(critic, "DATA", self.root)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(self.temporary.cleanup)

    def _write_book(self, pages: int = 2) -> None:
        _write(
            self.book_root / "book.json",
            {"pages": [{"index": index} for index in range(1, pages + 1)]},
        )
        _write(
            self.book_root / "derived" / "story" / "story_plan.json",
            {
                "pages": [
                    {"page_index": index, "beats": [{"narration": "narration"}]}
                    for index in range(1, pages + 1)
                ]
            },
        )
        _write(
            self.book_root / "derived" / "scene" / "scene_plan.json",
            {
                "scenes": [
                    {
                        "scene_id": f"scene-{index}",
                        "page_index": index,
                        "caption": "caption",
                        "prompt": "prompt",
                        "subtitles": [{"text": "line", "start_ms": 0, "end_ms": 100}],
                    }
                    for index in range(1, pages + 1)
                ]
            },
        )
        _write(
            self.book_root / "derived" / "scene" / "timeline.json",
            {
                "pages": [
                    {"page_index": index, "start_ms": (index - 1) * 1000, "end_ms": index * 1000}
                    for index in range(1, pages + 1)
                ]
            },
        )
        video = self.book_root / "derived" / "video" / "final.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"video")
        for index in range(1, pages + 1):
            audio = self.book_root / "derived" / "audio" / "narration" / f"page-{index:03d}.mp3"
            audio.parent.mkdir(parents=True, exist_ok=True)
            audio.write_bytes(b"audio")

    def test_complete_book_is_ok(self) -> None:
        self._write_book()

        report = critic.run_critic(self.spec)

        self.assertTrue(report["ok"])
        self.assertEqual([], report["warnings"])
        self.assertEqual(2, report["stats"]["pages"])
        self.assertTrue(
            (self.book_root / "derived" / "critic" / "report.json").is_file()
        )

    def test_missing_page_and_timeline_gap_are_reported(self) -> None:
        self._write_book(pages=2)
        _write(
            self.book_root / "derived" / "scene" / "timeline.json",
            {
                "pages": [
                    {"page_index": 1, "start_ms": 0, "end_ms": 1000},
                    {"page_index": 2, "start_ms": 1500, "end_ms": 2500},
                ]
            },
        )
        _write(self.book_root / "derived" / "story" / "story_plan.json", {"pages": [{"page_index": 1, "beats": []}]})

        report = critic.run_critic(self.spec)
        codes = {warning["code"] for warning in report["warnings"]}

        self.assertIn("story_missing_page", codes)
        self.assertIn("timeline_gap", codes)
        self.assertTrue(report["ok"])

    def test_missing_video_is_an_error(self) -> None:
        self._write_book()
        (self.book_root / "derived" / "video" / "final.mp4").unlink()

        report = critic.run_critic(self.spec)

        self.assertFalse(report["ok"])
        self.assertIn("video_missing", {warning["code"] for warning in report["warnings"]})


if __name__ == "__main__":
    unittest.main()

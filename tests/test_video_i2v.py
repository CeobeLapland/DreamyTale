"""I2V branch of the video stage, exercised with a fake provider (no network)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

from pipeline import video
from pipeline.config import BookSpec
from pipeline.models.i2v import I2VRequest


def _write_book(root: Path) -> None:
    book_root = root / "zh-i2v"
    (book_root / "pages").mkdir(parents=True)
    (book_root / "derived" / "scene").mkdir(parents=True)
    image = np.zeros((600, 1000, 3), dtype=np.uint8)
    image[:, :] = (180, 120, 60)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    encoded.tofile(book_root / "pages" / "001.png")
    (book_root / "book.json").write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "index": 1,
                        "image_path": "pages/001.png",
                        "width_px": 2608,
                        "height_px": 1304,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (book_root / "derived" / "scene" / "scene_plan.json").write_text(
        json.dumps(
            {
                "scenes": [
                    {
                        "scene_id": "scene-zh-i2v-001",
                        "page_index": 1,
                        "start_ms": 0,
                        "end_ms": 1000,
                        "caption": "test",
                        "prompt": "test prompt",
                        "negative_prompt": "",
                        "camera": "fixed",
                        "seed": 7,
                        "keyframe_path": "",
                        "subtitles": [],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


class FakeI2V:
    name = "fake_i2v"

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[I2VRequest] = []
        self.fail = fail

    def available(self) -> bool:
        return True

    def generate(self, request: I2VRequest, out_path: Path) -> Path:
        self.calls.append(request)
        if self.fail:
            raise RuntimeError("fake api is down")
        video.render_scene_animation(
            request.image_path,
            out_path,
            duration_ms=request.duration_ms,
            camera="fixed",
            fps=8,
            size=(request.width, request.height),
        )
        return out_path


class I2VVideoStageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        _write_book(self.root)
        self.spec = BookSpec("zh-i2v", "", "", "", "zh-CN", "narrative", "test")
        self.addCleanup(self.temporary.cleanup)

    def _run(self, provider: FakeI2V) -> dict:
        config = {
            "i2v": {
                "provider": "fake",
                "scene_ids": ["scene-zh-i2v-001"],
                "max_scenes": 100,
            }
        }
        with mock.patch.object(video, "DATA", self.root), mock.patch.object(
            video, "load_config", return_value=config
        ), mock.patch.object(video, "build_i2v", return_value=provider):
            return video.run_video(self.spec)

    def test_i2v_provider_is_used_and_recorded(self) -> None:
        provider = FakeI2V()

        report = self._run(provider)

        self.assertEqual(1, len(provider.calls))
        self.assertEqual(1, report["i2v_scenes"])
        self.assertEqual(0, report["fallback_scenes"])
        manifest = json.loads(
            (self.root / "zh-i2v" / "derived" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        stage = manifest["stages"][0]
        self.assertEqual("fake_i2v", stage["provider"])
        self.assertEqual(1, stage["params"]["i2v_scenes"])
        self.assertFalse(stage["degraded"])
        result = json.loads(
            (self.root / "zh-i2v" / "derived" / "generation_result.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("fake_i2v", result["model_versions"]["video"])

    def test_i2v_failure_falls_back_to_page_animation(self) -> None:
        provider = FakeI2V(fail=True)

        report = self._run(provider)

        self.assertEqual(0, report["i2v_scenes"])
        self.assertEqual(1, report["fallback_scenes"])
        self.assertTrue(
            (self.root / "zh-i2v" / "derived" / "video" / "scene-zh-i2v-001.mp4").is_file()
        )
        manifest = json.loads(
            (self.root / "zh-i2v" / "derived" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("page-animation-v1", manifest["stages"][0]["model"])
        self.assertTrue(manifest["stages"][0]["degraded"])
        self.assertEqual("I2V_FALLBACK", manifest["stages"][0]["error_code"])


if __name__ == "__main__":
    unittest.main()

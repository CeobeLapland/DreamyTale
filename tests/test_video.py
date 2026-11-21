"""Video stage tests. Run: python -m pytest tests/test_video.py -v"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.video import _motion, render_scene_animation
from pipeline.tts import edge_tts_available, _voice_for


class MotionTests(unittest.TestCase):
    def test_camera_text_maps_to_motion(self) -> None:
        self.assertEqual(_motion("从左侧缓慢推近到画面中心"), "push_in")
        self.assertEqual(_motion("轻微拉远展示全貌"), "pull_out")
        self.assertEqual(_motion("平移跟随画面里的角色"), "pan")
        self.assertEqual(_motion("固定镜头，保留绘本纸面质感"), "fixed")
        self.assertEqual(_motion(""), "push_in")

    def test_voice_follows_the_book_language(self) -> None:
        self.assertTrue(_voice_for("zh-CN").startswith("zh-CN"))
        self.assertTrue(_voice_for("en").startswith("en-US"))


class RenderTests(unittest.TestCase):
    def test_page_animation_is_written(self) -> None:
        import cv2
        import numpy as np

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = root / "page.png"
            image = np.zeros((600, 1000, 3), dtype=np.uint8)
            image[:, :] = (200, 120, 60)
            cv2.imwrite(str(page), image)

            out = root / "scene.mp4"
            render_scene_animation(page, out, duration_ms=1000, camera="推近", fps=8)
            self.assertTrue(out.is_file())
            self.assertGreater(out.stat().st_size, 0)

            capture = cv2.VideoCapture(str(out))
            frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            capture.release()
            self.assertGreaterEqual(frames, 6)


class TtsTests(unittest.TestCase):
    def test_edge_tts_availability_is_a_bool(self) -> None:
        self.assertIsInstance(edge_tts_available(), bool)


if __name__ == "__main__":
    unittest.main()

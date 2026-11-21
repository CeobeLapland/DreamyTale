import json
import tempfile
import unittest
from pathlib import Path

from backend.app.adapters import VLMObject, VLMPageResult
from backend.app.vlm_results import apply_vlm_result
from backend.app.validation import ContractError


class VLMResultStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.package_root = Path(self.temporary.name) / "zh-99"
        (self.package_root / "pages").mkdir(parents=True)
        (self.package_root / "audio").mkdir()
        (self.package_root / "source").mkdir()
        (self.package_root / "pages" / "001.png").write_bytes(b"png")
        (self.package_root / "audio" / "001.wav").write_bytes(b"wav")
        (self.package_root / "source" / "book.pdf").write_bytes(b"pdf")
        (self.package_root / "source" / "script.txt").write_text(
            "01. 播放",
            encoding="utf-8",
        )

        package = {
            "schema_version": "1.0.0",
            "book_id": "zh-99",
            "source_name": "中文绘本99",
            "title": "测试绘本",
            "language": "zh-CN",
            "pdf_path": "source/book.pdf",
            "script_path": "source/script.txt",
            "page_count": 1,
            "pages": [
                {
                    "index": 1,
                    "image_path": "pages/001.png",
                    "text": "",
                    "text_source": "embedded_pdf",
                    "width_pt": 100.0,
                    "height_pt": 100.0,
                    "width_px": 200,
                    "height_px": 200,
                    "text_spans": [],
                    "hotspots": [
                        {
                            "hotspot_id": "page-001-hotspot-001",
                            "page_index": 1,
                            "label": "人工热区",
                            "bbox_px": [5, 5, 20, 20],
                            "description": "人工标注内容",
                            "source": "manual",
                        }
                    ],
                }
            ],
            "steps": [
                {
                    "number": 1,
                    "instruction": "播放",
                    "mandatory": True,
                    "audio_path": "audio/001.wav",
                    "actions": [
                        {
                            "action_id": "step-001-a01",
                            "type": "control",
                            "text": "播放",
                            "mandatory": True,
                            "target": None,
                        }
                    ],
                }
            ],
            "click_targets": [],
        }
        (self.package_root / "book.json").write_text(
            json.dumps(package, ensure_ascii=False),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _result(self) -> VLMPageResult:
        return VLMPageResult(
            page_index=1,
            summary="两个人物在搭积木",
            scene="室内，白天",
            characters=("小满", "花花"),
            objects=(
                VLMObject(
                    label="积木城堡",
                    category="object",
                    description="用积木搭成的城堡",
                    confidence=0.92,
                    bbox_px=(20, 30, 150, 180),
                ),
                VLMObject(
                    label="积木",
                    category="object",
                    description="一块积木",
                    confidence=0.8,
                ),
            ),
        )

    def test_writes_hotspot_and_preserves_manual_hotspot(self) -> None:
        package = apply_vlm_result(
            self.package_root,
            self._result(),
            provider="fake-vlm",
        )

        labels = [item.label for item in package.pages[0].hotspots]
        self.assertIn("人工热区", labels)
        self.assertIn("积木城堡", labels)
        generated = next(
            item
            for item in package.pages[0].hotspots
            if item.label == "积木城堡"
        )
        self.assertEqual("vlm", generated.source)
        self.assertEqual([20, 30, 150, 180], generated.bbox_px)

    def test_saves_objects_without_bbox_in_raw_result(self) -> None:
        apply_vlm_result(
            self.package_root,
            self._result(),
            provider="fake-vlm",
        )
        raw_path = (
            self.package_root / "derived" / "vlm" / "page-001.json"
        )
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        self.assertEqual(2, len(raw["objects"]))
        self.assertIsNone(raw["objects"][1]["bbox_px"])

    def test_running_twice_does_not_duplicate_hotspots(self) -> None:
        apply_vlm_result(
            self.package_root,
            self._result(),
            provider="fake-vlm",
        )
        package = apply_vlm_result(
            self.package_root,
            self._result(),
            provider="fake-vlm",
        )
        vlm_hotspots = [
            item
            for item in package.pages[0].hotspots
            if item.source == "vlm"
        ]
        self.assertEqual(1, len(vlm_hotspots))

    def test_rejects_hotspot_outside_page_bounds(self) -> None:
        result = self._result()
        invalid = VLMPageResult(
            page_index=1,
            summary=result.summary,
            scene=result.scene,
            characters=result.characters,
            objects=(
                VLMObject(
                    label="越界对象",
                    category="object",
                    description="坐标超出页面",
                    confidence=0.9,
                    bbox_px=(20, 30, 300, 180),
                ),
            ),
        )
        with self.assertRaises(ContractError):
            apply_vlm_result(
                self.package_root,
                invalid,
                provider="fake-vlm",
            )


if __name__ == "__main__":
    unittest.main()
import json
import tempfile
import unittest
from pathlib import Path

from backend.app.adapters import VLMObject, VLMPageResult
from backend.app.validation import ContractError
from backend.app.vlm_results import apply_vlm_result
from backend.tests.fixtures import write_package


class VLMResultStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.package_root = write_package(Path(self.temporary.name) / "books")

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
        self.assertIn("城堡", labels)
        self.assertIn("积木城堡", labels)
        generated = next(
            item
            for item in package.pages[0].hotspots
            if item.label == "积木城堡"
        )
        self.assertEqual("vlm", generated.source.value)
        self.assertEqual((20, 30, 150, 180), generated.bbox_px)

    def test_generated_hotspot_follows_v2_contract(self) -> None:
        package = apply_vlm_result(
            self.package_root,
            self._result(),
            provider="fake-vlm",
        )
        generated = next(
            item
            for item in package.pages[0].hotspots
            if item.label == "积木城堡"
        )

        self.assertEqual(1, generated.version)
        self.assertEqual("active", generated.status.value)
        self.assertEqual(16, len(generated.hash))
        self.assertEqual(0.92, generated.confidence)
        self.assertTrue(generated.hotspot_id.startswith("hotspot-zh-99-001-vlm-"))

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
        self.assertEqual("2.0.0", raw["schema_version"])
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
            if item.source.value == "vlm"
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

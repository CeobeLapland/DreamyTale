import tempfile
import unittest
from pathlib import Path

from pipeline import config


class MaterialResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.original_materials = config.MATERIALS
        config.MATERIALS = self.root

    def tearDown(self) -> None:
        config.MATERIALS = self.original_materials
        self.temporary.cleanup()

    def test_resolves_legacy_encoded_pdf_name(self) -> None:
        legacy_name = (
            "\u6d93\ue15f\u6783\u7f01\u6a3b\u6e7001.pdf"
        )
        expected = self.root / legacy_name
        expected.write_bytes(b"pdf")

        resolved = config.resolve_material("中文绘本01.pdf")

        self.assertEqual(expected, resolved)

    def test_resolves_legacy_encoded_audio_directory(self) -> None:
        legacy_name = "\u6d93\ue15f\u6783\u7f01\u6a3b\u6e7001"
        expected = self.root / legacy_name
        expected.mkdir()

        resolved = config.resolve_material("中文绘本01")

        self.assertEqual(expected, resolved)

    def test_prefers_exact_filename(self) -> None:
        exact = self.root / "中文绘本01.pdf"
        legacy = self.root / "\u6d93\ue15f\u6783\u7f01\u6a3b\u6e7001.pdf"
        exact.write_bytes(b"exact")
        legacy.write_bytes(b"legacy")

        resolved = config.resolve_material("中文绘本01.pdf")

        self.assertEqual(exact, resolved)

    def test_missing_material_has_clear_error(self) -> None:
        with self.assertRaises(FileNotFoundError):
            config.resolve_material("不存在的绘本.pdf")


if __name__ == "__main__":
    unittest.main()
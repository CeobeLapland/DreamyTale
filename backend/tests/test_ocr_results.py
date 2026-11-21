import json
import tempfile
import unittest
from pathlib import Path

from backend.app.adapters import OCRBlock, OCRResult
from backend.app.ocr_results import apply_ocr_result
from backend.app.validation import ContractError
from backend.tests.fixtures import write_package


class OCRResultStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.package_root = write_package(Path(self.temporary.name) / "books")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _result(self) -> OCRResult:
        return OCRResult(
            page_index=1,
            text="第1页文字",
            blocks=(
                OCRBlock(
                    text="第1页文字",
                    bbox_px=(10, 20, 100, 50),
                    confidence=0.95,
                ),
            ),
        )

    def test_writes_span_with_v2_fields(self) -> None:
        package = apply_ocr_result(
            self.package_root,
            self._result(),
            provider="fake-ocr",
        )
        span = package.pages[0].text_spans[-1]

        self.assertEqual("ocr", span.source.value)
        self.assertEqual(0.95, span.confidence)
        self.assertEqual(1, span.version)
        self.assertEqual("active", span.status.value)
        self.assertEqual(16, len(span.hash))
        self.assertEqual((10, 20, 100, 50), span.bbox_px)

    def test_replace_text_switches_page_text_source(self) -> None:
        package = apply_ocr_result(
            self.package_root,
            self._result(),
            provider="fake-ocr",
            replace_text=True,
        )

        self.assertEqual("第1页文字", package.pages[0].text)
        self.assertEqual("ocr", package.pages[0].text_source.value)
        self.assertEqual(0.95, package.pages[0].text_confidence)

    def test_saves_raw_result_with_schema_version(self) -> None:
        apply_ocr_result(
            self.package_root,
            self._result(),
            provider="fake-ocr",
        )
        raw_path = self.package_root / "derived" / "ocr" / "page-001.json"
        raw = json.loads(raw_path.read_text(encoding="utf-8"))

        self.assertEqual("2.0.0", raw["schema_version"])
        self.assertEqual("fake-ocr", raw["provider"])
        self.assertEqual(1, len(raw["blocks"]))

    def test_running_twice_does_not_duplicate_spans(self) -> None:
        apply_ocr_result(
            self.package_root,
            self._result(),
            provider="fake-ocr",
        )
        package = apply_ocr_result(
            self.package_root,
            self._result(),
            provider="fake-ocr",
        )
        ocr_spans = [
            span
            for span in package.pages[0].text_spans
            if span.source.value == "ocr"
        ]
        self.assertEqual(1, len(ocr_spans))

    def test_rejects_span_outside_page_bounds(self) -> None:
        invalid = OCRResult(
            page_index=1,
            text="越界",
            blocks=(
                OCRBlock(
                    text="越界",
                    bbox_px=(10, 20, 400, 50),
                    confidence=0.9,
                ),
            ),
        )
        with self.assertRaises(ContractError):
            apply_ocr_result(
                self.package_root,
                invalid,
                provider="fake-ocr",
            )


if __name__ == "__main__":
    unittest.main()

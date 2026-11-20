import unittest
from pathlib import Path

from backend.app.adapters import (
    AdapterUnavailableError,
    OCRBlock,
    OCRResult,
)


class FakeOCRAdapter:
    def provider_name(self) -> str:
        return "fake-ocr"

    def health(self) -> None:
        return None

    def recognize(
        self,
        image_path: Path,
        *,
        page_index: int,
        language: str,
    ) -> OCRResult:
        text = "积木城堡"
        return OCRResult(
            page_index=page_index,
            text=text,
            blocks=(
                OCRBlock(
                    text=text,
                    bbox_px=(10, 20, 100, 50),
                    confidence=0.95,
                ),
            ),
        )


class OCRAdapterContractTests(unittest.TestCase):
    def test_accepts_standard_ocr_result(self) -> None:
        adapter = FakeOCRAdapter()
        result = adapter.recognize(
            Path("page.png"),
            page_index=1,
            language="zh-CN",
        )
        self.assertEqual("fake-ocr", adapter.provider_name())
        self.assertEqual("积木城堡", result.text)
        self.assertEqual(1, result.page_index)
        self.assertEqual(len(result.blocks), 1)

    def test_rejects_invalid_bbox(self) -> None:
        with self.assertRaises(ValueError):
            OCRBlock(
                text="积木",
                bbox_px=(100, 20, 10, 50),
                confidence=0.9,
            )

    def test_marks_temporary_unavailability_as_retryable(self) -> None:
        error = AdapterUnavailableError("service timeout")
        self.assertTrue(error.retryable)

    def test_marks_bad_model_output_as_not_retryable(self) -> None:
        from backend.app.adapters import AdapterResponseError

        error = AdapterResponseError("invalid JSON")
        self.assertFalse(error.retryable)


if __name__ == "__main__":
    unittest.main()
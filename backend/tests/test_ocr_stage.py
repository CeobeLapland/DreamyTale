import json
import tempfile
import unittest
from pathlib import Path

from backend.app.adapters import AdapterUnavailableError, OCRBlock, OCRResult
from backend.app.ocr_stage import run_ocr_stage
from backend.app.store import BookStore
from backend.tests.fixtures import valid_package, write_package


class FakeOCRAdapter:
    def __init__(self) -> None:
        self.health_calls = 0

    def provider_name(self) -> str:
        return "fake-ocr"

    def health(self) -> None:
        self.health_calls += 1

    def recognize(
        self,
        image_path: Path,
        *,
        page_index: int,
        language: str,
    ) -> OCRResult:
        text = f"第{page_index}页文字"
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


class UnavailableOCRAdapter(FakeOCRAdapter):
    def health(self) -> None:
        raise AdapterUnavailableError("OCR service is offline")


class OCRStageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.book_store = BookStore(root / "books")
        self.package_root = write_package(root / "books")

        package = valid_package()
        page = package["pages"][0]
        page["text"] = ""
        page["text_source"] = "none"
        page["text_confidence"] = None
        second = json.loads(json.dumps(page))
        second["index"] = 2
        second["image_path"] = "pages/002.png"
        second["text_spans"] = []
        second["hotspots"] = []
        package["pages"] = [page, second]
        package["page_count"] = 2
        (self.package_root / "pages" / "002.png").write_bytes(b"png")
        (self.package_root / "book.json").write_text(
            json.dumps(package, ensure_ascii=False),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_processes_every_page_and_reports_progress(self) -> None:
        adapter = FakeOCRAdapter()
        progress: list[tuple[str, float]] = []

        package = run_ocr_stage(
            self.book_store,
            "zh-99",
            adapter,
            report=lambda stage, value: progress.append((stage, value)),
        )

        self.assertEqual(1, adapter.health_calls)
        self.assertEqual(2, len(package.pages))
        ocr_spans = [
            span
            for page in package.pages
            for span in page.text_spans
            if span.source.value == "ocr"
        ]
        self.assertEqual(2, len(ocr_spans))
        self.assertEqual(16, len(ocr_spans[0].hash))
        self.assertEqual(("ocr", 0.0), progress[0])
        self.assertEqual(("ocr", 1.0), progress[-1])

        first_raw = self.package_root / "derived" / "ocr" / "page-001.json"
        second_raw = self.package_root / "derived" / "ocr" / "page-002.json"
        self.assertTrue(first_raw.is_file())
        self.assertTrue(second_raw.is_file())

    def test_stops_before_pages_when_service_is_unavailable(self) -> None:
        progress: list[tuple[str, float]] = []
        with self.assertRaises(AdapterUnavailableError):
            run_ocr_stage(
                self.book_store,
                "zh-99",
                UnavailableOCRAdapter(),
                report=lambda stage, value: progress.append((stage, value)),
            )
        self.assertEqual([], progress)


if __name__ == "__main__":
    unittest.main()

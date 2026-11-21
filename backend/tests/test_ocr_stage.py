import json
import tempfile
import unittest
from pathlib import Path

from backend.app.adapters import AdapterUnavailableError, OCRBlock, OCRResult
from backend.app.ocr_stage import run_ocr_stage
from backend.app.store import BookStore


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
        self.package_root = self.book_store.root / "zh-99"

        for directory in ("pages", "audio", "source"):
            (self.package_root / directory).mkdir(parents=True)

        for index in (1, 2):
            (self.package_root / "pages" / f"{index:03d}.png").write_bytes(b"png")
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
            "page_count": 2,
            "pages": [
                {
                    "index": index,
                    "image_path": f"pages/{index:03d}.png",
                    "text": "",
                    "text_source": "embedded_pdf",
                    "width_pt": 100.0,
                    "height_pt": 100.0,
                    "width_px": 200,
                    "height_px": 200,
                    "text_spans": [],
                    "hotspots": [],
                }
                for index in (1, 2)
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
        self.assertEqual(1, len(package.pages[0].text_spans))
        self.assertEqual(1, len(package.pages[1].text_spans))
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
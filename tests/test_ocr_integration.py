"""Optional OCR integration smoke test.

Runs only when RapidOCR is installed and the local page image exists; skips on a
clean clone so unit tests stay dependency-free.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from pipeline.models import build_ocr

PAGE = Path("data/books/zh-01/pages/006.png")


class OCRIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(PAGE.exists(), "local zh-01 page image not present")
    def test_reads_rasterized_speech_bubble(self) -> None:
        provider = build_ocr()
        if not provider.available():
            self.skipTest("no OCR provider configured")
        items = provider.recognize(PAGE)
        texts = [item.text for item in items]
        self.assertTrue(any("故意" in text for text in texts), texts)


if __name__ == "__main__":
    unittest.main()

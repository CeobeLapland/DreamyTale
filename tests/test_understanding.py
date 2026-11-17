"""OCR merge tests. Run: python -m unittest discover -s tests -v"""

from __future__ import annotations

import unittest

from contracts.models import Page, PageBlock, TextSpan
from pipeline.models import load_config
from pipeline.models.base import OCRItem, VLMResult
from pipeline.narrative import parse_narrative
from pipeline.understanding import merge_ocr


def make_page(
    text: str = "",
    blocks: list[PageBlock] | None = None,
    width: int = 1000,
    height: int = 1000,
    language: str = "zh-CN",
) -> Page:
    return Page(
        index=1,
        image_path="pages/001.png",
        width_px=width,
        height_px=height,
        width_pt=500.0,
        height_pt=500.0,
        text=text,
        text_source="embedded_pdf" if text else "none",
        text_confidence=0.99 if text else None,
        language=language,
        blocks=blocks or [],
        text_spans=[],
        hotspots=[],
        sha256="a" * 64,
    )


def pdf_block(text: str, bbox: tuple[int, int, int, int]) -> PageBlock:
    return PageBlock(
        block_id="block-test-book-001-001",
        page_index=1,
        type="body",
        text=text,
        bbox_px=bbox,
        source="embedded_pdf",
        confidence=0.99,
        reading_order=1,
        lang="zh-CN",
    )


class MergeTests(unittest.TestCase):
    def test_ocr_adds_rasterized_text(self) -> None:
        page = make_page("下雨了", [pdf_block("下雨了", (50, 50, 300, 90))])
        merged = merge_ocr(
            "test-book",
            page,
            [OCRItem("我又不是故意的", (100, 500, 400, 550), 0.8)],
            "fake",
        )
        self.assertEqual(merged.accepted, 1)
        self.assertIn("我又不是故意的", merged.page.text)
        self.assertEqual(merged.page.text_source.value, "mixed")
        self.assertEqual(len(merged.page.blocks), 2)

    def test_ocr_skips_pdf_duplicate(self) -> None:
        page = make_page("下雨了", [pdf_block("下雨了", (50, 50, 300, 90))])
        merged = merge_ocr(
            "test-book",
            page,
            [OCRItem("下雨了", (55, 55, 295, 85), 0.9)],
            "fake",
        )
        self.assertEqual(merged.accepted, 0)
        self.assertEqual(merged.records[0]["reason"], "duplicate_text")

    def test_ocr_skips_watermark(self) -> None:
        page = make_page("")
        merged = merge_ocr(
            "test-book",
            page,
            [OCRItem("仅供第二届北京市大学生人工智能+创新大赛参赛使用，请勿外传", (0, 0, 1000, 200), 0.9)],
            "fake",
        )
        self.assertEqual(merged.accepted, 0)
        self.assertEqual(merged.records[0]["reason"], "watermark")

    def test_ocr_only_page(self) -> None:
        page = make_page("", language="en")
        merged = merge_ocr(
            "test-book",
            page,
            [OCRItem("Hello world", (100, 100, 500, 160), 0.85)],
            "fake",
        )
        self.assertEqual(merged.accepted, 1)
        self.assertEqual(merged.page.text, "Hello world")
        self.assertEqual(merged.page.text_source.value, "ocr")
        self.assertAlmostEqual(merged.page.text_confidence, 0.85, places=3)

    def test_invalid_bbox_is_skipped(self) -> None:
        page = make_page("")
        merged = merge_ocr("test-book", page, [OCRItem("x", (0, 0, 1, 1), 0.9)], "fake")
        self.assertEqual(merged.accepted, 0)
        self.assertEqual(merged.records[0]["reason"], "invalid_bbox")

    def test_watermark_phrase_filter(self) -> None:
        page = make_page("")
        merged = merge_ocr(
            "test-book",
            page,
            [OCRItem("北京市大学生", (100, 100, 300, 150), 0.8)],
            "fake",
            ["仅供第二届北京市大学生人工智能创新大赛纸书智伴赛题参赛使用请勿外传"],
        )
        self.assertEqual(merged.accepted, 0)
        self.assertEqual(merged.records[0]["reason"], "watermark")

    def test_inside_note_filter(self) -> None:
        note = PageBlock(
            block_id="block-test-book-001-001",
            page_index=1,
            type="note",
            text="甲骨文 楷书 木",
            bbox_px=(800, 800, 990, 990),
            source="embedded_pdf",
            confidence=0.99,
            reading_order=1,
            lang="zh-CN",
        )
        page = make_page("", blocks=[note])
        merged = merge_ocr(
            "test-book",
            page,
            [OCRItem("甲常文", (820, 820, 900, 860), 0.8)],
            "fake",
        )
        self.assertEqual(merged.accepted, 0)
        self.assertEqual(merged.records[0]["reason"], "inside_nonstory")

    def test_short_watermark_fragment(self) -> None:
        page = make_page("")
        merged = merge_ocr(
            "test-book",
            page,
            [OCRItem("清勿", (100, 100, 200, 140), 0.8)],
            "fake",
            ["仅供第二届北京市大学生人工智能创新大赛纸书智伴赛题参赛使用请勿外传"],
        )
        self.assertEqual(merged.accepted, 0)
        self.assertEqual(merged.records[0]["reason"], "watermark")


class ConfigTests(unittest.TestCase):
    def test_config_sections(self) -> None:
        cfg = load_config()
        self.assertIn("ocr", cfg)
        self.assertIn("vlm", cfg)


class NarrativeTests(unittest.TestCase):
    def test_parse_structured(self) -> None:
        result = VLMResult(text="", data={"text": "两个女孩在搭积木。", "entities": ["小满", "花花"], "visible_text": []})
        parsed = parse_narrative(result)
        self.assertEqual(parsed["text"], "两个女孩在搭积木。")
        self.assertEqual(parsed["entities"], ["小满", "花花"])

    def test_parse_json_text(self) -> None:
        result = VLMResult(text='{"text": "a", "entities": ["x"], "visible_text": ["hi"]}')
        parsed = parse_narrative(result)
        self.assertEqual(parsed["text"], "a")
        self.assertEqual(parsed["visible_text"], ["hi"])

    def test_parse_plain_text(self) -> None:
        result = VLMResult(text="plain narrative")
        parsed = parse_narrative(result)
        self.assertEqual(parsed["text"], "plain narrative")
        self.assertEqual(parsed["entities"], [])


if __name__ == "__main__":
    unittest.main()

"""Contract and parser smoke tests. Run: python -m unittest discover -s tests -v"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from contracts.models import BookPackage, Page, PageBlock, QueryAction, QueryItem, QuerySet, TextSpan
from pipeline.query_sets import _classify, _detect_lang, _split_click


def make_page(
    index: int = 1,
    text: str = "hello",
    blocks: list[PageBlock] | None = None,
    spans: list[TextSpan] | None = None,
) -> Page:
    return Page(
        index=index,
        image_path=f"pages/{index:03d}.png",
        width_px=1000,
        height_px=1000,
        width_pt=500.0,
        height_pt=500.0,
        text=text,
        text_source="embedded_pdf" if text else "none",
        text_confidence=0.99 if text else None,
        language="en",
        blocks=blocks or [],
        text_spans=spans or [],
        hotspots=[],
        sha256="a" * 64,
    )


def make_book(pages: list[Page], page_count: int | None = None) -> BookPackage:
    return BookPackage(
        book_id="test-book",
        source_name="Test",
        title="Test",
        language="en",
        content_type="narrative",
        source_type="pdf",
        source_path="source/book.pdf",
        page_count=page_count if page_count is not None else len(pages),
        pages=pages,
        status="ingested",
    )


class ContractTests(unittest.TestCase):
    def test_minimal_book(self) -> None:
        book = make_book([make_page(1), make_page(2)])
        self.assertEqual(book.page_count, 2)
        self.assertEqual(book.pages[1].index, 2)

    def test_page_count_mismatch(self) -> None:
        with self.assertRaises(ValidationError):
            make_book([make_page(1)], page_count=2)

    def test_block_bbox_outside_page(self) -> None:
        block = PageBlock(
            block_id="block-test-book-001-001",
            page_index=1,
            type="body",
            text="x",
            bbox_px=(0, 0, 2000, 100),
            source="embedded_pdf",
            confidence=0.9,
            reading_order=1,
        )
        with self.assertRaises(ValidationError):
            make_book([make_page(1, blocks=[block])])

    def test_text_span_hash(self) -> None:
        with self.assertRaises(ValidationError):
            TextSpan(
                span_id="span-test-book-001-001",
                page_index=1,
                text="hello",
                bbox_px=(0, 0, 100, 50),
                source="embedded_pdf",
                confidence=0.9,
                version=1,
                status="active",
                hash="not-a-hash",
            )

    def test_query_set(self) -> None:
        item = QueryItem(
            query_id="q-001",
            number=1,
            instruction="play",
            mandatory=True,
            lang="en",
            actions=[
                QueryAction(
                    action_id="q-001-a01",
                    kind="control",
                    text="play",
                    mandatory=True,
                    control_action="play",
                )
            ],
        )
        qs = QuerySet(
            query_set_id="test-script",
            book_id="test-book",
            name="test",
            language="mixed",
            source="official_script",
            items=[item],
        )
        self.assertEqual(len(qs.items), 1)

    def test_seek_requires_query(self) -> None:
        with self.assertRaises(ValidationError):
            QueryAction(action_id="a", kind="seek", text="find", mandatory=True)

    def test_duplicate_numbers(self) -> None:
        def item(number: int, qid: str) -> QueryItem:
            return QueryItem(
                query_id=qid,
                number=number,
                instruction="play",
                mandatory=True,
                lang="en",
                actions=[
                    QueryAction(
                        action_id=f"{qid}-a01",
                        kind="control",
                        text="play",
                        mandatory=True,
                        control_action="play",
                    )
                ],
            )

        with self.assertRaises(ValidationError):
            QuerySet(
                query_set_id="dup",
                name="dup",
                language="mixed",
                source="official_script",
                items=[item(1, "q1"), item(1, "q2")],
            )


class QueryParserTests(unittest.TestCase):
    def test_control(self) -> None:
        kind, extra = _classify("播放", None)
        self.assertEqual(kind.value, "control")
        self.assertEqual(extra["control_action"].value, "play")

    def test_seek(self) -> None:
        kind, _ = _classify("找到搭了九块积木的画面", None)
        self.assertEqual(kind.value, "seek")

    def test_find_quoted_text_is_search(self) -> None:
        kind, extra = _classify("找到“还不倒”", None)
        self.assertEqual(kind.value, "search")
        self.assertEqual(extra["search_text"], "还不倒")

    def test_highlight_this_uses_previous_search(self) -> None:
        kind, extra = _classify("高亮这句话", "我又不是故意的")
        self.assertEqual(kind.value, "highlight")
        self.assertEqual(extra["highlight_text"], "我又不是故意的")

    def test_click_split(self) -> None:
        target, action = _split_click("[点击] 点击积木城堡 | 暂停并展示城堡信息 （必选）")
        self.assertEqual(target, "积木城堡")
        self.assertEqual(action, "暂停并展示城堡信息")

    def test_language(self) -> None:
        self.assertEqual(_detect_lang("播放").value, "zh")
        self.assertEqual(_detect_lang("What happened?").value, "en")
        self.assertEqual(_detect_lang("查找文字“POPCORN”").value, "mixed")


if __name__ == "__main__":
    unittest.main()

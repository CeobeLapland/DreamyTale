"""PDF -> BookPackage v2 ingest.

This is the reference implementation of the ingest stage: render pages, extract
embedded text into block/span structure, classify watermarks and teaching notes,
and write a contract-valid `book.json`.

It intentionally does not call OCR/VLM yet. Pages without a text layer are kept
as image-only pages with `text_source: none`; the understand stage fills them.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

from contracts.models import (
    BlockType,
    BookPackage,
    Page,
    PageBlock,
    RenderInfo,
    Rights,
    SpanSource,
    Status,
    TextSource,
    TextSpan,
    content_hash,
)

from .config import DATA, DEFAULT_DPI, BookSpec

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
WATERMARK_HINTS = ("仅供", "请勿", "请久", "清勿", "仅售", "参赛", "赛题", "纸书", "外传", "版权", "人工智", "大赛")
NOTE_HINTS = (
    "汉字源流",
    "阅读指导",
    "甲骨文",
    "楷书",
    "金文",
    "小篆",
    "隶书",
    "story by",
    "pictures by",
    "share your opinions",
    "how do you like the story",
    "copyright",
    "isbn",
)
FOOTER_HINTS = ("indesign", "adobe", "导出", "印刷")


@dataclass
class RawSpan:
    text: str
    bbox_px: tuple[int, int, int, int]


@dataclass
class RawBlock:
    page_index: int
    text: str
    bbox_px: tuple[int, int, int, int]
    font_size: float
    spans: list[RawSpan] = field(default_factory=list)
    kind: str = "body"


@dataclass
class RenderedPage:
    index: int
    path: Path
    width_px: int
    height_px: int
    width_pt: float
    height_pt: float
    sha256: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _norm_repeat(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _clamp_bbox(
    bbox: tuple[float, float, float, float],
    sx: float,
    sy: float,
    width_px: int,
    height_px: int,
) -> tuple[int, int, int, int] | None:
    x1, y1, x2, y2 = bbox
    x1 = max(0, min(width_px, round(x1 * sx)))
    y1 = max(0, min(height_px, round(y1 * sy)))
    x2 = max(0, min(width_px, round(x2 * sx)))
    y2 = max(0, min(height_px, round(y2 * sy)))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    return x1, y1, x2, y2


def _is_watermark(text: str) -> bool:
    return any(hint in text for hint in WATERMARK_HINTS)


def _is_note(text: str) -> bool:
    low = text.lower()
    return any(hint in low for hint in NOTE_HINTS)


def _is_page_number(text: str) -> bool:
    return bool(re.fullmatch(r"\s*\d{1,3}\s*", text))


def _is_footer(text: str) -> bool:
    lower = text.lower()
    return any(hint in lower for hint in FOOTER_HINTS)


def _join_page_text(blocks: list[RawBlock], language: str) -> str:
    if not blocks:
        return ""
    parts = [re.sub(r"\s+", " ", b.text).strip() for b in blocks if b.text.strip()]
    if language.lower().startswith("zh"):
        return "".join(re.sub(r"\s+", "", part) for part in parts)
    return " ".join(parts)


def render_pages(pdf_path: Path, pages_dir: Path, dpi: int = DEFAULT_DPI) -> list[RenderedPage]:
    pages_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[RenderedPage] = []
    with pymupdf.open(pdf_path) as doc:
        for index, page in enumerate(doc, start=1):
            pix = page.get_pixmap(dpi=dpi)
            out = pages_dir / f"{index:03d}.png"
            pix.save(out)
            rect = page.rect
            rendered.append(
                RenderedPage(
                    index=index,
                    path=out,
                    width_px=pix.width,
                    height_px=pix.height,
                    width_pt=round(float(rect.width), 3),
                    height_pt=round(float(rect.height), 3),
                    sha256=_sha256_file(out),
                )
            )
    return rendered


def _extract_raw_blocks(page: pymupdf.Page, page_index: int, rendered: RenderedPage) -> list[RawBlock]:
    rect = page.rect
    sx = rendered.width_px / rect.width if rect.width else 1.0
    sy = rendered.height_px / rect.height if rect.height else 1.0
    raw: list[RawBlock] = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        line_texts: list[str] = []
        sizes: list[float] = []
        spans: list[RawSpan] = []
        for line in block.get("lines", []):
            parts: list[str] = []
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text.strip():
                    continue
                parts.append(text)
                sizes.append(float(span.get("size", 0.0)))
                bbox = _clamp_bbox(span.get("bbox"), sx, sy, rendered.width_px, rendered.height_px)
                if bbox:
                    spans.append(RawSpan(text=text.strip(), bbox_px=bbox))
            if parts:
                line_texts.append("".join(parts))
        text = "\n".join(line_texts).strip()
        if not text:
            continue
        bbox = _clamp_bbox(block.get("bbox"), sx, sy, rendered.width_px, rendered.height_px)
        if not bbox:
            continue
        raw.append(
            RawBlock(
                page_index=page_index,
                text=text,
                bbox_px=bbox,
                font_size=max(sizes) if sizes else 0.0,
                spans=spans,
            )
        )
    return raw


def _classify_blocks(blocks_by_page: dict[int, list[RawBlock]], page_count: int) -> None:
    counts = Counter()
    for blocks in blocks_by_page.values():
        for block in blocks:
            if len(block.text) <= 120:
                counts[_norm_repeat(block.text)] += 1

    min_repeat = max(3, math.ceil(page_count * 0.5))
    for page_index, blocks in blocks_by_page.items():
        for block in blocks:
            text = block.text
            norm = _norm_repeat(text)
            if _is_watermark(text):
                kind = "header"
            elif _is_note(text):
                kind = "note"
            elif _is_page_number(text):
                kind = "footer"
            elif _is_footer(text):
                kind = "footer"
            elif counts[norm] >= min_repeat and len(norm) <= 120 and _is_watermark(text):
                kind = "header"
            elif page_index == 1 and block.font_size >= 24 and block.bbox_px[1] < 300:
                kind = "title"
            else:
                kind = "body"
            block.kind = kind


def _span_hash(page_index: int, text: str, bbox: tuple[int, int, int, int]) -> str:
    return content_hash(
        {
            "page_index": page_index,
            "text": text,
            "bbox_px": list(bbox),
            "source": SpanSource.embedded_pdf.value,
            "confidence": 0.99,
            "version": 1,
            "status": Status.active.value,
        }
    )


def _build_pages(
    book_id: str,
    language: str,
    rendered_pages: list[RenderedPage],
    blocks_by_page: dict[int, list[RawBlock]],
    dpi: int,
    renderer_version: str,
) -> list[Page]:
    pages: list[Page] = []
    for rendered in rendered_pages:
        page_index = rendered.index
        raw_blocks = blocks_by_page.get(page_index, [])
        half = rendered.width_px / 2

        def reading_key(block: RawBlock) -> tuple[int, int, int]:
            # Spreads (width/height > 1.5) read left page -> right page -> full-width notes.
            if rendered.width_px / rendered.height_px > 1.5:
                x1, _, x2, _ = block.bbox_px
                if x1 < half < x2:
                    col = 2
                elif x2 <= half:
                    col = 0
                else:
                    col = 1
                return col, round(block.bbox_px[1] / 36), block.bbox_px[0]
            return 0, round(block.bbox_px[1] / 36), block.bbox_px[0]

        ordered = sorted(raw_blocks, key=reading_key)

        page_blocks: list[PageBlock] = []
        page_spans: list[TextSpan] = []
        body_blocks: list[RawBlock] = []
        span_seq = 0
        for seq, block in enumerate(ordered, start=1):
            kind = block.kind
            page_blocks.append(
                PageBlock(
                    block_id=f"block-{book_id}-{page_index:03d}-{seq:03d}",
                    page_index=page_index,
                    type=BlockType(kind),
                    text=block.text,
                    bbox_px=block.bbox_px,
                    source=SpanSource.embedded_pdf,
                    confidence=0.99,
                    reading_order=seq,
                    lang=language,
                )
            )
            if kind in {"header", "footer", "note"}:
                continue
            body_blocks.append(block)
            for span in block.spans:
                span_seq += 1
                page_spans.append(
                    TextSpan(
                        span_id=f"span-{book_id}-{page_index:03d}-{span_seq:03d}",
                        page_index=page_index,
                        text=span.text,
                        bbox_px=span.bbox_px,
                        source=SpanSource.embedded_pdf,
                        confidence=0.99,
                        version=1,
                        status=Status.active,
                        hash=_span_hash(page_index, span.text, span.bbox_px),
                    )
                )

        page_text = _join_page_text(body_blocks, language)
        text_source = TextSource.embedded_pdf if page_text else TextSource.none
        pages.append(
            Page(
                index=page_index,
                image_path=f"pages/{page_index:03d}.png",
                width_px=rendered.width_px,
                height_px=rendered.height_px,
                width_pt=rendered.width_pt,
                height_pt=rendered.height_pt,
                text=page_text,
                text_source=text_source,
                text_confidence=0.99 if page_text else None,
                language=language,
                blocks=page_blocks,
                text_spans=page_spans,
                hotspots=[],
                sha256=rendered.sha256,
                render=RenderInfo(dpi=dpi, renderer="pymupdf", version=renderer_version),
            )
        )
    return pages


def ingest_pdf(
    pdf_path: Path,
    book_id: str,
    language: str = "zh-CN",
    content_type: str = "narrative",
    source_name: str | None = None,
    dpi: int = DEFAULT_DPI,
) -> BookPackage:
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    book_dir = DATA / book_id
    pages_dir = book_dir / "pages"
    source_dir = book_dir / "source"
    derived_dir = book_dir / "derived" / "understanding"
    for path in (pages_dir, source_dir, derived_dir):
        path.mkdir(parents=True, exist_ok=True)

    source_target = source_dir / "book.pdf"
    if pdf_path.resolve() != source_target.resolve():
        shutil.copy2(pdf_path, source_target)

    renderer_version = getattr(pymupdf, "__version__", "unknown")
    rendered_pages = render_pages(pdf_path, pages_dir, dpi=dpi)

    blocks_by_page: dict[int, list[RawBlock]] = {}
    with pymupdf.open(pdf_path) as doc:
        for page_index, page in enumerate(doc, start=1):
            blocks_by_page[page_index] = _extract_raw_blocks(page, page_index, rendered_pages[page_index - 1])

    _classify_blocks(blocks_by_page, len(rendered_pages))
    pages = _build_pages(book_id, language, rendered_pages, blocks_by_page, dpi, renderer_version)

    now = _now()
    book = BookPackage(
        book_id=book_id,
        source_name=source_name or pdf_path.stem,
        title=source_name or pdf_path.stem,
        authors=[],
        language=language,
        languages=[language],
        content_type=content_type,
        source_type="pdf",
        source_path="source/book.pdf",
        page_count=len(pages),
        pages=pages,
        style=None,
        rights=Rights(license="competition_sample", note="命题组授权样本，仅用于本次比赛"),
        status="ingested",
        query_set_ids=[],
        capabilities_path=None,
        created_at=now,
        updated_at=now,
    )

    (book_dir / "book.json").write_text(
        json.dumps(book.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (derived_dir / "blocks.jsonl").open("w", encoding="utf-8") as fh:
        for page in pages:
            for block in page.blocks:
                fh.write(json.dumps(block.model_dump(mode="json"), ensure_ascii=False) + "\n")

    pages_with_text = sum(1 for page in pages if page.text)
    report = {
        "book_id": book_id,
        "pdf": pdf_path.name,
        "page_count": len(pages),
        "pages_with_text": pages_with_text,
        "pages_without_text": len(pages) - pages_with_text,
        "blocks": sum(len(page.blocks) for page in pages),
        "spans": sum(len(page.text_spans) for page in pages),
        "headers": sum(1 for page in pages for block in page.blocks if block.type == "header"),
        "notes": sum(1 for page in pages for block in page.blocks if block.type == "note"),
        "warnings": [] if pages_with_text else ["no embedded text layer; OCR/VLM required"],
    }
    (book_dir / "derived" / "ingest_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return book


def ingest_book(spec: BookSpec, dpi: int = DEFAULT_DPI) -> BookPackage:
    return ingest_pdf(
        pdf_path=spec.pdf_path,
        book_id=spec.book_id,
        language=spec.language,
        content_type=spec.content_type,
        source_name=spec.source_name,
        dpi=dpi,
    )


def ingest_all(specs: list[BookSpec], dpi: int = DEFAULT_DPI) -> list[BookPackage]:
    books: list[BookPackage] = []
    for spec in specs:
        print(f"ingest {spec.book_id} <- {spec.pdf_path.name}")
        book = ingest_book(spec, dpi=dpi)
        print(
            f"  pages={book.page_count} "
            f"with_text={sum(1 for p in book.pages if p.text)} "
            f"blocks={sum(len(p.blocks) for p in book.pages)} "
            f"spans={sum(len(p.text_spans) for p in book.pages)}"
        )
        books.append(book)
    return books

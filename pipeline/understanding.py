"""Free OCR understanding stage.

Reads page images, accepts OCR text that is not already covered by the PDF text
layer, and writes it back into `book.json` as PageBlock/TextSpan with
`source: ocr`. This is what fills English picture books and rasterized speech
bubbles in Chinese books.

The stage is provider-agnostic: pass any OCRProvider; the default comes from
`config/models.yaml`.
"""

from __future__ import annotations

import json
import re
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contracts.models import (
    BookPackage,
    Page,
    PageBlock,
    SpanSource,
    Status,
    TextSource,
    TextSpan,
    content_hash,
)

from .config import DATA, BookSpec
from .ingest import _is_footer, _is_note, _is_page_number, _is_watermark
from .models import load_config
from .models.base import OCRItem, OCRProvider
from .models.null import NullOCR

STORY_TYPES = {"title", "body", "caption", "sfx"}
WATERMARK_PUNCT = set("“”\"'‘’，。！？、：；（）()+-—…·.,!?;:")


def _looks_like_watermark(text: str, phrases: list[str]) -> bool:
    if not phrases:
        return False
    pool = set("".join(phrases))
    chars = [c for c in text if not c.isspace() and c not in WATERMARK_PUNCT]
    if not chars or len(chars) > 30:
        return False
    overlap = sum(1 for c in chars if c in pool) / len(chars)
    if overlap >= 0.8:
        return True
    # Short OCR fragments of a watermark often drop one character (清勿/仅售/只伴).
    return len(chars) <= 6 and overlap >= 0.5


def _center_inside(bbox: tuple[int, int, int, int], outer: tuple[int, int, int, int]) -> bool:
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


@dataclass
class MergeResult:
    page: Page
    records: list[dict[str, Any]]
    accepted: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _clamp(bbox: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int] | None:
    x1, y1, x2, y2 = bbox
    x1, y1 = max(0, min(width, x1)), max(0, min(height, y1))
    x2, y2 = max(0, min(width, x2)), max(0, min(height, y2))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    return x1, y1, x2, y2


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    return inter / max(1.0, area_a + area_b - inter)


def _dedupe_reason(
    item: OCRItem,
    page: Page,
    bbox: tuple[int, int, int, int],
    watermark_phrases: list[str] | None = None,
) -> str | None:
    text = item.text.strip()
    if not text:
        return "empty"
    if _is_watermark(text) or _looks_like_watermark(text, watermark_phrases or []):
        return "watermark"
    if _is_page_number(text):
        return "page_number"
    if _is_footer(text):
        return "footer"
    if _is_note(text):
        return "note"

    norm = _norm(text)
    for block in page.blocks:
        block_norm = _norm(block.text)
        if block_norm == norm:
            return "duplicate_text"
        if block.type in STORY_TYPES and _iou(bbox, block.bbox_px) > 0.25:
            return "overlaps_pdf_block"
        if block.type in STORY_TYPES and norm and norm in block_norm and _iou(bbox, block.bbox_px) > 0.1:
            return "substring_of_pdf_block"
        if block.type in {"header", "footer", "note"} and _iou(bbox, block.bbox_px) > 0.5:
            return "overlaps_nonstory"
        if block.type in {"note", "footer"} and _center_inside(bbox, block.bbox_px):
            return "inside_nonstory"
    return None


def _reading_key(block: PageBlock, page: Page) -> tuple[int, int, int]:
    if page.width_px / page.height_px > 1.5:
        half = page.width_px / 2
        x1, _, x2, _ = block.bbox_px
        if x1 < half < x2:
            col = 2
        elif x2 <= half:
            col = 0
        else:
            col = 1
        return col, round(block.bbox_px[1] / 36), block.bbox_px[0]
    return 0, round(block.bbox_px[1] / 36), block.bbox_px[0]


def _page_text(blocks: list[PageBlock], language: str | None) -> str:
    story = [b for b in blocks if b.type in STORY_TYPES]
    if not story:
        return ""
    if (language or "").lower().startswith("zh"):
        return "".join(re.sub(r"\s+", "", b.text) for b in story)
    return " ".join(re.sub(r"\s+", " ", b.text).strip() for b in story)


def _text_source(blocks: list[PageBlock]) -> tuple[TextSource, float | None]:
    story = [b for b in blocks if b.type in STORY_TYPES]
    has_pdf = any(b.source == SpanSource.embedded_pdf for b in story)
    has_ocr = any(b.source == SpanSource.ocr for b in story)
    if has_pdf and has_ocr:
        return TextSource.mixed, 0.95
    if has_ocr:
        conf = [b.confidence for b in story if b.source == SpanSource.ocr]
        return TextSource.ocr, round(statistics.mean(conf), 3) if conf else None
    if has_pdf:
        return TextSource.embedded_pdf, 0.99
    return TextSource.none, None


def strip_ocr(page: Page) -> Page:
    """Remove a previous OCR pass so reruns are idempotent."""
    if not any(block.source == SpanSource.ocr for block in page.blocks) and not any(
        span.source == SpanSource.ocr for span in page.text_spans
    ):
        return page
    page.blocks = [block for block in page.blocks if block.source != SpanSource.ocr]
    page.text_spans = [span for span in page.text_spans if span.source != SpanSource.ocr]
    page.blocks.sort(key=lambda block: _reading_key(block, page))
    for order, block in enumerate(page.blocks, start=1):
        block.reading_order = order
    page.text = _page_text(page.blocks, page.language)
    page.text_source, page.text_confidence = _text_source(page.blocks)
    return Page.model_validate(page.model_dump(mode="json"))


def merge_ocr(
    book_id: str,
    page: Page,
    items: list[OCRItem],
    provider: str,
    watermark_phrases: list[str] | None = None,
) -> MergeResult:
    records: list[dict[str, Any]] = []
    new_blocks: list[PageBlock] = []
    new_spans: list[TextSpan] = []

    for item in items:
        bbox = _clamp(item.bbox_px, page.width_px, page.height_px)
        if bbox is None:
            records.append(
                {"page_index": page.index, "text": item.text, "bbox_px": list(item.bbox_px), "provider": provider, "accepted": False, "reason": "invalid_bbox"}
            )
            continue
        reason = _dedupe_reason(item, page, bbox, watermark_phrases)
        if reason:
            records.append(
                {"page_index": page.index, "text": item.text, "bbox_px": list(bbox), "confidence": item.confidence, "provider": provider, "accepted": False, "reason": reason}
            )
            continue

        seq = len(new_blocks) + 1
        block_id = f"block-{book_id}-{page.index:03d}-ocr-{seq:03d}"
        span_id = f"span-{book_id}-{page.index:03d}-ocr-{seq:03d}"
        kind = "title" if page.index == 1 and bbox[1] < page.height_px * 0.35 and len(item.text) <= 120 else "body"
        new_blocks.append(
            PageBlock(
                block_id=block_id,
                page_index=page.index,
                type=kind,
                text=item.text,
                bbox_px=bbox,
                source=SpanSource.ocr,
                confidence=item.confidence,
                reading_order=len(page.blocks) + seq,
                lang=page.language,
            )
        )
        new_spans.append(
            TextSpan(
                span_id=span_id,
                page_index=page.index,
                text=item.text,
                bbox_px=bbox,
                source=SpanSource.ocr,
                confidence=item.confidence,
                version=1,
                status=Status.active,
                hash=content_hash(
                    {
                        "page_index": page.index,
                        "text": item.text,
                        "bbox_px": list(bbox),
                        "source": SpanSource.ocr.value,
                        "confidence": item.confidence,
                        "version": 1,
                        "status": Status.active.value,
                    }
                ),
            )
        )
        records.append(
            {"page_index": page.index, "text": item.text, "bbox_px": list(bbox), "confidence": item.confidence, "provider": provider, "accepted": True, "reason": None, "block_id": block_id, "span_id": span_id}
        )

    if not new_blocks:
        return MergeResult(page=page, records=records, accepted=0)

    page.blocks.extend(new_blocks)
    page.text_spans.extend(new_spans)
    page.blocks.sort(key=lambda block: _reading_key(block, page))
    for order, block in enumerate(page.blocks, start=1):
        block.reading_order = order

    page.text = _page_text(page.blocks, page.language)
    page.text_source, page.text_confidence = _text_source(page.blocks)
    page = Page.model_validate(page.model_dump(mode="json"))
    return MergeResult(page=page, records=records, accepted=len(new_blocks))


def run_ocr(spec: BookSpec, provider: OCRProvider, watermark_phrases: list[str] | None = None) -> dict[str, Any]:
    book_path = DATA / spec.book_id / "book.json"
    if not book_path.exists():
        raise FileNotFoundError(book_path)
    book = BookPackage.model_validate(json.loads(book_path.read_text(encoding="utf-8")))
    book_dir = DATA / spec.book_id
    if watermark_phrases is None:
        watermark_phrases = list((load_config().get("ocr", {}) or {}).get("watermark_phrases", []) or [])

    started = time.perf_counter()
    report: dict[str, Any] = {
        "book_id": spec.book_id,
        "provider": provider.name,
        "available": provider.available(),
        "watermark_phrases": len(watermark_phrases),
        "pages_processed": 0,
        "pages_changed": 0,
        "items": 0,
        "accepted": 0,
        "skipped": 0,
        "errors": [],
        "seconds": 0.0,
    }
    records: list[dict[str, Any]] = []

    if not report["available"]:
        report["seconds"] = round(time.perf_counter() - started, 2)
        _write_reports(book_dir, records, report)
        return report

    for position, page in enumerate(book.pages):
        book.pages[position] = strip_ocr(page)

    for position, page in enumerate(book.pages):
        image_path = book_dir / page.image_path
        if not image_path.exists():
            report["errors"].append({"page_index": page.index, "error": "missing_page_image"})
            continue
        try:
            items = provider.recognize(image_path)
        except Exception as exc:  # noqa: BLE001
            report["errors"].append({"page_index": page.index, "error": f"{type(exc).__name__}: {exc}"})
            continue

        report["pages_processed"] += 1
        report["items"] += len(items)
        merged = merge_ocr(spec.book_id, page, items, provider.name, watermark_phrases)
        book.pages[position] = merged.page
        if merged.accepted:
            report["pages_changed"] += 1
            report["accepted"] += merged.accepted
        report["skipped"] += sum(1 for record in merged.records if not record["accepted"])
        records.extend(merged.records)
        if page.index % 5 == 0 or page.index == len(book.pages):
            print(f"  {spec.book_id} page {page.index}/{len(book.pages)}", flush=True)

    book = BookPackage.model_validate(book.model_dump(mode="json"))
    book.updated_at = _now()
    book_path.write_text(json.dumps(book.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    report["seconds"] = round(time.perf_counter() - started, 2)
    _write_reports(book_dir, records, report)
    return report


def _write_reports(book_dir: Path, records: list[dict[str, Any]], report: dict[str, Any]) -> None:
    out_dir = book_dir / "derived" / "understanding"
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "ocr.jsonl").open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    (book_dir / "derived" / "ocr_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run_ocr_all(specs: list[BookSpec], provider: OCRProvider | None = None) -> list[dict[str, Any]]:
    provider = provider or NullOCR()
    watermark_phrases = list((load_config().get("ocr", {}) or {}).get("watermark_phrases", []) or [])
    reports = []
    for spec in specs:
        print(f"ocr {spec.book_id} ({provider.name})", flush=True)
        report = run_ocr(spec, provider, watermark_phrases)
        reports.append(report)
        if report["available"]:
            print(
                f"  pages={report['pages_processed']} changed={report['pages_changed']} "
                f"items={report['items']} accepted={report['accepted']} skipped={report['skipped']} "
                f"{report['seconds']}s errors={len(report['errors'])}",
                flush=True,
            )
        else:
            print("  OCR provider unavailable; pages left unchanged", flush=True)
    return reports

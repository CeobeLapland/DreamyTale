"""OCR 结果回写。

回写后的 text_spans 必须满足 v2 TextSpan：`confidence`、`version`、`status`、`hash` 齐全，
`bbox_px` 落在页图范围内（越界由契约校验拦下，不静默裁剪）。
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.app.adapters.ocr import OCRResult
from backend.app.models import BookPackage, SCHEMA_VERSION, content_hash
from backend.app.validation import (
    ContractError,
    book_package_from_dict,
    normalize_book_package,
    validate_book_package,
)


def apply_ocr_result(
    package_root: Path,
    result: OCRResult,
    *,
    provider: str,
    replace_text: bool = False,
) -> BookPackage:
    package_root = package_root.resolve()
    manifest_path = package_root / "book.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"book manifest not found: {manifest_path}")

    data = normalize_book_package(json.loads(manifest_path.read_text(encoding="utf-8")))
    book_id = data.get("book_id", "book")
    pages = data["pages"]
    page = next(
        (item for item in pages if item["index"] == result.page_index),
        None,
    )
    if page is None:
        raise ValueError(f"page not found: {result.page_index}")

    existing_spans = page.get("text_spans", [])
    retained_spans = [
        span for span in existing_spans if span.get("source") != "ocr"
    ]
    used_ids = {
        span["span_id"]
        for item in pages
        for span in item.get("text_spans", [])
        if span.get("source") != "ocr"
    }

    new_spans = []
    sequence = 1
    for block in result.blocks:
        while True:
            span_id = f"span-{book_id}-{result.page_index:03d}-ocr-{sequence:03d}"
            sequence += 1
            if span_id not in used_ids:
                break
        used_ids.add(span_id)
        span = {
            "span_id": span_id,
            "page_index": result.page_index,
            "text": block.text,
            "bbox_px": list(block.bbox_px),
            "source": "ocr",
            "confidence": block.confidence,
            "version": 1,
            "status": "active",
        }
        span["hash"] = content_hash(span)
        new_spans.append(span)

    page["text_spans"] = retained_spans + new_spans
    if replace_text:
        if result.text.strip():
            page["text"] = result.text
            page["text_source"] = "ocr"
            page["text_confidence"] = (
                sum(block.confidence for block in result.blocks) / len(result.blocks)
                if result.blocks
                else 0.0
            )
        else:
            page["text"] = ""
            page["text_source"] = "none"
            page["text_confidence"] = None

    errors = validate_book_package(data, package_root=package_root)
    if errors:
        raise ContractError(errors)

    raw_result = {
        "schema_version": SCHEMA_VERSION,
        "page_index": result.page_index,
        "provider": provider or "unknown",
        "text": result.text,
        "blocks": [
            {
                "text": block.text,
                "bbox_px": list(block.bbox_px),
                "confidence": block.confidence,
            }
            for block in result.blocks
        ],
    }

    raw_path = (
        package_root
        / "derived"
        / "ocr"
        / f"page-{result.page_index:03d}.json"
    )
    _write_json(raw_path, raw_result)
    _write_json(manifest_path, data)
    return book_package_from_dict(data, package_root=package_root)


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)

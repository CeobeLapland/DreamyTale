from __future__ import annotations

import json
from pathlib import Path

from backend.app.adapters.ocr import OCRResult
from backend.app.models import BookPackage
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

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data = normalize_book_package(data)
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
            span_id = (
                f"page-{result.page_index:03d}-span-{sequence:03d}"
            )
            sequence += 1
            if span_id not in used_ids:
                break
        used_ids.add(span_id)
        new_spans.append(
            {
                "span_id": span_id,
                "page_index": result.page_index,
                "text": block.text,
                "bbox_px": list(block.bbox_px),
                "source": "ocr",
            }
        )

    page["text_spans"] = retained_spans + new_spans
    if replace_text:
        page["text"] = result.text
        page["text_source"] = "ocr"

    errors = validate_book_package(data, package_root=package_root)
    if errors:
        raise ContractError(errors)

    raw_result = {
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
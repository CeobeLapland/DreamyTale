from __future__ import annotations

import json
from pathlib import Path

from backend.app.adapters.vlm import VLMPageResult
from backend.app.models import BookPackage
from backend.app.validation import (
    ContractError,
    book_package_from_dict,
    normalize_book_package,
    validate_book_package,
)


def apply_vlm_result(
    package_root: Path,
    result: VLMPageResult,
    *,
    provider: str,
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

    existing_hotspots = page.get("hotspots", [])
    retained_hotspots = [
        hotspot
        for hotspot in existing_hotspots
        if hotspot.get("source") != "vlm"
    ]
    used_ids = {
        hotspot["hotspot_id"]
        for item in pages
        for hotspot in item.get("hotspots", [])
        if hotspot.get("source") != "vlm"
    }

    new_hotspots = []
    sequence = 1
    for item in result.objects:
        if item.bbox_px is None:
            continue
        while True:
            hotspot_id = (
                f"page-{result.page_index:03d}-hotspot-{sequence:03d}"
            )
            sequence += 1
            if hotspot_id not in used_ids:
                break
        used_ids.add(hotspot_id)
        new_hotspots.append(
            {
                "hotspot_id": hotspot_id,
                "page_index": result.page_index,
                "label": item.label,
                "bbox_px": list(item.bbox_px),
                "description": item.description,
                "source": "vlm",
            }
        )

    page["hotspots"] = retained_hotspots + new_hotspots
    errors = validate_book_package(data, package_root=package_root)
    if errors:
        raise ContractError(errors)

    raw_result = {
        "page_index": result.page_index,
        "provider": provider or "unknown",
        "summary": result.summary,
        "scene": result.scene,
        "characters": list(result.characters),
        "objects": [
            {
                "label": item.label,
                "category": item.category,
                "description": item.description,
                "confidence": item.confidence,
                "bbox_px": (
                    list(item.bbox_px)
                    if item.bbox_px is not None
                    else None
                ),
            }
            for item in result.objects
        ],
    }

    raw_path = (
        package_root
        / "derived"
        / "vlm"
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
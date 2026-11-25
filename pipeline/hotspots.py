"""Hotspots: where the user can tap something.

Two sources, in this order:

  1. the text layer - if the thing the query taps is written on the page
     ("积木城堡"), the word box is the hotspot and the answer is exact;
  2. the vision model - for things that only exist in the picture
     ("蝙蝠翅膀"), the model is asked where the object is and the box is
     scaled back to the page pixels.

The hotspots are written into the book package (`page.hotspots`), which is
what the runtime reads when a click arrives.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contracts.models import BookPackage, Hotspot, HotspotSource, Status, content_hash
from contracts.retrieval import normalize, overlap_score

from .config import DATA, BookSpec
from .manual import auto_narrative_records

LOCATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "bbox_px": {
            "type": "array",
            "items": {"type": "integer"},
        },
        "found": {"type": "boolean"},
    },
    "required": ["bbox_px", "found"],
}

PAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "page_index": {"type": "integer"},
        "found": {"type": "boolean"},
    },
    "required": ["page_index", "found"],
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _scale_for(width: int, height: int, max_side: int) -> float:
    longest = max(width, height)
    return max_side / longest if longest else 1.0


def _overlap_ratio(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> float:
    """Overlap divided by the smaller box's area; 0 means disjoint."""
    x1 = max(first[0], second[0])
    y1 = max(first[1], second[1])
    x2 = min(first[2], second[2])
    y2 = min(first[3], second[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    intersection = (x2 - x1) * (y2 - y1)
    first_area = max(1, (first[2] - first[0]) * (first[3] - first[1]))
    second_area = max(1, (second[2] - second[0]) * (second[3] - second[1]))
    return intersection / min(first_area, second_area)


def _text_hit(target: str, pages: list[dict[str, Any]]) -> tuple[int, list[int]] | None:
    """Find the target in the page text layer, with its box when there is one."""
    needle = normalize(target)
    if not needle:
        return None
    for page in pages:
        for block in page.get("blocks") or []:
            if needle in normalize(str(block.get("text") or "")):
                bbox = block.get("bbox_px")
                return int(page["index"]), [int(value) for value in bbox] if bbox else []
        for span in page.get("text_spans") or []:
            if needle in normalize(str(span.get("text") or "")):
                bbox = span.get("bbox_px")
                return int(page["index"]), [int(value) for value in bbox] if bbox else []
    return None


def _candidate_page(target: str, pages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The page most likely to show the object."""
    needle = normalize(target)
    best: dict[str, Any] | None = None
    best_score = 0
    for page in pages:
        haystack = normalize(
            f"{page.get('text') or ''} {page.get('narrative') or ''} "
            f"{' '.join(page.get('entities') or [])}"
        )
        score = overlap_score(needle, haystack)
        if score > best_score:
            best_score = score
            best = page
    return best


def _candidate_page_with_llm(
    llm: Any,
    target: str,
    pages: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Cross-lingual page routing.

    Chinese click targets meet English page narratives ("电影海报" vs "movie
    poster"), so lexical overlap is zero. The text model reads the per-page
    descriptions and picks the page; the VLM still decides the box.
    """
    if llm is None or not llm.available():
        return None
    rows: list[str] = []
    for page in pages:
        description = " ".join(
            part
            for part in (
                str(page.get("text") or "").strip(),
                str(page.get("narrative") or "").strip(),
                " ".join(str(item) for item in page.get("entities") or []),
            )
            if part
        )
        if description:
            rows.append(f"第 {page['index']} 页：{description[:260]}")
    if not rows:
        return None
    prompt = (
        f"用户想点击绘本里的“{target}”。下面是每一页的文字和画面描述。\n"
        "请判断这个对象最可能出现在第几页；只依据描述，不要猜。\n\n"
        + "\n".join(rows)
        + "\n\n返回 JSON：{\"page_index\": 5, \"found\": true}。"
        "找不到就返回 {\"page_index\": 0, \"found\": false}。"
    )
    try:
        result = llm.chat(prompt, json_schema=PAGE_SCHEMA)
    except Exception:  # noqa: BLE001 - hotspot creation degrades, not crashes
        return None
    data = result.data if isinstance(result.data, dict) else None
    if not data or not data.get("found"):
        return None
    try:
        page_index = int(data.get("page_index") or 0)
    except (TypeError, ValueError):
        return None
    return next((page for page in pages if int(page["index"]) == page_index), None)


def _locate_with_vlm(
    vlm: Any,
    target: str,
    image_path: Path,
    width: int,
    height: int,
    max_side: int,
) -> tuple[int, int, int, int] | None:
    """Ask the vision model where the object is.

    The model sees a downscaled copy of the page, so the box it returns is in
    that image's pixels and has to be scaled back to the page.
    """
    prompt = (
        f"这是一页儿童绘本。画面里有一处是“{target}”。\n"
        "请给出它在图中的位置，返回 JSON：\n"
        "- found：画面里有没有这个东西；\n"
        "- bbox_px：它的边界框，格式 [左, 上, 右, 下]，用这张图本身的像素坐标。\n"
        "找不到就返回 found=false，bbox_px 给 [0,0,0,0]。\n"
        "只返回 JSON。"
    )
    result = vlm.describe(image_path, prompt, json_schema=LOCATE_SCHEMA)
    data = result.data if isinstance(result.data, dict) else None
    if not data or not data.get("found"):
        return None
    bbox = data.get("bbox_px")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    scale = _scale_for(width, height, max_side)
    x1, y1, x2, y2 = (int(round(float(value) * scale)) for value in bbox)
    x1 = max(0, min(width - 1, x1))
    y1 = max(0, min(height - 1, y1))
    x2 = max(x1 + 1, min(width, x2))
    y2 = max(y1 + 1, min(height, y2))
    return x1, y1, x2, y2


def build_hotspots(
    spec: BookSpec,
    vlm: Any = None,
    llm: Any = None,
    max_side: int = 1024,
) -> dict[str, Any]:
    """Create the hotspots the query set asks for and store them in the book."""
    book_path = DATA / spec.book_id / "book.json"
    query_sets = sorted((DATA / spec.book_id / "query_sets").glob("*.json"))
    if not book_path.exists():
        raise FileNotFoundError(book_path)
    if not query_sets:
        raise FileNotFoundError(f"no query set for {spec.book_id}")

    book = BookPackage.model_validate(json.loads(book_path.read_text(encoding="utf-8")))
    query_set = json.loads(query_sets[0].read_text(encoding="utf-8"))
    narratives = {
        int(record["page_index"]): record
        for record in auto_narrative_records(spec.book_id)
        if record.get("page_index")
    }
    pages: list[dict[str, Any]] = []
    for page in book.pages:
        narrative = narratives.get(page.index, {})
        pages.append(
            {
                "index": page.index,
                "text": page.text,
                "narrative": str(narrative.get("text") or ""),
                "entities": list(narrative.get("entities") or []),
                "blocks": [block.model_dump(mode="json") for block in page.blocks],
                "text_spans": [span.model_dump(mode="json") for span in page.text_spans],
            }
        )

    started = time.perf_counter()
    targets: list[tuple[str, int]] = []
    for item in query_set.get("items", []):
        for action in item.get("actions", []):
            if action.get("kind") == "click" and action.get("target"):
                target = str(action["target"]).strip()
                if target and target not in [name for name, _ in targets]:
                    targets.append((target, int(item["number"])))

    by_page: dict[int, list[Hotspot]] = {}
    from_text = 0
    from_model = 0
    from_llm_pages = 0
    unresolved: list[str] = []

    for target, number in targets:
        hit = _text_hit(target, pages)
        page_index = 0
        bbox: list[int] = []
        if hit:
            page_index, bbox = hit
            duplicate = any(
                item.page_index == page_index
                and tuple(item.bbox_px) == tuple(bbox)
                for item in by_page.get(page_index, [])
            )
            if duplicate and vlm is not None:
                # Two targets on the same text line ("大象 / 天鹅") produce the
                # same box; ask the VLM for the object itself so the boxes
                # stop being identical.
                page_model = next(
                    item for item in book.pages if item.index == page_index
                )
                image_path = DATA / spec.book_id / page_model.image_path
                located = _locate_with_vlm(
                    vlm,
                    target,
                    image_path,
                    page_model.width_px,
                    page_model.height_px,
                    getattr(vlm, "max_side", max_side),
                )
                if located:
                    bbox = list(located)
                    from_model += 1
                else:
                    from_text += 1
            else:
                from_text += 1
        else:
            page = _candidate_page(target, pages)
            if page is None:
                page = _candidate_page_with_llm(llm, target, pages)
                if page is not None:
                    from_llm_pages += 1
            if page is None:
                unresolved.append(target)
                continue
            page_index = int(page["index"])
            if vlm is not None:
                page_model = next(item for item in book.pages if item.index == page_index)
                image_path = DATA / spec.book_id / page_model.image_path
                located = _locate_with_vlm(
                    vlm,
                    target,
                    image_path,
                    page_model.width_px,
                    page_model.height_px,
                    getattr(vlm, "max_side", max_side),
                )
                if located:
                    bbox = list(located)
                    from_model += 1
                else:
                    unresolved.append(target)
                    continue
            else:
                unresolved.append(target)
                continue

        if not bbox:
            # No box, no hotspot: a hotspot without a position cannot be clicked.
            unresolved.append(target)
            continue

        hotspot = Hotspot(
            hotspot_id=f"hotspot-{spec.book_id}-{number:03d}-{len(targets):02d}",
            page_index=page_index,
            label=target,
            bbox_px=tuple(bbox),
            description=(
                f"You tapped “{target}”."
                if str(book.language).lower().startswith("en")
                else f"你点到的是“{target}”。"
            ),
            source=HotspotSource.auto if hit else HotspotSource.vlm,
            confidence=0.9 if hit else 0.6,
            version=1,
            status=Status.active,
            hash="0" * 16,
        )
        hotspot.hash = content_hash(hotspot.model_dump(mode="json"))
        by_page.setdefault(page_index, []).append(hotspot)

    # The script only names a handful of click targets. Add a few readable
    # text blocks per page so the video is not clickable on one page only.
    english = str(book.language).lower().startswith("en")
    skip_markers = (
        "出版社", "出版", "版社", "版权", "isbn", "仅供", "大赛", "请勿外传",
        "内容中心", "分级", "阅读", "学而思", "课程", "教材", "编写", "书名", "作者",
    )
    existing_boxes = {
        (item.page_index, tuple(item.bbox_px))
        for items in by_page.values()
        for item in items
    }
    boxes_by_page: dict[int, list[tuple[int, int, int, int]]] = {}
    for page_index, boxes in (
        (item.page_index, tuple(item.bbox_px))
        for items in by_page.values()
        for item in items
    ):
        boxes_by_page.setdefault(page_index, []).append(boxes)
    existing_labels = {
        normalize(item.label) for items in by_page.values() for item in items
    }
    for page in book.pages:
        if page.index == 1:
            # The cover is a pile of publisher labels, not story objects.
            continue
        added = 0
        spans = sorted(
            page.text_spans,
            key=lambda span: len(str(span.text or "")),
            reverse=True,
        )
        for span in spans:
            text = str(span.text or "").strip().strip("“”\"' ")
            if len(text) < 4 or len(text) > 40:
                continue
            if any(marker in text.lower() for marker in skip_markers):
                continue
            key = (page.index, tuple(span.bbox_px))
            if key in existing_boxes or normalize(text) in existing_labels:
                continue
            if any(
                _overlap_ratio(span.bbox_px, other) > 0.45
                for other in boxes_by_page.get(page.index, [])
            ):
                continue
            label = text[:18]
            hotspot = Hotspot(
                hotspot_id=f"hotspot-{spec.book_id}-p{page.index:03d}-{added + 1:02d}",
                page_index=page.index,
                label=label,
                bbox_px=tuple(span.bbox_px),
                description=(
                    f"You tapped “{label}”."
                    if english
                    else f"你点到的是“{label}”这段文字。"
                ),
                source=HotspotSource.auto,
                confidence=0.8,
                version=1,
                status=Status.active,
                hash="0" * 16,
            )
            hotspot.hash = content_hash(hotspot.model_dump(mode="json"))
            by_page.setdefault(page.index, []).append(hotspot)
            existing_boxes.add(key)
            boxes_by_page.setdefault(page.index, []).append(tuple(span.bbox_px))
            existing_labels.add(normalize(label))
            added += 1
            if added >= 3:
                break

    updated = []
    for page in book.pages:
        page.hotspots = by_page.get(page.index, [])
        updated.append(page)
    book.pages = updated
    book.updated_at = _now()
    book_path.write_text(
        json.dumps(book.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "book_id": spec.book_id,
        "targets": len(targets),
        "from_text": from_text,
        "from_model": from_model,
        "from_llm_pages": from_llm_pages,
        "unresolved": unresolved,
        "hotspots": sum(len(items) for items in by_page.values()),
        "seconds": round(time.perf_counter() - started, 2),
    }

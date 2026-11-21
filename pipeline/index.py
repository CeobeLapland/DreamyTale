"""Search index: everything the user can ask about, in one place.

Three sources, one index:
  * the page text layer (PDF text + OCR spans) — has coordinates;
  * the VLM visible text and the page narrative — no coordinates, but it is
    the only source for rasterized books (the English ones have no text layer);
  * the scene subtitles and aliases — what `seek` and `highlight` hit.

The index is a file inside the book package, so the backend can read exactly
the same data the pipeline produced (no second implementation of the search).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contracts.retrieval import find_scene as _find_scene
from contracts.retrieval import normalize
from contracts.retrieval import search_index as _search_index

from .config import DATA, BookSpec

INDEX_DIR = "index"
SEARCH_FILE = "search_index.json"
SCENE_FILE = "scene_index.json"


def _norm(text: str) -> str:
    return normalize(text)


def index_dir(book_id: str) -> Path:
    return DATA / book_id / "derived" / INDEX_DIR


def search_index_path(book_id: str) -> Path:
    return index_dir(book_id) / SEARCH_FILE


def scene_index_path(book_id: str) -> Path:
    return index_dir(book_id) / SCENE_FILE


def load_search_index(book_id: str) -> dict[str, Any]:
    path = search_index_path(book_id)
    if not path.is_file():
        return {"book_id": book_id, "entries": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"book_id": book_id, "entries": []}


def load_scene_index(book_id: str) -> dict[str, Any]:
    path = scene_index_path(book_id)
    if not path.is_file():
        return {"book_id": book_id, "scenes": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"book_id": book_id, "scenes": []}


def _narratives(book_id: str) -> list[dict[str, Any]]:
    path = DATA / book_id / "derived" / "understanding" / "narrative.jsonl"
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("status") == "active":
            records.append(record)
    return records


def _scenes(book_id: str) -> list[dict[str, Any]]:
    path = DATA / book_id / "derived" / "scene" / "scene_plan.json"
    if not path.is_file():
        return []
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    scenes = plan.get("scenes") if isinstance(plan, dict) else None
    return scenes if isinstance(scenes, list) else []


def build_index(spec: BookSpec) -> dict[str, Any]:
    book_path = DATA / spec.book_id / "book.json"
    if not book_path.exists():
        raise FileNotFoundError(book_path)
    book = json.loads(book_path.read_text(encoding="utf-8"))

    entries: list[dict[str, Any]] = []
    for page in book.get("pages", []):
        page_index = int(page.get("index") or 0)
        for span in page.get("text_spans", []) or []:
            entries.append(
                {
                    "entry_id": span.get("span_id"),
                    "kind": "span",
                    "page_index": page_index,
                    "text": str(span.get("text") or ""),
                    "bbox_px": list(span.get("bbox_px") or []) or None,
                    "scene_id": None,
                }
            )

    for record in _narratives(spec.book_id):
        page_index = int(record.get("page_index") or 0)
        for order, line in enumerate(record.get("visible_text") or [], start=1):
            text = str(line).strip()
            if not text:
                continue
            entries.append(
                {
                    "entry_id": f"vlm-{spec.book_id}-{page_index:03d}-{order:03d}",
                    "kind": "vlm_text",
                    "page_index": page_index,
                    "text": text,
                    "bbox_px": None,
                    "scene_id": None,
                }
            )
        narrative = str(record.get("text") or "").strip()
        if narrative:
            entries.append(
                {
                    "entry_id": f"narrative-{spec.book_id}-{page_index:03d}",
                    "kind": "narrative",
                    "page_index": page_index,
                    "text": narrative,
                    "bbox_px": None,
                    "scene_id": None,
                }
            )

    scene_records: list[dict[str, Any]] = []
    page_narratives = {
        int(record.get("page_index") or 0): str(record.get("text") or "")
        for record in _narratives(spec.book_id)
    }
    for scene in _scenes(spec.book_id):
        scene_id = str(scene.get("scene_id") or "")
        page_index = int(scene.get("page_index") or 0)
        subtitles: list[dict[str, Any]] = []
        for order, subtitle in enumerate(scene.get("subtitles") or [], start=1):
            text = str(subtitle.get("text") or "").strip()
            if not text:
                continue
            subtitles.append(subtitle)
            entries.append(
                {
                    "entry_id": f"subtitle-{scene_id}-{order:02d}",
                    "kind": "subtitle",
                    "page_index": page_index,
                    "text": text,
                    "bbox_px": None,
                    "scene_id": scene_id,
                    "start_ms": int(subtitle.get("start_ms") or 0),
                    "end_ms": int(subtitle.get("end_ms") or 0),
                }
            )
        aliases = list(scene.get("aliases") or [])
        searchable = " ".join(
            [
                str(scene.get("caption") or ""),
                " ".join(str(alias) for alias in aliases),
                " ".join(str(item.get("text") or "") for item in subtitles),
                page_narratives.get(page_index, ""),
            ]
        )
        scene_records.append(
            {
                "scene_id": scene_id,
                "page_index": page_index,
                "start_ms": int(scene.get("start_ms") or 0),
                "end_ms": int(scene.get("end_ms") or 0),
                "caption": str(scene.get("caption") or ""),
                "aliases": aliases,
                "entities": list(scene.get("entities") or []),
                "text": searchable,
            }
        )

    out_dir = index_dir(spec.book_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    search_index = {
        "book_id": spec.book_id,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
    }
    search_index_path(spec.book_id).write_text(
        json.dumps(search_index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    scene_index = {
        "book_id": spec.book_id,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "scenes": scene_records,
    }
    scene_index_path(spec.book_id).write_text(
        json.dumps(scene_index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "book_id": spec.book_id,
        "entries": len(entries),
        "scenes": len(scene_records),
        "search_index_path": str(search_index_path(spec.book_id)),
        "scene_index_path": str(scene_index_path(spec.book_id)),
    }


def search_entries(book_id: str, query: str) -> list[dict[str, Any]]:
    """Entries whose text contains the query."""
    return _search_index(load_search_index(book_id), query)


def find_scene(book_id: str, query: str) -> dict[str, Any] | None:
    """Best scene for a free text query."""
    return _find_scene(load_scene_index(book_id), query)

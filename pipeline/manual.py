"""Human corrections — the fallback that keeps the pipeline honest.

Auto products are never edited in place. A human correction is a new record with
`source="human"` that wins over the auto one, while the auto record stays
`superseded` (DATA_CONTRACT §6.4 and §7). This is what makes a book without a
working VLM still usable, and what the review queue later reads.

Layout per book:

    data/books/<book_id>/manual/narrative.json     page level human narrative
    data/books/<book_id>/manual/annotations.jsonl  field level corrections

Both files are small text and are committed, so A and C see the same fixes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DATA

MANUAL_DIR = "manual"
NARRATIVE_FILE = "narrative.json"
ANNOTATIONS_FILE = "annotations.jsonl"


def manual_dir(book_id: str) -> Path:
    return DATA / book_id / MANUAL_DIR


def narrative_path(book_id: str) -> Path:
    return manual_dir(book_id) / NARRATIVE_FILE


def annotations_path(book_id: str) -> Path:
    return manual_dir(book_id) / ANNOTATIONS_FILE


def load_narrative_corrections(book_id: str) -> dict[int, dict[str, Any]]:
    """Return human narrative corrections keyed by page index."""
    path = narrative_path(book_id)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    pages = payload.get("pages") if isinstance(payload, dict) else None
    if not isinstance(pages, dict):
        return {}
    corrections: dict[int, dict[str, Any]] = {}
    for key, value in pages.items():
        if not isinstance(value, dict):
            continue
        try:
            index = int(key)
        except (TypeError, ValueError):
            continue
        if not str(value.get("text") or "").strip():
            continue
        corrections[index] = value
    return corrections


def save_narrative_corrections(book_id: str, corrections: dict[int, dict[str, Any]]) -> Path:
    path = narrative_path(book_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "book_id": book_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "pages": {str(index): corrections[index] for index in sorted(corrections)},
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def seed_narrative_corrections(book_id: str, records: list[dict[str, Any]]) -> Path:
    """Create the human correction file from the auto narrative, keeping edits.

    Pages that already carry a human correction are left untouched so seeding
    never destroys a reviewer's work.
    """
    existing = load_narrative_corrections(book_id)
    for record in records:
        index = int(record.get("page_index") or 0)
        if index <= 0 or index in existing:
            continue
        existing[index] = {
            "text": str(record.get("text") or ""),
            "entities": list(record.get("entities") or []),
            "visible_text": list(record.get("visible_text") or []),
            "reviewer": "",
            "reason": "",
        }
    return save_narrative_corrections(book_id, existing)


def load_annotations(book_id: str) -> list[dict[str, Any]]:
    """Field level human corrections, newest last."""
    path = annotations_path(book_id)
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
        if isinstance(record, dict):
            records.append(record)
    return records


def auto_narrative_records(book_id: str) -> list[dict[str, Any]]:
    """Active auto narratives, used as the starting point for human editing."""
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

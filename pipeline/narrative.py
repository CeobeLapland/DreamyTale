"""VLM narrative stage.

Turns each page image into a short, evidence-only description plus entities and
visible text. This feeds story/scene/QA for books whose story is rasterized.

Provider-agnostic: configure `vlm` in `config/models.yaml`; if none is available
the stage is a no-op and writes a report.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contracts.models import BookPackage, Status, content_hash

from .config import DATA, BookSpec
from .manual import load_narrative_corrections
from .models.base import VLMProvider, VLMResult
from .models.null import NullVLM

PROMPT = """You are reading one page of a children's picture book.
Describe only what is visible on this page. Do not invent events from other pages.
Return JSON with exactly these keys:
- "text": 80-150 Chinese characters (or 50-100 English words): who, where, what they are doing, and the mood.
- "entities": names and important objects as written in the book.
- "visible_text": printed or handwritten words visible on the page, verbatim; [] if none.
Return JSON only."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "entities": {"type": "array", "items": {"type": "string"}},
        "visible_text": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["text", "entities", "visible_text"],
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def parse_narrative(result: VLMResult) -> dict[str, Any]:
    data = result.data
    if data is None:
        try:
            data = json.loads(result.text)
        except json.JSONDecodeError:
            data = {"text": result.text.strip(), "entities": [], "visible_text": []}
    text = str(data.get("text", "")).strip()
    entities = [str(x).strip() for x in data.get("entities", []) or [] if str(x).strip()]
    visible_text = [str(x).strip() for x in data.get("visible_text", []) or [] if str(x).strip()]
    return {"text": text, "entities": entities, "visible_text": visible_text}


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
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


def _superseded(record: dict[str, Any]) -> dict[str, Any]:
    return {**record, "status": Status.superseded.value}


def build_page_records(
    page_index: int,
    book_id: str,
    correction: dict[str, Any] | None,
    auto: dict[str, Any] | None,
    old: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Records to store for one page.

    A human correction wins over the auto narrative; the auto record is kept but
    marked superseded so nothing is silently destroyed (DATA_CONTRACT §6.4).
    """
    if correction:
        record = {
            "page_index": page_index,
            "book_id": book_id,
            "text": str(correction.get("text") or "").strip(),
            "entities": list(correction.get("entities") or []),
            "visible_text": list(correction.get("visible_text") or []),
            "source": "human",
            "confidence": 0.99,
            "version": int(old.get("version", 0)) + 1 if old else 1,
            "status": Status.active.value,
        }
        record["hash"] = content_hash(record)
        records = [record]
        if old:
            records.append(_superseded(old))
        return records

    if auto:
        record = {
            "page_index": page_index,
            "book_id": book_id,
            **auto,
            "source": "vlm",
            "confidence": 0.5,
            "version": int(old.get("version", 0)) + 1 if old else 1,
            "status": Status.active.value,
        }
        record["hash"] = content_hash(record)
        records = [record]
        if old:
            records.append(_superseded(old))
        return records

    return [old] if old else []


def run_vlm(spec: BookSpec, provider: VLMProvider) -> dict[str, Any]:
    book_path = DATA / spec.book_id / "book.json"
    if not book_path.exists():
        raise FileNotFoundError(book_path)
    book = BookPackage.model_validate(json.loads(book_path.read_text(encoding="utf-8")))
    book_dir = DATA / spec.book_id
    out_dir = book_dir / "derived" / "understanding"
    out_dir.mkdir(parents=True, exist_ok=True)
    narrative_file = out_dir / "narrative.jsonl"

    started = time.perf_counter()
    available = provider.available()
    corrections = load_narrative_corrections(spec.book_id)
    previous = {
        int(record["page_index"]): record
        for record in _read_records(narrative_file)
        if record.get("page_index") and record.get("status") == Status.active.value
    }

    report: dict[str, Any] = {
        "book_id": spec.book_id,
        "provider": provider.name,
        "available": available,
        "pages_processed": 0,
        "pages_human": 0,
        "pages_carried_over": 0,
        "errors": [],
        "seconds": 0.0,
    }

    records: list[dict[str, Any]] = []
    for page in book.pages:
        old = previous.get(page.index)
        correction = corrections.get(page.index)
        if not correction and not available:
            records.extend(build_page_records(page.index, spec.book_id, None, None, old))
            if old:
                report["pages_carried_over"] += 1
            continue

        auto: dict[str, Any] | None = None
        if not correction:
            image_path = book_dir / page.image_path
            if not image_path.exists():
                report["errors"].append({"page_index": page.index, "error": "missing_page_image"})
                continue
            try:
                result = provider.describe(image_path, PROMPT, json_schema=SCHEMA)
            except Exception as exc:  # noqa: BLE001
                report["errors"].append({"page_index": page.index, "error": f"{type(exc).__name__}: {exc}"})
                continue
            parsed = parse_narrative(result)
            if not parsed["text"]:
                report["errors"].append({"page_index": page.index, "error": "empty_narrative"})
                continue
            auto = parsed

        records.extend(build_page_records(page.index, spec.book_id, correction, auto, old))
        if correction:
            report["pages_human"] += 1
        else:
            report["pages_processed"] += 1

    with narrative_file.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    report["seconds"] = round(time.perf_counter() - started, 2)
    (book_dir / "derived" / "vlm_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def run_vlm_all(specs: list[BookSpec], provider: VLMProvider | None = None) -> list[dict[str, Any]]:
    provider = provider or NullVLM()
    reports = []
    for spec in specs:
        print(f"vlm {spec.book_id} ({provider.name})")
        report = run_vlm(spec, provider)
        reports.append(report)
        print(
            f"  auto={report['pages_processed']} human={report['pages_human']} "
            f"kept={report['pages_carried_over']} errors={len(report['errors'])} "
            f"{report['seconds']}s"
        )
        if not report["available"] and not report["pages_human"]:
            print("  VLM provider unavailable and no manual narrative; narrative unchanged")
    return reports

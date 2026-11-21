"""Check how much of a QuerySet can be resolved from the ingested book.

The book text layer comes first, but the search index (PDF text + OCR + VLM
visible text + scene subtitles) and the scene index are consulted too, so the
report says what the system can really answer today, not what the raw PDF
happens to contain.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import DATA, BookSpec
from .index import find_scene, search_entries


def _norm(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", "", text)
    return text.strip("“”\"'‘’ ")


def _book_text_pages(book: dict[str, Any]) -> list[tuple[int, str, list[dict]]]:
    pages = []
    for page in book["pages"]:
        pages.append((page["index"], _norm(page.get("text", "")), page.get("text_spans", [])))
    return pages


def _find_text(pages: list[tuple[int, str, list[dict]]], target: str) -> list[int]:
    needle = _norm(target)
    if not needle:
        return []
    hits: list[int] = []
    for page_index, text, spans in pages:
        if needle in text or any(needle in _norm(span["text"]) for span in spans):
            hits.append(page_index)
    return hits


def analyze(spec: BookSpec) -> dict[str, Any]:
    book_path = DATA / spec.book_id / "book.json"
    query_sets = sorted((DATA / spec.book_id / "query_sets").glob("*.json"))
    if not book_path.exists():
        raise FileNotFoundError(book_path)
    if not query_sets:
        raise FileNotFoundError(f"no query set for {spec.book_id}")

    book = json.loads(book_path.read_text(encoding="utf-8"))
    query_set = json.loads(query_sets[0].read_text(encoding="utf-8"))
    pages = _book_text_pages(book)

    unresolved: list[dict[str, Any]] = []
    resolved = 0
    needs_scene_plan = 0
    needs_qa_cards = 0
    needs_hotspots = 0
    by_kind: dict[str, dict[str, int]] = {}

    for item in query_set["items"]:
        for action in item["actions"]:
            kind = action["kind"]
            bucket = by_kind.setdefault(kind, {"resolved": 0, "unresolved": 0})
            target = None
            if kind in {"search", "highlight"}:
                target = action.get("search_text") or action.get("highlight_text")
                hits = _find_text(pages, target or "")
                if not hits:
                    # The PDF text layer is not the only source: the VLM read the
                    # pictures and the scenes carry the narration.
                    hits = [
                        int(entry.get("page_index") or 0)
                        for entry in search_entries(spec.book_id, target or "")
                    ]
                if hits:
                    resolved += 1
                    bucket["resolved"] += 1
                else:
                    bucket["unresolved"] += 1
                    unresolved.append(
                        {
                            "number": item["number"],
                            "kind": kind,
                            "instruction": item["instruction"],
                            "target": target,
                            "reason": "text_not_found_needs_ocr_or_vlm",
                        }
                    )
            elif kind == "click":
                target = action.get("target")
                hotspots = [
                    hotspot
                    for page in book["pages"]
                    for hotspot in page.get("hotspots", [])
                    if hotspot.get("label") == target
                ]
                if hotspots:
                    resolved += 1
                    bucket["resolved"] += 1
                else:
                    needs_hotspots += 1
                    bucket["unresolved"] += 1
                    unresolved.append(
                        {
                            "number": item["number"],
                            "kind": kind,
                            "instruction": item["instruction"],
                            "target": target,
                            "reason": "needs_hotspot",
                        }
                    )
            elif kind == "seek":
                scene = find_scene(spec.book_id, action.get("seek_query") or "")
                if scene:
                    resolved += 1
                    bucket["resolved"] += 1
                else:
                    needs_scene_plan += 1
                    bucket["unresolved"] += 1
                    unresolved.append(
                        {
                            "number": item["number"],
                            "kind": kind,
                            "instruction": item["instruction"],
                            "target": action.get("seek_query"),
                            "reason": "needs_scene_plan",
                        }
                    )
            elif kind == "qa":
                needs_qa_cards += 1
                bucket["unresolved"] += 1
                unresolved.append(
                    {
                        "number": item["number"],
                        "kind": kind,
                        "instruction": item["instruction"],
                        "target": None,
                        "reason": "needs_qa_card",
                    }
                )
            else:
                resolved += 1
                bucket["resolved"] += 1

    report = {
        "book_id": spec.book_id,
        "query_set_id": query_set["query_set_id"],
        "pages": len(book["pages"]),
        "pages_with_text": sum(1 for p in book["pages"] if p.get("text")),
        "pages_with_spans": sum(1 for p in book["pages"] if p.get("text_spans")),
        "by_kind": by_kind,
        "resolved_actions": resolved,
        "unresolved_actions": len(unresolved),
        "needs_scene_plan": needs_scene_plan,
        "needs_qa_cards": needs_qa_cards,
        "needs_hotspots": needs_hotspots,
        "unresolved": unresolved,
    }
    out_dir = DATA / spec.book_id / "derived"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "coverage_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def analyze_all(specs: list[BookSpec]) -> list[dict[str, Any]]:
    reports = []
    for spec in specs:
        report = analyze(spec)
        reports.append(report)
        print(
            f"{spec.book_id}: resolved={report['resolved_actions']} "
            f"unresolved={report['unresolved_actions']} "
            f"(scene={report['needs_scene_plan']} qa={report['needs_qa_cards']} "
            f"hotspot={report['needs_hotspots']})"
        )
    return reports

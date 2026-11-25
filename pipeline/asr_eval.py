"""Transcribe the official WAV query set and report what was heard.

This is the offline check for the voice path: every item in every book's query
set has a WAV recorded by the organisers. We transcribe each one with the same
provider the reader uses, compare it to the script line, and write the
transcripts to `derived/asr/transcripts.jsonl` so failures can be inspected.

It is a diagnostic, not a scoreboard: the demo needs the commands to be heard,
not a particular number.
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any

from contracts.models import BookPackage

from .asr_prompt import vocabulary_prompt
from .config import DATA, BookSpec
from .models import ASRProvider

OUTPUT = Path("derived") / "asr" / "transcripts.jsonl"


def _normalize(text: str) -> str:
    return "".join(
        char
        for char in (text or "").lower()
        if char.isalnum() or "\u4e00" <= char <= "\u9fff"
    )


def _edit_distance(left: str, right: str) -> int:
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _cer(expected: str, actual: str) -> float:
    clean_expected = _normalize(expected)
    clean_actual = _normalize(actual)
    if not clean_expected:
        return 0.0 if not clean_actual else 1.0
    return _edit_distance(clean_expected, clean_actual) / len(clean_expected)


def _load_items(book_id: str) -> list[dict[str, Any]]:
    query_sets = sorted((DATA / book_id / "query_sets").glob("*.json"))
    if not query_sets:
        return []
    data = json.loads(query_sets[0].read_text(encoding="utf-8"))
    return [item for item in data.get("items", []) if isinstance(item, dict)]


def run_asr_eval(
    spec: BookSpec,
    provider: ASRProvider,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    book_root = DATA / spec.book_id
    book_path = book_root / "book.json"
    if not book_path.is_file():
        return {"book_id": spec.book_id, "error": "book.json missing", "items": 0}
    package = BookPackage.model_validate(
        json.loads(book_path.read_text(encoding="utf-8"))
    )
    prompt = vocabulary_prompt(package, book_root)

    items = _load_items(spec.book_id)
    if limit is not None:
        items = items[:limit]

    records: list[dict[str, Any]] = []
    latencies: list[int] = []
    started = time.perf_counter()
    for item in items:
        audio_path = item.get("audio_path")
        if not audio_path:
            continue
        path = book_root / str(audio_path)
        if not path.is_file():
            continue
        expected = str(item.get("instruction") or "")
        try:
            result = provider.transcribe(path, initial_prompt=prompt)
        except Exception as exc:  # noqa: BLE001 - one bad clip must not stop the run
            records.append(
                {
                    "book_id": spec.book_id,
                    "query_id": item.get("query_id"),
                    "audio_path": str(audio_path),
                    "expected": expected,
                    "text": "",
                    "error": f"{type(exc).__name__}: {exc}",
                    "cer": 1.0,
                }
            )
            continue

        latencies.append(result.latency_ms)
        records.append(
            {
                "book_id": spec.book_id,
                "query_id": item.get("query_id"),
                "audio_path": str(audio_path),
                "expected": expected,
                "text": result.text,
                "language": result.language,
                "duration_ms": result.duration_ms,
                "latency_ms": result.latency_ms,
                "cer": round(_cer(expected, result.text), 4),
            }
        )

    out_path = book_root / OUTPUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    errors = [record for record in records if record.get("error")]
    scored = [record for record in records if not record.get("error")]
    mean_cer = statistics.fmean(record["cer"] for record in scored) if scored else 0.0
    worst = sorted(scored, key=lambda record: record["cer"], reverse=True)[:5]
    latencies.sort()
    p50 = latencies[len(latencies) // 2] if latencies else 0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0

    return {
        "book_id": spec.book_id,
        "items": len(records),
        "errors": len(errors),
        "mean_cer": round(mean_cer, 3),
        "p50_ms": p50,
        "p95_ms": p95,
        "seconds": round(time.perf_counter() - started, 1),
        "worst": worst,
        "path": str(out_path),
    }

"""Online session artifacts: Turn history and interaction Trace.

Contract paths (`docs/DATA_CONTRACT.md` §2):

- `data/turns/<yyyy-mm-dd>.jsonl` — one `Turn` per interaction, append-only.
- `data/traces/<yyyy-mm-dd>/<trace_id>.json` — one technical `Trace` per turn.

Both live outside the per-book package so they can be audited across books.
Writes are best-effort: a read-only data directory must not break an answer.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from backend.app.models import Trace, Turn

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_WRITE_LOCK = Lock()
_MAX_SCAN_FILES = 400


def default_data_root() -> Path:
    return Path(
        os.environ.get("DREAMYTALE_SESSION_ROOT", REPOSITORY_ROOT / "data")
    ).resolve()


def _root(data_root: Path | None) -> Path:
    return Path(data_root).resolve() if data_root is not None else default_data_root()


def _day(now: datetime) -> str:
    return now.strftime("%Y-%m-%d")


def write_turn(turn: Turn, data_root: Path | None = None) -> Path | None:
    """Append one Turn; returns the file path, or None when writing failed."""
    root = _root(data_root)
    now = turn.ts.astimezone() if turn.ts.tzinfo else datetime.now()
    path = root / "turns" / f"{_day(now)}.jsonl"
    with _WRITE_LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(turn.model_dump_json() + "\n")
        except OSError:
            return None
    return path


def write_trace(trace: Trace, data_root: Path | None = None) -> Path | None:
    """Write one Trace; returns the file path, or None when writing failed."""
    root = _root(data_root)
    now = trace.created_at.astimezone() if trace.created_at.tzinfo else datetime.now()
    path = root / "traces" / _day(now) / f"{trace.trace_id}.json"
    with _WRITE_LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                trace.model_dump_json(indent=2), encoding="utf-8"
            )
        except OSError:
            return None
    return path


def _json_lines(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
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


def read_turns(
    book_id: str,
    *,
    data_root: Path | None = None,
    session_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Recent turns for one book, oldest first (so the player can replay them)."""
    root = _root(data_root)
    folder = root / "turns"
    files = sorted(folder.glob("*.jsonl"), reverse=True)[:_MAX_SCAN_FILES]
    collected: list[dict[str, Any]] = []
    for path in files:
        for record in reversed(_json_lines(path)):
            if record.get("book_id") != book_id:
                continue
            if session_id and record.get("session_id") != session_id:
                continue
            collected.append(record)
            if len(collected) >= limit:
                collected.reverse()
                return collected
    collected.reverse()
    return collected


def read_traces(
    book_id: str,
    *,
    data_root: Path | None = None,
    session_id: str | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Recent interaction traces for one book, newest first."""
    root = _root(data_root)
    files = sorted(
        (root / "traces").glob("*/*.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )[:_MAX_SCAN_FILES]
    collected: list[dict[str, Any]] = []
    for path in files:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict):
            continue
        payload = record.get("input") or {}
        if payload.get("book_id") != book_id:
            continue
        if session_id and payload.get("session_id") != session_id:
            continue
        if record.get("kind") != "interaction":
            continue
        record["_path"] = str(path)
        collected.append(record)
        if len(collected) >= limit:
            break
    return collected


def latest_eval_run(root: Path | None = None) -> dict[str, Any] | None:
    """Newest `runs/run-*/run.json` for the in-page evaluation panel."""
    runs_root = (Path(root) if root is not None else REPOSITORY_ROOT) / "runs"
    candidates = sorted(
        runs_root.glob("run-*/run.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict):
            record["_path"] = str(path)
            return record
    return None

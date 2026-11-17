"""Validate book packages and query sets against the v2 contract.

Usage:
    python -m contracts.validate --all
    python -m contracts.validate --book data/books/zh-01/book.json
    python -m contracts.validate --query-set data/books/zh-01/query_sets/zh-01-script-v1.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .models import BookPackage, QuerySet

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "books"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_book(path: Path) -> list[str]:
    try:
        BookPackage.model_validate(load_json(path))
    except (ValidationError, json.JSONDecodeError, OSError) as exc:
        return [f"{path}: {exc}"]
    return []


def validate_query_set(path: Path) -> list[str]:
    try:
        QuerySet.model_validate(load_json(path))
    except (ValidationError, json.JSONDecodeError, OSError) as exc:
        return [f"{path}: {exc}"]
    return []


def discover() -> tuple[list[Path], list[Path]]:
    books = sorted(DATA.glob("*/book.json"))
    query_sets = sorted(DATA.glob("*/query_sets/*.json"))
    return books, query_sets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="validate every book and query set under data/books")
    parser.add_argument("--book", action="append", default=[], help="book.json path (repeatable)")
    parser.add_argument("--query-set", action="append", default=[], help="query set JSON path (repeatable)")
    args = parser.parse_args(argv)

    books = [Path(p) for p in args.book]
    query_sets = [Path(p) for p in args.query_set]
    if args.all or (not books and not query_sets):
        b, q = discover()
        books.extend(b)
        query_sets.extend(q)

    errors: list[str] = []
    for path in books:
        errors.extend(validate_book(path))
    for path in query_sets:
        errors.extend(validate_query_set(path))

    if errors:
        for err in errors:
            print(f"ERROR {err}")
        print(f"\n{len(errors)} error(s)")
        return 1

    print(f"ok: {len(books)} book(s), {len(query_sets)} query set(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

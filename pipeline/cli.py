"""CLI for the local content pipeline.

Commands:
    python -m pipeline ingest --all
    python -m pipeline ingest --pdf path/to/book.pdf --book-id my-book --language zh-CN
    python -m pipeline parse-scripts --all
    python -m pipeline all
    python -m pipeline validate
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from contracts.validate import main as validate_main

from .config import BOOKS, DEFAULT_DPI, find_book
from .coverage import analyze_all
from .ingest import ingest_book, ingest_pdf
from .query_sets import parse_script


def _select(args: argparse.Namespace) -> list:
    if args.all:
        return list(BOOKS)
    return [find_book(book_id) for book_id in args.book]


def cmd_ingest(args: argparse.Namespace) -> int:
    if args.pdf:
        if not args.book_id:
            raise SystemExit("--pdf requires --book-id")
        book = ingest_pdf(
            Path(args.pdf),
            book_id=args.book_id,
            language=args.language,
            content_type=args.content_type,
            source_name=args.source_name,
            dpi=args.dpi,
        )
        print(f"ok {book.book_id}: pages={book.page_count}")
        return 0

    specs = _select(args)
    if not specs:
        raise SystemExit("select --all or --book")
    for spec in specs:
        print(f"ingest {spec.book_id} <- {spec.pdf_path.name}")
        book = ingest_book(spec, dpi=args.dpi)
        print(
            f"  pages={book.page_count} "
            f"with_text={sum(1 for p in book.pages if p.text)} "
            f"blocks={sum(len(p.blocks) for p in book.pages)} "
            f"spans={sum(len(p.text_spans) for p in book.pages)}"
        )
    return 0


def cmd_parse_scripts(args: argparse.Namespace) -> int:
    specs = _select(args)
    if not specs:
        raise SystemExit("select --all or --book")
    for spec in specs:
        print(f"parse scripts {spec.book_id} <- {spec.script_path.name}")
        query_set = parse_script(spec)
        print(
            f"  items={len(query_set.items)} "
            f"actions={sum(len(i.actions) for i in query_set.items)} "
            f"mandatory={sum(1 for i in query_set.items if i.mandatory)}"
        )
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    specs = _select(args) if (args.all or args.book) else list(BOOKS)
    for spec in specs:
        print(f"ingest {spec.book_id} <- {spec.pdf_path.name}")
        book = ingest_book(spec, dpi=args.dpi)
        print(
            f"  pages={book.page_count} "
            f"with_text={sum(1 for p in book.pages if p.text)} "
            f"blocks={sum(len(p.blocks) for p in book.pages)} "
            f"spans={sum(len(p.text_spans) for p in book.pages)}"
        )
        print(f"parse scripts {spec.book_id} <- {spec.script_path.name}")
        query_set = parse_script(spec)
        print(
            f"  items={len(query_set.items)} "
            f"actions={sum(len(i.actions) for i in query_set.items)} "
            f"mandatory={sum(1 for i in query_set.items if i.mandatory)}"
        )
    analyze_all(specs)
    return validate_main(["--all"])


def cmd_coverage(args: argparse.Namespace) -> int:
    specs = _select(args)
    if not specs:
        raise SystemExit("select --all or --book")
    analyze_all(specs)
    return 0


def cmd_validate(_args: argparse.Namespace) -> int:
    return validate_main(["--all"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_selection(p: argparse.ArgumentParser) -> None:
        p.add_argument("--all", action="store_true", help="all six configured books")
        p.add_argument("--book", action="append", default=[], help="book_id (repeatable)")

    p_ingest = sub.add_parser("ingest", help="PDF -> pages + book.json")
    add_selection(p_ingest)
    p_ingest.add_argument("--pdf", help="arbitrary PDF; requires --book-id")
    p_ingest.add_argument("--book-id")
    p_ingest.add_argument("--language", default="zh-CN")
    p_ingest.add_argument("--content-type", default="narrative", choices=["narrative", "expository", "mixed"])
    p_ingest.add_argument("--source-name")
    p_ingest.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    p_ingest.set_defaults(func=cmd_ingest)

    p_parse = sub.add_parser("parse-scripts", help="txt scripts -> QuerySet + audio")
    add_selection(p_parse)
    p_parse.set_defaults(func=cmd_parse_scripts)

    p_all = sub.add_parser("all", help="ingest + parse scripts + coverage + validate")
    add_selection(p_all)
    p_all.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    p_all.set_defaults(func=cmd_all)

    p_cov = sub.add_parser("coverage", help="check how much of each QuerySet is resolvable")
    add_selection(p_cov)
    p_cov.set_defaults(func=cmd_coverage)

    p_validate = sub.add_parser("validate", help="validate every book.json and query set")
    p_validate.set_defaults(func=cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

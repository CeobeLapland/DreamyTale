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
import json
import sys
import time
from pathlib import Path

from contracts.models import BookPackage
from contracts.validate import main as validate_main

from .config import BOOKS, DATA, DEFAULT_DPI, find_book
from .coverage import analyze_all
from .ingest import ingest_book, ingest_pdf
from .index import build_index
from .manual import auto_narrative_records, seed_narrative_corrections
from .models import build_llm, build_ocr, build_vlm, config_path, status as provider_status
from .narrative import run_vlm_all
from .query_sets import parse_script
from .review import render_overlay
from .scene import run_scene
from .story import run_story
from .tts import run_tts
from .understanding import run_ocr_all
from .video import run_video


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


def cmd_understand(args: argparse.Namespace) -> int:
    specs = _select(args)
    if not specs:
        raise SystemExit("select --all or --book")
    provider = build_ocr()
    print(f"ocr provider: {provider.name} (config: {config_path()})")
    if not provider.available():
        print("warning: no OCR provider available; pages left unchanged")
    run_ocr_all(specs, provider)
    analyze_all(specs)
    return validate_main(["--all"])


def cmd_narrative(args: argparse.Namespace) -> int:
    specs = _select(args)
    if not specs:
        raise SystemExit("select --all or --book")
    provider = build_vlm()
    print(f"vlm provider: {provider.name} (config: {config_path()})")
    if not provider.available():
        print("warning: no VLM provider available; narrative unchanged")
    run_vlm_all(specs, provider)
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    specs = _select(args)
    if not specs:
        raise SystemExit("select --book")
    if not args.page:
        raise SystemExit("--page is required")
    if args.out and len(specs) > 1:
        raise SystemExit("--out supports one book at a time")
    for spec in specs:
        out = Path(args.out) if args.out else None
        path = render_overlay(spec.book_id, args.page, target=args.target, out_path=out)
        print(path)
    return 0


def cmd_manual(args: argparse.Namespace) -> int:
    specs = _select(args)
    if not specs:
        raise SystemExit("select --all or --book")
    for spec in specs:
        records = auto_narrative_records(spec.book_id)
        if not records:
            print(f"{spec.book_id}: no auto narrative yet; create the file empty and fill it by hand")
        path = seed_narrative_corrections(spec.book_id, records)
        print(f"{spec.book_id}: {path}")
    return 0


def cmd_vlm_check(args: argparse.Namespace) -> int:
    """One page, one prompt: check the local model end to end without a full run."""
    specs = _select(args)
    if not specs:
        raise SystemExit("select --all or --book")
    provider = build_vlm()
    model = getattr(provider, "model", "?")
    print(f"vlm provider: {provider.name} model={model}")
    if not provider.available():
        print(f"unavailable: {getattr(provider, 'detail', '') or 'not configured'}")
        return 1
    prompt = args.prompt or "用中文简短描述这一页上看到的内容，只写画面里看得见的内容。"
    for spec in specs:
        book_path = DATA / spec.book_id / "book.json"
        if not book_path.exists():
            print(f"{spec.book_id}: no book.json")
            continue
        book = BookPackage.model_validate(json.loads(book_path.read_text(encoding="utf-8")))
        pages = [p for p in book.pages if p.index == args.page] if args.page else book.pages[:1]
        for page in pages:
            image_path = DATA / spec.book_id / page.image_path
            started = time.perf_counter()
            result = provider.describe(image_path, prompt)
            elapsed = time.perf_counter() - started
            print(f"{spec.book_id} page {page.index}: {elapsed:.1f}s")
            print(result.text[:600])
    return 0


def cmd_story(args: argparse.Namespace) -> int:
    specs = _select(args)
    if not specs:
        raise SystemExit("select --all or --book")
    llm = build_llm()
    print(f"llm provider: {llm.name} model={getattr(llm, 'model', '')}")
    if not llm.available():
        print("warning: no LLM available; existing plans are kept, new books fall back to the page text")
    for spec in specs:
        report = run_story(spec, llm)
        if report.get("skipped"):
            print(f"  {spec.book_id}: skipped ({report['reason']}); existing plan kept")
            continue
        print(
            f"  {spec.book_id}: llm_pages={report['pages_llm']} "
            f"fallback_pages={report['pages_fallback']} "
            f"characters={report['characters']} beats={report['beats']} "
            f"errors={len(report['errors'])} {report['seconds']}s"
        )
    return 0


def cmd_scene(args: argparse.Namespace) -> int:
    specs = _select(args)
    if not specs:
        raise SystemExit("select --all or --book")
    for spec in specs:
        report = run_scene(spec)
        print(
            f"  {spec.book_id}: pages={report['pages']} scenes={report['scenes']} "
            f"total={report['total_ms']}ms -> {report['plan_path']}"
        )
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    specs = _select(args)
    if not specs:
        raise SystemExit("select --all or --book")
    for spec in specs:
        report = build_index(spec)
        print(
            f"  {spec.book_id}: entries={report['entries']} scenes={report['scenes']} "
            f"-> {report['search_index_path']}"
        )
    return 0


def cmd_video(args: argparse.Namespace) -> int:
    specs = _select(args)
    if not specs:
        raise SystemExit("select --all or --book")
    for spec in specs:
        report = run_video(spec, limit_pages=args.limit_pages)
        print(
            f"  {spec.book_id}: scenes={report['scenes']} pages={report['pages']} "
            f"total={report['total_ms']}ms errors={len(report['errors'])} "
            f"{report['seconds']}s -> {report['book_video']}"
        )
    return 0


def cmd_tts(args: argparse.Namespace) -> int:
    specs = _select(args)
    if not specs:
        raise SystemExit("select --all or --book")
    for spec in specs:
        report = run_tts(spec)
        if not report["available"]:
            print(f"  {spec.book_id}: edge-tts not installed; narration stays in the subtitles")
            continue
        print(
            f"  {spec.book_id}: files={len(report['files'])} errors={len(report['errors'])} "
            f"{report['seconds']}s"
        )
    return 0


def cmd_models(_args: argparse.Namespace) -> int:
    print(f"config: {config_path()}")
    print(f"ocr provider: {build_ocr().name}")
    print(f"vlm provider: {build_vlm().name}")
    for item in provider_status():
        state = "available" if item.available else "unavailable"
        print(f"  {item.kind}: {item.provider} -> {state} {item.detail}".rstrip())
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

    p_understand = sub.add_parser("understand", help="OCR pass; fills text from page images")
    add_selection(p_understand)
    p_understand.set_defaults(func=cmd_understand)

    p_narrative = sub.add_parser("narrative", help="VLM page narrative; requires a configured VLM")
    add_selection(p_narrative)
    p_narrative.set_defaults(func=cmd_narrative)

    p_review = sub.add_parser("review", help="render a page with PDF/OCR boxes for visual review")
    add_selection(p_review)
    p_review.add_argument("--page", type=int, required=True)
    p_review.add_argument("--target", help="highlight blocks containing this text")
    p_review.add_argument("--out", help="output PNG path")
    p_review.set_defaults(func=cmd_review)

    p_manual = sub.add_parser("manual", help="seed the human correction file for a book")
    add_selection(p_manual)
    p_manual.set_defaults(func=cmd_manual)

    p_check = sub.add_parser("vlm-check", help="send one page to the VLM and print the answer")
    add_selection(p_check)
    p_check.add_argument("--page", type=int, help="page index (default: first page)")
    p_check.add_argument("--prompt", help="override the test prompt")
    p_check.set_defaults(func=cmd_vlm_check)

    p_story = sub.add_parser("story", help="BookPackage + narratives -> StoryPlan")
    add_selection(p_story)
    p_story.set_defaults(func=cmd_story)

    p_scene = sub.add_parser("scene", help="StoryPlan -> ScenePlan + timeline")
    add_selection(p_scene)
    p_scene.set_defaults(func=cmd_scene)

    p_index = sub.add_parser("index", help="build the search index and the scene index")
    add_selection(p_index)
    p_index.set_defaults(func=cmd_index)

    p_video = sub.add_parser("video", help="ScenePlan -> page animations + book video")
    add_selection(p_video)
    p_video.add_argument("--limit-pages", type=int, help="only render up to this page")
    p_video.set_defaults(func=cmd_video)

    p_tts = sub.add_parser("tts", help="narration audio via Edge TTS (optional)")
    add_selection(p_tts)
    p_tts.set_defaults(func=cmd_tts)

    p_models = sub.add_parser("models", help="show configured OCR/VLM providers")
    p_models.set_defaults(func=cmd_models)

    p_validate = sub.add_parser("validate", help="validate every book.json and query set")
    p_validate.set_defaults(func=cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

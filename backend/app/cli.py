from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.archive import ArchiveIndex
from backend.app.ingest import ingest_book
from backend.app.script_parser import parse_script
from backend.app.store import BookStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest an official picture-book archive")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--book", help="Book key such as 中文绘本01")
    parser.add_argument("--output", type=Path, default=Path("temp/books"))
    parser.add_argument("--scale", type=float, default=2.0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--books-root", type=Path, default=Path("temp/books"))
    parser.add_argument("--validate", metavar="BOOK_ID")
    parser.add_argument("--migrate", metavar="BOOK_ID")
    parser.add_argument("--list", action="store_true", help="List books in the archive")
    parser.add_argument(
        "--inspect-all",
        action="store_true",
        help="Validate scripts and audio mappings for every book",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.validate:
        errors = BookStore(args.books_root).validate(args.validate)
        print(json.dumps({"book_id": args.validate, "errors": errors}, ensure_ascii=False))
        if errors:
            raise SystemExit(1)
        return
    if args.migrate:
        changed = BookStore(args.books_root).migrate(args.migrate)
        print(json.dumps({"book_id": args.migrate, "changed": changed}, ensure_ascii=False))
        return
    if not args.archive:
        raise SystemExit("--archive is required unless --validate or --migrate is used")
    archive = ArchiveIndex.load(args.archive)
    if args.list:
        print(json.dumps(archive.list_books(), ensure_ascii=False, indent=2))
        return
    if args.inspect_all:
        reports = []
        for book_key in archive.list_books():
            _, script_name, audio_directory = archive.find_book_files(book_key)
            steps = parse_script(archive.read(script_name).decode("utf-8-sig"))
            audio = archive.audio_entries(audio_directory)
            reports.append(
                {
                    "book": book_key,
                    "steps": len(steps),
                    "audio": len(audio),
                    "missingAudio": [
                        step.number
                        for step in steps
                        if step.number not in {number for number, _, _ in audio}
                    ],
                    "mandatorySteps": [
                        step.number for step in steps if step.mandatory
                    ],
                    "clickTargets": sorted(
                        {
                            action.target
                            for step in steps
                            for action in step.actions
                            if action.type == "click" and action.target
                        }
                    ),
                }
            )
        print(json.dumps(reports, ensure_ascii=False, indent=2))
        return
    if not args.book:
        raise SystemExit(
            "--book is required unless --list or --inspect-all is used"
        )
    output = ingest_book(
        args.archive,
        args.book,
        args.output,
        render_scale=args.scale,
        force=args.force,
    )
    print(output.resolve())


if __name__ == "__main__":
    main()


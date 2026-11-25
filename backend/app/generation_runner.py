from __future__ import annotations

import json
from pathlib import Path

from pipeline.config import DATA, BookSpec, find_book
from pipeline.orchestrator import RunReport, run_book

from backend.app.jobs import ProgressReporter


class PipelineGenerationRunner:
    """Delegate the generation job to the deterministic agent DAG.

    The Job/API shape stays A's: `progress` is still `(JobStage, fraction)`.
    """

    def run(self, book_id: str, report: ProgressReporter) -> RunReport:
        spec = resolve_book_spec(book_id)
        return run_book(spec, progress=report)


def resolve_book_spec(book_id: str) -> BookSpec:
    try:
        return find_book(book_id)
    except KeyError:
        pass

    book_path = DATA / book_id / "book.json"
    if not book_path.is_file():
        raise FileNotFoundError(book_path)

    data = json.loads(book_path.read_text(encoding="utf-8"))
    language = str(data.get("language") or "zh-CN")
    title = str(data.get("title") or data.get("source_name") or book_id)
    content_type = str(data.get("content_type") or "narrative")

    return BookSpec(
        book_id=book_id,
        pdf_name="",
        audio_dir="",
        script_name="",
        language=language,
        content_type=content_type,
        source_name=title,
    )
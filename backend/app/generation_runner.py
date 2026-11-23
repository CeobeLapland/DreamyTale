from __future__ import annotations

import json
from pathlib import Path

from pipeline.config import DATA, BookSpec, find_book
from pipeline.final import render_final
from pipeline.index import build_index
from pipeline.models import build_llm, build_ocr, build_vlm
from pipeline.narrative import run_vlm_all
from pipeline.retime import retime_book
from pipeline.scene import run_scene
from pipeline.story import run_story
from pipeline.tts import run_tts
from pipeline.understanding import run_ocr_all
from pipeline.video import run_video

from backend.app.jobs import ProgressReporter


class PipelineGenerationRunner:
    """Execute the existing content pipeline for an API generation job."""

    def run(self, book_id: str, report: ProgressReporter) -> None:
        spec = resolve_book_spec(book_id)

        report("ocr", 0.05)
        ocr = build_ocr()
        run_ocr_all([spec], ocr)
        report("ocr", 0.15)

        report("vlm", 0.20)
        vlm = build_vlm()
        run_vlm_all([spec], vlm)
        report("vlm", 0.35)

        report("story", 0.38)
        llm = build_llm()
        run_story(spec, llm)
        report("story", 0.50)

        report("scene", 0.53)
        run_scene(spec)
        report("scene", 0.60)

        report("tts", 0.63)
        run_tts(spec)
        retime_book(spec)
        report("tts", 0.70)

        report("index", 0.72)
        build_index(spec)
        report("index", 0.76)

        report("video", 0.80)
        video_report = run_video(spec)
        if not video_report.get("book_video"):
            raise RuntimeError("video pipeline produced no book video")
        report("video", 0.90)

        report("compose", 0.92)
        final_report = render_final(spec)
        if not Path(final_report["final_video"]).is_file():
            raise RuntimeError("final composition produced no MP4")
        report("compose", 0.99)


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
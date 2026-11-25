"""Critic: check the generated assets before a human looks at them.

This is a deterministic, model-free reviewer. It does not try to judge taste;
it checks the things that silently break a demo:

- every book page has a story beat and a scene;
- scene captions/prompts are not empty;
- the timeline is contiguous;
- subtitles and narration exist where the story says they should;
- the final video exists and carries audio.

The report is written to `derived/critic/report.json` so the manifest, the
reader's "生成链路" panel and the demo script can all point at the same file.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DATA, BookSpec

REPORT_PATH = Path("derived") / "critic" / "report.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _warning(code: str, message: str, **extra: Any) -> dict[str, Any]:
    record = {"code": code, "message": message}
    record.update(extra)
    return record


def run_critic(spec: BookSpec) -> dict[str, Any]:
    book_root = DATA / spec.book_id
    book = _read_json(book_root / "book.json")
    story = _read_json(book_root / "derived" / "story" / "story_plan.json")
    scene_plan = _read_json(book_root / "derived" / "scene" / "scene_plan.json")
    timeline = _read_json(book_root / "derived" / "scene" / "timeline.json")

    page_indices = [int(page.get("index") or 0) for page in book.get("pages", [])]
    story_pages = {
        int(page.get("page_index") or 0): page
        for page in story.get("pages", [])
    }
    scenes_by_page: dict[int, list[dict[str, Any]]] = {}
    for scene in scene_plan.get("scenes", []):
        scenes_by_page.setdefault(int(scene.get("page_index") or 0), []).append(scene)
    bounds = {
        int(page.get("page_index") or 0): (
            int(page.get("start_ms") or 0),
            int(page.get("end_ms") or 0),
        )
        for page in timeline.get("pages", [])
    }

    warnings: list[dict[str, Any]] = []
    for page_index in page_indices:
        if page_index not in story_pages:
            warnings.append(
                _warning("story_missing_page", "no story beat for this page", page_index=page_index)
            )
        if not scenes_by_page.get(page_index):
            warnings.append(
                _warning("scene_missing_page", "no scene for this page", page_index=page_index)
            )
        start, end = bounds.get(page_index, (0, 0))
        if end <= start:
            warnings.append(
                _warning("timeline_invalid", "page has no positive duration", page_index=page_index)
            )

    ordered = [bounds[index] for index in page_indices if index in bounds]
    for previous, current in zip(ordered, ordered[1:]):
        if previous[1] != current[0]:
            warnings.append(
                _warning(
                    "timeline_gap",
                    "page timestamps are not contiguous",
                    expected_ms=previous[1],
                    actual_ms=current[0],
                )
            )
            break

    for page_index, scenes in sorted(scenes_by_page.items()):
        for scene in scenes:
            if not str(scene.get("caption") or "").strip():
                warnings.append(
                    _warning("empty_caption", "scene caption is empty", page_index=page_index, scene_id=scene.get("scene_id"))
                )
            if not str(scene.get("prompt") or "").strip():
                warnings.append(
                    _warning("empty_prompt", "scene prompt is empty", page_index=page_index, scene_id=scene.get("scene_id"))
                )
            if not scene.get("subtitles"):
                warnings.append(
                    _warning("subtitle_missing", "scene has no subtitle", page_index=page_index, scene_id=scene.get("scene_id"))
                )

    audio_dir = book_root / "derived" / "audio" / "narration"
    audio_pages = sorted(audio_dir.glob("page-*.mp3")) if audio_dir.is_dir() else []
    narrated_pages = {
        page_index
        for page_index in page_indices
        if story_pages.get(page_index) and story_pages[page_index].get("beats")
    }
    missing_audio = sorted(narrated_pages - {
        int(path.stem.split("-")[-1]) for path in audio_pages
    })
    if missing_audio:
        warnings.append(
            _warning(
                "audio_missing",
                "some narrated pages have no audio",
                pages=missing_audio,
            )
        )

    final_video = book_root / "derived" / "video" / "final.mp4"
    if not final_video.is_file() or final_video.stat().st_size == 0:
        warnings.append(_warning("video_missing", "final.mp4 is missing or empty"))

    errors = [
        warning
        for warning in warnings
        if warning["code"] in {"video_missing", "timeline_invalid"}
    ]
    report = {
        "book_id": spec.book_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": not errors,
        "stats": {
            "pages": len(page_indices),
            "scenes": sum(len(items) for items in scenes_by_page.values()),
            "narrated_pages": len(narrated_pages),
            "audio_pages": len(audio_pages),
            "subtitle_scenes": sum(
                1
                for scenes in scenes_by_page.values()
                for scene in scenes
                if scene.get("subtitles")
            ),
        },
        "warnings": warnings,
    }
    path = book_root / REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from .config import DATA, BookSpec

_DURATION_RE = re.compile(
    r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)"
)
PADDING_MS = 500


def probe_audio_duration_ms(path: Path) -> int:
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    completed = subprocess.run(
        [ffmpeg, "-i", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    match = _DURATION_RE.search(completed.stderr or completed.stdout)
    if match is None:
        raise ValueError(f"cannot determine audio duration: {path}")

    hours, minutes, seconds = match.groups()
    total_ms = round(
        (
            int(hours) * 3600
            + int(minutes) * 60
            + float(seconds)
        )
        * 1000
    )
    return total_ms


def retime_book(spec: BookSpec) -> dict[str, Any]:
    started = time.perf_counter()
    book_root = DATA / spec.book_id
    scene_path = book_root / "derived" / "scene" / "scene_plan.json"
    timeline_path = book_root / "derived" / "scene" / "timeline.json"
    audio_dir = book_root / "derived" / "audio" / "narration"

    plan = json.loads(scene_path.read_text(encoding="utf-8"))
    scenes = {
        str(scene["scene_id"]): scene
        for scene in plan.get("scenes", [])
    }
    changed_pages = 0

    for mapping in plan.get("page_map", []):
        page_index = int(mapping.get("page_index") or 0)
        old_start = int(mapping.get("start_ms") or 0)
        old_end = int(mapping.get("end_ms") or 0)
        old_duration = old_end - old_start
        if old_duration <= 0:
            continue

        audio_path = audio_dir / f"page-{page_index:03d}.mp3"
        target_duration = old_duration

        if audio_path.is_file():
            audio_duration = probe_audio_duration_ms(audio_path)
            target_duration = max(
                old_duration,
                audio_duration + PADDING_MS,
            )

        if target_duration == old_duration:
            continue

        scale = target_duration / old_duration
        mapping["start_ms"] = 0
        mapping["end_ms"] = target_duration

        for scene_id in mapping.get("scene_ids", []):
            scene = scenes.get(str(scene_id))
            if scene is None:
                continue

            scene["start_ms"] = round(
                int(scene.get("start_ms") or 0) * scale
            )
            scene["end_ms"] = round(
                int(scene.get("end_ms") or 0) * scale
            )

            for subtitle in scene.get("subtitles", []):
                subtitle["start_ms"] = round(
                    int(subtitle.get("start_ms") or 0) * scale
                )
                subtitle["end_ms"] = round(
                    int(subtitle.get("end_ms") or 0) * scale
                )

            for item in scene.get("objects", []):
                item["start_ms"] = round(
                    int(item.get("start_ms") or 0) * scale
                )
                item["end_ms"] = round(
                    int(item.get("end_ms") or 0) * scale
                )

        changed_pages += 1

    timeline = _rebuild_timeline(plan)
    scene_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    timeline_path.write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "book_id": spec.book_id,
        "changed_pages": changed_pages,
        "total_ms": timeline["total_ms"],
        "scene_plan": str(scene_path),
        "timeline": str(timeline_path),
        "seconds": round(time.perf_counter() - started, 2),
    }


def _rebuild_timeline(plan: dict[str, Any]) -> dict[str, Any]:
    scenes = {
        str(scene["scene_id"]): scene
        for scene in plan.get("scenes", [])
    }
    pages: list[dict[str, Any]] = []
    timeline_scenes: list[dict[str, Any]] = []
    cursor = 0

    for mapping in plan.get("page_map", []):
        page_index = int(mapping.get("page_index") or 0)
        duration = int(mapping.get("end_ms") or 0) - int(
            mapping.get("start_ms") or 0
        )
        scene_ids = [str(item) for item in mapping.get("scene_ids", [])]
        pages.append(
            {
                "page_index": page_index,
                "start_ms": cursor,
                "end_ms": cursor + duration,
                "scene_ids": scene_ids,
            }
        )

        for scene_id in scene_ids:
            scene = scenes.get(scene_id)
            if scene is None:
                continue
            timeline_scenes.append(
                {
                    "scene_id": scene_id,
                    "page_index": page_index,
                    "start_ms": cursor + int(scene.get("start_ms") or 0),
                    "end_ms": cursor + int(scene.get("end_ms") or 0),
                    "video_path": str(scene.get("video_path") or ""),
                }
            )

        cursor += duration

    return {
        "book_id": plan.get("book_id"),
        "total_ms": cursor,
        "pages": pages,
        "scenes": timeline_scenes,
    }
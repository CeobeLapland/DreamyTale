from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from .config import DATA, BookSpec
from .video import _ascii_temp_root, _ascii_video_input


def render_final(spec: BookSpec) -> dict[str, Any]:
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw

    book_root = DATA / spec.book_id
    source_video = book_root / "derived" / "video" / "book.mp4"
    scene_plan_path = book_root / "derived" / "scene" / "scene_plan.json"
    timeline_path = book_root / "derived" / "scene" / "timeline.json"

    if not source_video.is_file():
        raise FileNotFoundError(source_video)
    if not scene_plan_path.is_file():
        raise FileNotFoundError(scene_plan_path)
    if not timeline_path.is_file():
        raise FileNotFoundError(timeline_path)

    plan = json.loads(scene_plan_path.read_text(encoding="utf-8"))
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))

    page_bounds = {
        int(page["page_index"]): (
            int(page["start_ms"]),
            int(page["end_ms"]),
        )
        for page in timeline.get("pages", [])
    }

    subtitle_events: list[tuple[int, int, str]] = []
    for scene in plan.get("scenes", []):
        page_index = int(scene.get("page_index") or 0)
        if page_index not in page_bounds:
            continue
        page_start, _ = page_bounds[page_index]
        for item in scene.get("subtitles", []):
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            start_ms = page_start + int(item.get("start_ms") or 0)
            end_ms = page_start + int(item.get("end_ms") or 0)
            if end_ms > start_ms:
                subtitle_events.append((start_ms, end_ms, text))
    subtitle_events.sort(key=lambda item: item[0])

    audio_events = _audio_events(book_root, page_bounds)
    temp_root = _ascii_temp_root()
    visual_temp = temp_root / f"{uuid.uuid4().hex}-visual.mp4"
    final_temp = temp_root / f"{uuid.uuid4().hex}-final.mp4"
    srt_path = book_root / "derived" / "video" / "subtitles.srt"
    final_path = book_root / "derived" / "video" / "final.mp4"

    try:
        font = _load_font(30)

        with _ascii_video_input(source_video) as readable:
            capture = cv2.VideoCapture(str(readable))
            if not capture.isOpened():
                raise RuntimeError(f"cannot open video: {source_video}")

            fps = capture.get(cv2.CAP_PROP_FPS) or 12
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            writer = cv2.VideoWriter(
                str(visual_temp),
                cv2.VideoWriter_fourcc(*"mp4v"),
                fps,
                (width, height),
            )
            if not writer.isOpened():
                capture.release()
                raise RuntimeError("cannot open subtitle video writer")

            frame_index = 0
            try:
                while True:
                    ok, frame = capture.read()
                    if not ok:
                        break
                    current_ms = int(frame_index / fps * 1000)
                    text = _subtitle_at(subtitle_events, current_ms)
                    if text:
                        frame = _draw_subtitle(
                            frame,
                            text,
                            font,
                            np,
                            Image,
                            ImageDraw,
                        )
                    writer.write(frame)
                    frame_index += 1
            finally:
                writer.release()
                capture.release()

        _write_srt(srt_path, subtitle_events)
        _mux_audio(
            visual_temp,
            final_temp,
            audio_events,
            page_bounds,
        )
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(final_temp, final_path)
        _update_generation_result(
            book_root / "derived" / "generation_result.json",
            final_path,
            srt_path,
            book_root,
        )

        return {
            "book_id": spec.book_id,
            "final_video": str(final_path),
            "subtitle_path": str(srt_path),
            "audio_pages": len(audio_events),
            "subtitle_entries": len(subtitle_events),
            "frames": frame_index,
        }
    finally:
        visual_temp.unlink(missing_ok=True)
        final_temp.unlink(missing_ok=True)


def _audio_events(
    book_root: Path,
    page_bounds: dict[int, tuple[int, int]],
) -> list[tuple[int, int, Path]]:
    audio_dir = book_root / "derived" / "audio" / "narration"
    result: list[tuple[int, int, Path]] = []
    for page_index, (start_ms, end_ms) in sorted(page_bounds.items()):
        path = audio_dir / f"page-{page_index:03d}.mp3"
        if path.is_file():
            result.append((start_ms, end_ms, path))
    return result


def _mux_audio(
    video_path: Path,
    output_path: Path,
    audio_events: list[tuple[int, int, Path]],
    page_bounds: dict[int, tuple[int, int]],
) -> None:
    if not audio_events:
        shutil.copyfile(video_path, output_path)
        return

    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    args = [ffmpeg, "-y", "-i", str(video_path)]
    filters = []
    labels = []

    for index, (start_ms, end_ms, audio_path) in enumerate(audio_events):
        args.extend(["-i", str(audio_path)])
        duration = max(0.1, (end_ms - start_ms) / 1000)
        filters.append(
            f"[{index + 1}:a]"
            f"atrim=duration={duration},"
            "asetpts=PTS-STARTPTS,"
            f"apad=pad_dur={duration},"
            f"adelay=delays={start_ms}:all=1"
            f"[a{index}]"
        )
        labels.append(f"[a{index}]")

    filters.append(
        "".join(labels)
        + f"amix=inputs={len(labels)}:duration=longest:normalize=0[aout]"
    )

    args.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(output_path),
        ]
    )
    completed = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "ffmpeg audio mux failed: "
            + (completed.stderr or completed.stdout)[-3000:]
        )


def _subtitle_at(
    events: list[tuple[int, int, str]],
    current_ms: int,
) -> str | None:
    for start_ms, end_ms, text in events:
        if start_ms <= current_ms < end_ms:
            return text
    return None


def _draw_subtitle(
    frame,
    text: str,
    font,
    np,
    Image,
    ImageDraw,
):
    import cv2

    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image, "RGBA")
    max_chars = max(12, int(image.width / 34))
    lines = _wrap_text(text, max_chars)
    bbox = draw.multiline_textbbox((0, 0), "\n".join(lines), font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = max(20, (image.width - text_width) // 2)
    y = image.height - text_height - 55

    draw.rectangle(
        (
            x - 18,
            y - 14,
            x + text_width + 18,
            y + text_height + 14,
        ),
        fill=(0, 0, 0, 170),
    )
    draw.multiline_text(
        (x, y),
        "\n".join(lines),
        font=font,
        fill=(255, 255, 255, 255),
        align="center",
        spacing=6,
    )
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def _wrap_text(text: str, max_chars: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        while len(paragraph) > max_chars:
            lines.append(paragraph[:max_chars])
            paragraph = paragraph[max_chars:]
        if paragraph:
            lines.append(paragraph)
    return lines or [text]


def _load_font(size: int):
    from PIL import ImageFont

    candidates = [
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
    ]
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _write_srt(path: Path, events: list[tuple[int, int, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = []
    for index, (start_ms, end_ms, text) in enumerate(events, start=1):
        blocks.append(
            f"{index}\n"
            f"{_srt_time(start_ms)} --> {_srt_time(end_ms)}\n"
            f"{text}\n"
        )
    path.write_text("\n".join(blocks), encoding="utf-8-sig")


def _srt_time(milliseconds: int) -> str:
    milliseconds = max(0, milliseconds)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _update_generation_result(
    path: Path,
    final_video: Path,
    subtitle_path: Path,
    book_root: Path,
) -> None:
    if not path.is_file():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    data["full_video_path"] = str(
        final_video.relative_to(book_root)
    ).replace("\\", "/")
    data["subtitle_paths"] = [
        str(subtitle_path.relative_to(book_root)).replace("\\", "/")
    ]
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

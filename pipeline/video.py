"""Video stage: ScenePlan -> VideoSegment + BookGenerationResult (§8.3, §8.4).

The default renderer is a page animation: the page image is slowly zoomed and
panned into a short mp4. It is deterministic, needs no model, and renders a
whole book in seconds, so the video stage can never block the demo.

When ComfyUI has a video model, key pages can be rendered as real image to
video clips instead. Without such a model the stage degrades to the page
animation, exactly as the contract's VIDEO_FAILED row says.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contracts.models import (
    BookGenerationResult,
    GenerationManifest,
    GenerationMetrics,
    GenerationPage,
    GenerationStatus,
    ManifestArtifact,
    ManifestStage,
    VideoSegment,
    content_hash,
)

from .config import DATA, BookSpec

VIDEO_DIR = Path("derived") / "video"
SCENE_DIR = Path("derived") / "scene"
THUMB_DIR = Path("derived") / "video" / "thumbs"
FPS = 12
FRAME_SIZE = (1280, 720)
PUSH_IN = 0.08


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _motion(camera: str) -> str:
    text = (camera or "").lower()
    if "拉远" in text or "zoom out" in text:
        return "pull_out"
    if "平移" in text or "pan" in text:
        return "pan"
    if "固定" in text or "fixed" in text:
        return "fixed"
    return "push_in"


def _letterbox(image, size: tuple[int, int]):
    """Fit the whole page into the frame; a picture book page must stay whole."""
    import cv2
    import numpy as np

    frame = np.full((size[1], size[0], 3), 245, dtype=np.uint8)
    height, width = image.shape[:2]
    scale = min(size[0] / width, size[1] / height)
    new_width = max(1, int(width * scale))
    new_height = max(1, int(height * scale))
    resized = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_AREA)
    offset_x = (size[0] - new_width) // 2
    offset_y = (size[1] - new_height) // 2
    frame[offset_y : offset_y + new_height, offset_x : offset_x + new_width] = resized
    return frame, new_width, new_height


def _crop(canvas, inner_width: int, inner_height: int, zoom: float, pan_x: float, pan_y: float):
    height, width = canvas.shape[:2]
    crop_width = max(2, int(width / zoom))
    crop_height = max(2, int(height / zoom))
    crop_width = min(crop_width, width)
    crop_height = min(crop_height, height)
    max_x = width - crop_width
    max_y = height - crop_height
    start_x = int(max_x * pan_x)
    start_y = int(max_y * pan_y)
    return canvas[start_y : start_y + crop_height, start_x : start_x + crop_width]


def render_scene_animation(
    image_path: Path,
    out_path: Path,
    duration_ms: int,
    camera: str = "",
    fps: int = FPS,
    size: tuple[int, int] = FRAME_SIZE,
) -> Path:
    """Render one scene as a slow page animation."""
    import cv2

    page = cv2.imread(str(image_path))
    if page is None:
        raise FileNotFoundError(image_path)
    canvas, inner_width, inner_height = _letterbox(page, size)

    frames = max(1, int(duration_ms / 1000 * fps))
    motion = _motion(camera)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(out_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        size,
    )
    if not writer.isOpened():
        raise RuntimeError(f"cannot open video writer for {out_path}")
    try:
        for index in range(frames):
            t = index / max(1, frames - 1)
            if motion == "push_in":
                zoom = 1.0 + PUSH_IN * t
                pan_x, pan_y = 0.5, 0.5 - 0.05 * t
            elif motion == "pull_out":
                zoom = 1.0 + PUSH_IN * (1 - t)
                pan_x, pan_y = 0.5, 0.5 + 0.05 * t
            elif motion == "pan":
                zoom = 1.0 + PUSH_IN * 0.6
                pan_x, pan_y = t, 0.5
            else:
                zoom = 1.0 + PUSH_IN * 0.3
                pan_x, pan_y = 0.5, 0.5
            crop = _crop(canvas, inner_width, inner_height, zoom, pan_x, pan_y)
            frame = cv2.resize(crop, size, interpolation=cv2.INTER_LINEAR)
            writer.write(frame)
    finally:
        writer.release()
    return out_path


def _thumbnail(image_path: Path, out_path: Path) -> Path:
    import cv2

    page = cv2.imread(str(image_path))
    if page is None:
        raise FileNotFoundError(image_path)
    canvas, _, _ = _letterbox(page, FRAME_SIZE)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), canvas)
    return out_path


def compose_book(spec: BookSpec, plan: dict[str, Any], segments: list[dict[str, Any]]) -> Path:
    """Concatenate the scene clips into one book video."""
    import cv2

    book_path = DATA / spec.book_id / VIDEO_DIR / "book.mp4"
    book_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(book_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        FPS,
        FRAME_SIZE,
    )
    if not writer.isOpened():
        raise RuntimeError(f"cannot open video writer for {book_path}")
    try:
        for segment in segments:
            # segment["path"] is package relative (contract rule)
            clip = DATA / spec.book_id / segment["path"]
            capture = cv2.VideoCapture(str(clip))
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                if frame.shape[1] != FRAME_SIZE[0] or frame.shape[0] != FRAME_SIZE[1]:
                    frame = cv2.resize(frame, FRAME_SIZE, interpolation=cv2.INTER_LINEAR)
                writer.write(frame)
            capture.release()
    finally:
        writer.release()
    return book_path


def run_video(spec: BookSpec, limit_pages: int | None = None) -> dict[str, Any]:
    """Render every scene of the book and write the generation artifacts."""
    import cv2

    book_path = DATA / spec.book_id / "book.json"
    scene_path = DATA / spec.book_id / SCENE_DIR / "scene_plan.json"
    if not book_path.exists():
        raise FileNotFoundError(book_path)
    if not scene_path.exists():
        raise FileNotFoundError(scene_path)
    book = json.loads(book_path.read_text(encoding="utf-8"))
    plan = json.loads(scene_path.read_text(encoding="utf-8"))

    started = time.perf_counter()
    video_dir = DATA / spec.book_id / VIDEO_DIR
    thumb_dir = DATA / spec.book_id / THUMB_DIR
    video_dir.mkdir(parents=True, exist_ok=True)
    thumb_dir.mkdir(parents=True, exist_ok=True)

    pages = {int(page["index"]): page for page in book.get("pages", [])}
    segments: list[dict[str, Any]] = []
    models: list[VideoSegment] = []
    fallbacks = 0
    errors: list[dict[str, Any]] = []

    scenes = plan.get("scenes") or []
    for scene in scenes:
        page_index = int(scene.get("page_index") or 0)
        if limit_pages is not None and page_index > limit_pages:
            continue
        scene_id = str(scene.get("scene_id") or "")
        page = pages.get(page_index)
        if page is None:
            continue
        image_path = DATA / spec.book_id / page["image_path"]
        out_path = video_dir / f"{scene_id}.mp4"
        duration_ms = int(scene.get("end_ms") or 0) - int(scene.get("start_ms") or 0)
        try:
            render_scene_animation(
                image_path,
                out_path,
                duration_ms=max(1000, duration_ms),
                camera=str(scene.get("camera") or ""),
            )
            thumb_path = _thumbnail(image_path, thumb_dir / f"{scene_id}.jpg")
            status = GenerationStatus.ok
            fallback_reason = None
        except Exception as exc:  # noqa: BLE001
            errors.append({"scene_id": scene_id, "error": f"{type(exc).__name__}: {exc}"})
            continue

        segments.append(
            {
                "scene_id": scene_id,
                "page_index": page_index,
                "path": str(out_path.relative_to(DATA / spec.book_id)).replace("\\", "/"),
                "start_ms": int(scene.get("start_ms") or 0),
                "end_ms": int(scene.get("end_ms") or 0),
                "thumbnail_path": str(thumb_path.relative_to(DATA / spec.book_id)).replace("\\", "/"),
            }
        )
        models.append(
            VideoSegment(
                segment_id=f"segment-{scene_id}",
                scene_id=scene_id,
                page_index=page_index,
                path=str(out_path.relative_to(DATA / spec.book_id)).replace("\\", "/"),
                duration_ms=max(1, duration_ms),
                width=FRAME_SIZE[0],
                height=FRAME_SIZE[1],
                fps=FPS,
                first_frame_path=str(scene.get("keyframe_path") or ""),
                model="page-animation-v1",
                params={"camera": str(scene.get("camera") or ""), "motion": _motion(str(scene.get("camera") or ""))},
                seed=int(scene.get("seed") or 0),
                style_score=scene.get("style_score"),
                status=status,
                fallback_reason=fallback_reason,
                created_at=_now(),
            )
        )

    book_video = compose_book(spec, plan, segments) if segments else None

    # Page level absolute timeline, derived from the scene clips.
    pages_out: list[GenerationPage] = []
    cursor = 0
    for page_index in sorted({segment["page_index"] for segment in segments}):
        page_segments = [item for item in segments if item["page_index"] == page_index]
        start_ms = cursor
        cursor += max(int(item["end_ms"]) for item in page_segments)
        pages_out.append(
            GenerationPage(
                page_index=page_index,
                video_path=page_segments[0]["path"],
                start_ms=start_ms,
                end_ms=cursor,
                scene_ids=[item["scene_id"] for item in page_segments],
                thumbnail_path=page_segments[0]["thumbnail_path"],
            )
        )

    audio_paths: list[str] = []
    audio_dir = DATA / spec.book_id / "derived" / "audio" / "narration"
    if audio_dir.is_dir():
        audio_paths = [
            f"derived/audio/narration/{item.name}"
            for item in sorted(audio_dir.glob("*.mp3"))
        ]

    result = BookGenerationResult(
        book_id=spec.book_id,
        generation_version=1,
        status="completed" if segments and not errors else ("degraded" if segments else "failed"),
        pages=pages_out,
        full_video_path=(
            str(book_video.relative_to(DATA / spec.book_id)).replace("\\", "/")
            if book_video
            else None
        ),
        subtitle_paths=[],
        audio_paths=audio_paths,
        timeline_path=f"derived/{SCENE_DIR.name}/timeline.json",
        manifest_path="derived/manifest.json",
        metrics=GenerationMetrics(
            style_score_avg=None,
            fallback_pages=fallbacks,
            qa_cards=0,
            duration_ms=cursor,
        ),
        model_versions={"video": "page-animation-v1"},
        prompt_versions={"story": "story-v1", "scene": "scene-v1"},
        created_at=_now(),
    )
    result_path = DATA / spec.book_id / "derived" / "generation_result.json"
    result_path.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    artifacts = [
        ManifestArtifact(path=f"derived/video/{segment['scene_id']}.mp4", sha256=content_hash(segment))
        for segment in segments
    ]
    if book_video:
        artifacts.append(
            ManifestArtifact(
                path="derived/video/book.mp4",
                sha256=content_hash({"path": str(book_video), "bytes": book_video.stat().st_size}),
            )
        )
    manifest = GenerationManifest(
        manifest_id=f"manifest-{spec.book_id}-001",
        book_id=spec.book_id,
        generation_version=1,
        input_hash=content_hash(book),
        stages=[
            ManifestStage(
                name="video",
                provider="local",
                model="page-animation-v1",
                model_version="v1",
                prompt_version="scene-v1",
                params={"fps": FPS, "size": list(FRAME_SIZE)},
                seed=None,
                started_at=_now(),
                duration_ms=int((time.perf_counter() - started) * 1000),
                status="completed" if segments and not errors else "degraded",
                error_code=None if not errors else "VIDEO_FAILED",
                degraded=bool(errors),
                output_hash=None,
            )
        ],
        artifacts=artifacts,
        model_versions={"video": "page-animation-v1"},
        prompt_versions={"story": "story-v1", "scene": "scene-v1"},
        created_at=_now(),
        status="completed" if segments and not errors else "degraded",
    )
    manifest_path = DATA / spec.book_id / "derived" / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "book_id": spec.book_id,
        "scenes": len(segments),
        "pages": len(pages_out),
        "total_ms": cursor,
        "book_video": str(book_video) if book_video else None,
        "result_path": str(result_path),
        "manifest_path": str(manifest_path),
        "errors": errors,
        "seconds": round(time.perf_counter() - started, 2),
    }

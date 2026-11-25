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
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
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
from .models import build_i2v, load_config
from .models.i2v import I2VRequest

VIDEO_DIR = Path("derived") / "video"
SCENE_DIR = Path("derived") / "scene"
THUMB_DIR = Path("derived") / "video" / "thumbs"
FPS = 12
FRAME_SIZE = (1280, 720)
PUSH_IN = 0.08

def _frame_size_for_book(book: dict[str, Any]) -> tuple[int, int]:
    ratios = []
    for page in book.get("pages", []):
        width = int(page.get("width_px") or 0)
        height = int(page.get("height_px") or 0)
        if width > 0 and height > 0:
            ratios.append(width / height)

    if not ratios:
        return FRAME_SIZE

    ratios.sort()
    median_ratio = ratios[len(ratios) // 2]

    if median_ratio > 1.05:
        return 1280, 720
    if median_ratio < 0.95:
        return 720, 1280
    return 1024, 1024


def _ascii_temp_root() -> Path:
    override = os.environ.get("DREAMYTALE_TMP_DIR")
    if override:
        root = Path(override).expanduser().resolve()
    elif os.name == "nt":
        drive = DATA.drive or Path.cwd().drive or "C:"
        root = Path(f"{drive}\\dreamytale-tmp")
    else:
        root = Path(tempfile.gettempdir()) / "dreamytale-tmp"

    root.mkdir(parents=True, exist_ok=True)
    return root


def ensure_h264(path: Path) -> bool:
    """Re-encode OpenCV's MPEG-4 Part 2 output to H.264.

    `cv2.VideoWriter` with the `mp4v` fourcc produces MPEG-4 Part 2, which
    Chromium refuses to play. Browsers only accept H.264 here, so every clip is
    remuxed with the bundled ffmpeg. If ffmpeg is missing the clip is kept as
    is: a degraded video is better than a failed stage.
    """
    try:
        import imageio_ffmpeg
    except ImportError:
        return False

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    temporary = path.with_name(f"{path.stem}-h264{path.suffix}")
    completed = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(temporary),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        temporary.unlink(missing_ok=True)
        return False
    os.replace(temporary, path)
    return True


@contextmanager
def _ascii_video_output(final_path: Path):
    temporary = _ascii_temp_root() / f"{uuid.uuid4().hex}{final_path.suffix}"
    try:
        yield temporary
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(temporary, final_path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _ascii_video_input(source_path: Path):
    temporary = _ascii_temp_root() / f"{uuid.uuid4().hex}{source_path.suffix}"
    shutil.copyfile(source_path, temporary)
    try:
        yield temporary
    finally:
        temporary.unlink(missing_ok=True)


def _imread_unicode(path: Path):
    import cv2
    import numpy as np

    data = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(path)
    return image


def _imwrite_unicode(path: Path, image) -> None:
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(path.suffix or ".png", image)
    if not ok:
        raise RuntimeError(f"cannot encode image for {path}")
    encoded.tofile(path)


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

    page = _imread_unicode(image_path)
    canvas, inner_width, inner_height = _letterbox(page, size)

    frames = max(1, int(duration_ms / 1000 * fps))
    motion = _motion(camera)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with _ascii_video_output(out_path) as temporary_output:
        writer = cv2.VideoWriter(
            str(temporary_output),
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

                crop = _crop(
                    canvas,
                    inner_width,
                    inner_height,
                    zoom,
                    pan_x,
                    pan_y,
                )
                frame = cv2.resize(
                    crop,
                    size,
                    interpolation=cv2.INTER_LINEAR,
                )
                writer.write(frame)
        finally:
            writer.release()

        ensure_h264(temporary_output)

    return out_path


def _thumbnail(
    image_path: Path,
    out_path: Path,
    size: tuple[int, int] = FRAME_SIZE,
) -> Path:
    page = _imread_unicode(image_path)
    canvas, _, _ = _letterbox(page, size)
    _imwrite_unicode(out_path, canvas)
    return out_path


def compose_book(
    spec: BookSpec,
    plan: dict[str, Any],
    segments: list[dict[str, Any]],
    size: tuple[int, int] = FRAME_SIZE,
) -> Path:
    """Concatenate clips using scene durations and source fps."""
    import cv2

    book_path = DATA / spec.book_id / VIDEO_DIR / "book.mp4"

    with _ascii_video_output(book_path) as temporary_book:
        writer = cv2.VideoWriter(
            str(temporary_book),
            cv2.VideoWriter_fourcc(*"mp4v"),
            FPS,
            size,
        )
        if not writer.isOpened():
            raise RuntimeError(f"cannot open video writer for {book_path}")

        try:
            for segment in segments:
                clip = DATA / spec.book_id / segment["path"]
                target_frames = max(
                    1,
                    round(
                        (int(segment["end_ms"]) - int(segment["start_ms"]))
                        / 1000
                        * FPS
                    ),
                )

                with _ascii_video_input(clip) as temporary_clip:
                    capture = cv2.VideoCapture(str(temporary_clip))
                    if not capture.isOpened():
                        raise RuntimeError(f"cannot open clip: {clip}")

                    source_fps = capture.get(cv2.CAP_PROP_FPS) or FPS
                    source_index = 0
                    last_frame = None

                    try:
                        for target_index in range(target_frames):
                            desired_source_index = int(
                                target_index / FPS * source_fps
                            )
                            while source_index <= desired_source_index:
                                ok, frame = capture.read()
                                if not ok:
                                    break
                                last_frame = frame
                                source_index += 1

                            if last_frame is None:
                                raise RuntimeError(
                                    f"clip has no readable frames: {clip}"
                                )

                            output_frame = last_frame
                            if (
                                output_frame.shape[1] != size[0]
                                or output_frame.shape[0] != size[1]
                            ):
                                output_frame, _, _ = _letterbox(
                                    output_frame,
                                    size,
                                )
                            writer.write(output_frame)
                    finally:
                        capture.release()
        finally:
            writer.release()

        ensure_h264(temporary_book)

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
    frame_size = _frame_size_for_book(book)
    plan = json.loads(scene_path.read_text(encoding="utf-8"))
    config = load_config()
    i2v_config = config.get("i2v", {}) or {}
    i2v_provider = build_i2v(config)
    i2v_available = i2v_provider.available()
    i2v_scene_ids = {
        str(item)
        for item in i2v_config.get("scene_ids", []) or []
    }
    i2v_max_scenes = max(
        0,
        int(i2v_config.get("max_scenes") or 0),
    )
    i2v_used = 0
    used_video_models: set[str] = set()

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
        use_i2v = i2v_available and (
            scene_id in i2v_scene_ids
            if i2v_scene_ids
            else i2v_used < i2v_max_scenes
        )
        model_name = "page-animation-v1"
        status = GenerationStatus.ok
        fallback_reason = None
        i2v_failed = False

        try:
            if use_i2v:
                try:
                    i2v_provider.generate(
                        I2VRequest(
                            image_path=image_path,
                            prompt=str(
                                scene.get("prompt")
                                or scene.get("caption")
                                or "人物轻微动作，保持原书风格"
                            ),
                            negative_prompt=str(
                                scene.get("negative_prompt")
                                or "角色变形，额外肢体，文字变化"
                            ),
                            duration_ms=max(1000, duration_ms),
                            seed=int(scene.get("seed") or 0),
                            width=frame_size[0],
                            height=frame_size[1],
                            fps=FPS,
                        ),
                        out_path,
                    )
                    model_name = i2v_provider.name
                    i2v_used += 1
                except Exception as exc:  # noqa: BLE001
                    i2v_failed = True
                    status = GenerationStatus.fallback
                    fallback_reason = (
                        f"I2V failed: {type(exc).__name__}: {exc}"
                    )

            if model_name == "page-animation-v1":
                render_scene_animation(
                    image_path,
                    out_path,
                    duration_ms=max(1000, duration_ms),
                    camera=str(scene.get("camera") or ""),
                    size=frame_size,
                )

            thumb_path = _thumbnail(
                image_path,
                thumb_dir / f"{scene_id}.jpg",
                size=frame_size,
            )
            used_video_models.add(model_name)
            if i2v_failed:
                fallbacks += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(
                {
                    "scene_id": scene_id,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
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
                width=frame_size[0],
                height=frame_size[1],
                fps=FPS,
                first_frame_path=str(scene.get("keyframe_path") or ""),
                model=model_name,
                params={
                    "camera": str(scene.get("camera") or ""),
                    "motion": _motion(str(scene.get("camera") or "")),
                    "fallback_reason": fallback_reason,
                },
                seed=int(scene.get("seed") or 0),
                style_score=scene.get("style_score"),
                status=status,
                fallback_reason=fallback_reason,
                created_at=_now(),
            )
        )

    book_video = compose_book(spec, plan, segments, size=frame_size) if segments else None

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

    if not used_video_models:
        used_video_models.add("page-animation-v1")

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
        model_versions={"video": ",".join(sorted(used_video_models))},
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
                provider=i2v_provider.name if i2v_used else "local",
                model=",".join(sorted(used_video_models)),
                model_version="v1",
                prompt_version="scene-v1",
                params={
                    "fps": FPS,
                    "size": list(frame_size),
                    "i2v_scenes": i2v_used,
                    "page_animation_scenes": max(0, len(segments) - i2v_used),
                    "i2v_fallbacks": fallbacks,
                },
                seed=None,
                started_at=_now(),
                duration_ms=int((time.perf_counter() - started) * 1000),
                status="completed" if segments and not errors else "degraded",
                error_code=(
                    "VIDEO_FAILED"
                    if errors
                    else ("I2V_FALLBACK" if fallbacks else None)
                ),
                degraded=bool(errors or fallbacks),
                output_hash=None,
            )
        ],
        artifacts=artifacts,
        model_versions={"video": ",".join(sorted(used_video_models))},
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
        "i2v_scenes": i2v_used,
        "fallback_scenes": fallbacks,
        "errors": errors,
        "seconds": round(time.perf_counter() - started, 2),
    }

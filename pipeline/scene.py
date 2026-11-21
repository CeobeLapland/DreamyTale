"""Scene stage: StoryPlan -> ScenePlan (DATA_CONTRACT §8.2).

Deterministic on purpose. The story model already wrote the narration; the
scene stage only has to turn beats into timed, searchable, generatable units:

  * one scene per beat, time relative to its own page;
  * aliases that make `seek` work (the query text is matched against them);
  * subtitles from the narration (this is what `search` and `highlight` hit);
  * objects from the page hotspots (this is what `click` hits);
  * a video prompt built from the style bible, so every page looks alike.

No model call here means the stage is reproducible and never blocks the video
stage; the contract fallback (SCENE_FAILED -> 每页一个 scene) is the same code
path with fewer beats.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contracts.models import (
    BookPackage,
    PageMap,
    Scene,
    SceneObject,
    ScenePlan,
    StoryPlan,
    Subtitle,
    content_hash,
)

from .config import DATA, BookSpec

PROMPT_VERSION = "scene-v1"

CAMERA_MOVES = (
    "从左侧缓慢推近到画面中心",
    "轻微拉远展示全貌",
    "平移跟随画面里的角色",
    "固定镜头，保留绘本纸面质感",
)

_SPLIT_CHARS = "，。！？；、,.!?;:\"“”‘’（）()《》<>—…· "


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _seed_for(scene_id: str) -> int:
    digest = hashlib.sha256(scene_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _aliases(entities: list[str], caption: str, narration: str, keywords: list[str] | None = None) -> list[str]:
    """Short phrases a user might say when asking to jump to this moment."""
    aliases: list[str] = []

    def add(value: str) -> None:
        text = value.strip()
        if text and text not in aliases and len(text) <= 24:
            aliases.append(text)

    for keyword in keywords or []:
        add(str(keyword))
    for entity in entities:
        add(entity)
    for source in (caption, narration):
        for fragment in _split(source):
            add(fragment)
    if not aliases:
        add(caption[:16] or "画面")
    return aliases[:6]


def _split(text: str) -> list[str]:
    parts: list[str] = []
    buffer = ""
    for char in text:
        if char in _SPLIT_CHARS:
            if 2 <= len(buffer) <= 16:
                parts.append(buffer)
            buffer = ""
            continue
        buffer += char
    if 2 <= len(buffer) <= 16:
        parts.append(buffer)
    return parts


def _video_prompt(style_line: str, palette: list[str], texture: str, caption: str, entities: list[str]) -> str:
    parts = [style_line or "手绘水彩绘本风格", caption]
    if palette:
        parts.append("配色 " + "、".join(palette[:3]))
    if texture:
        parts.append(texture)
    if entities:
        parts.append("画面里有 " + "、".join(entities[:4]))
    prompt = "，".join(part.strip("，。！？；、,. ") for part in parts if part)
    return prompt[:200]


def build_scene_plan(
    book: BookPackage,
    story: StoryPlan,
    plan_version: int = 1,
    keywords: dict[str, list[str]] | None = None,
) -> ScenePlan:
    scenes: list[Scene] = []
    page_map: list[PageMap] = []
    pages_by_index = {page.index: page for page in book.pages}
    keyword_map = keywords or {}

    for page_story in story.pages:
        page = pages_by_index.get(page_story.page_index)
        cursor = 0
        scene_ids: list[str] = []
        for index, beat in enumerate(page_story.beats, start=1):
            scene_id = (
                f"scene-{book.book_id}-{page_story.page_index:03d}"
                if len(page_story.beats) == 1
                else f"scene-{book.book_id}-{page_story.page_index:03d}-{index:02d}"
            )
            start_ms = cursor
            end_ms = cursor + beat.duration_ms
            cursor = end_ms
            caption = beat.description or beat.narration
            hotspots = list(page.hotspots) if page else []
            scenes.append(
                Scene(
                    scene_id=scene_id,
                    page_index=page_story.page_index,
                    beat_id=beat.beat_id,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    caption=caption,
                    aliases=_aliases(
                        beat.entities,
                        caption,
                        beat.narration,
                        keyword_map.get(beat.beat_id),
                    ),
                    entities=list(beat.entities),
                    action=beat.description,
                    camera=CAMERA_MOVES[(index - 1) % len(CAMERA_MOVES)],
                    prompt=_video_prompt(
                        story.style_bible.line,
                        list(story.style_bible.palette),
                        story.style_bible.texture or "",
                        caption,
                        list(beat.entities),
                    ),
                    negative_prompt="，".join(story.style_bible.negative_prompts),
                    keyframe_path=f"derived/scene/keyframes/{scene_id}.png",
                    video_path=f"derived/video/{scene_id}.mp4",
                    thumbnail_path=f"derived/video/thumbs/{scene_id}.jpg",
                    subtitles=[
                        Subtitle(
                            text=beat.narration,
                            start_ms=start_ms,
                            end_ms=end_ms,
                            lang=book.language,
                        )
                    ]
                    if beat.narration
                    else [],
                    objects=[
                        SceneObject(
                            entity=hotspot.label,
                            bbox_px=tuple(hotspot.bbox_px),
                            start_ms=start_ms,
                            end_ms=end_ms,
                        )
                        for hotspot in hotspots
                    ],
                    hotspot_ids=[hotspot.hotspot_id for hotspot in hotspots],
                    seed=_seed_for(scene_id),
                    style_score=None,
                    source="auto",
                    status="ok",
                )
            )
            scene_ids.append(scene_id)
        page_map.append(
            PageMap(
                page_index=page_story.page_index,
                scene_ids=scene_ids,
                start_ms=0,
                end_ms=cursor,
            )
        )

    return ScenePlan(
        book_id=book.book_id,
        plan_version=plan_version,
        page_map=page_map,
        scenes=scenes,
        model="deterministic",
        prompt_version=PROMPT_VERSION,
        source_hash=content_hash(story.model_dump(mode="json")),
        created_at=_now(),
    )


def build_timeline(book: BookPackage, plan: ScenePlan) -> dict[str, Any]:
    """Whole book timeline: page times are absolute, scene times are relative."""
    scenes_by_page: dict[int, list[Scene]] = {}
    for scene in plan.scenes:
        scenes_by_page.setdefault(scene.page_index, []).append(scene)

    pages: list[dict[str, Any]] = []
    timeline_scenes: list[dict[str, Any]] = []
    cursor = 0
    for mapping in plan.page_map:
        page_scenes = scenes_by_page.get(mapping.page_index, [])
        duration = mapping.end_ms - mapping.start_ms
        pages.append(
            {
                "page_index": mapping.page_index,
                "start_ms": cursor,
                "end_ms": cursor + duration,
                "scene_ids": list(mapping.scene_ids),
            }
        )
        for scene in page_scenes:
            timeline_scenes.append(
                {
                    "scene_id": scene.scene_id,
                    "page_index": scene.page_index,
                    "start_ms": cursor + scene.start_ms,
                    "end_ms": cursor + scene.end_ms,
                    "video_path": scene.video_path,
                }
            )
        cursor += duration
    return {
        "book_id": book.book_id,
        "total_ms": cursor,
        "pages": pages,
        "scenes": timeline_scenes,
    }


def run_scene(spec: BookSpec) -> dict[str, Any]:
    book_path = DATA / spec.book_id / "book.json"
    story_path = DATA / spec.book_id / "derived" / "story" / "story_plan.json"
    keyword_path = DATA / spec.book_id / "derived" / "story" / "beat_keywords.json"
    if not book_path.exists():
        raise FileNotFoundError(book_path)
    if not story_path.exists():
        raise FileNotFoundError(story_path)
    book = BookPackage.model_validate(json.loads(book_path.read_text(encoding="utf-8")))
    story = StoryPlan.model_validate(json.loads(story_path.read_text(encoding="utf-8")))
    keywords: dict[str, list[str]] = {}
    if keyword_path.is_file():
        try:
            raw = json.loads(keyword_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raw = {}
        if isinstance(raw, dict):
            keywords = {str(key): list(value) for key, value in raw.items() if isinstance(value, list)}

    plan = build_scene_plan(book, story, keywords=keywords)
    out_dir = DATA / spec.book_id / "derived" / "scene"
    out_dir.mkdir(parents=True, exist_ok=True)
    plan_path = out_dir / "scene_plan.json"
    plan_path.write_text(
        json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    timeline = build_timeline(book, plan)
    timeline_path = out_dir / "timeline.json"
    timeline_path.write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "book_id": spec.book_id,
        "scenes": len(plan.scenes),
        "pages": len(plan.page_map),
        "total_ms": timeline["total_ms"],
        "plan_path": str(plan_path),
        "timeline_path": str(timeline_path),
    }

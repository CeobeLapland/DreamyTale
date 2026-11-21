from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class TextSpan:
    span_id: str
    page_index: int
    text: str
    bbox_px: list[int]
    source: str


@dataclass(slots=True)
class Hotspot:
    hotspot_id: str
    page_index: int
    label: str
    bbox_px: list[int]
    description: str
    source: str


@dataclass(slots=True)
class ScriptAction:
    action_id: str
    type: str
    text: str
    mandatory: bool = False
    target: str | None = None


@dataclass(slots=True)
class ScriptStep:
    number: int
    instruction: str
    mandatory: bool
    actions: list[ScriptAction] = field(default_factory=list)
    audio_path: str | None = None


@dataclass(slots=True)
class Page:
    index: int
    image_path: str
    text: str
    text_source: str
    width_pt: float
    height_pt: float
    width_px: int
    height_px: int
    text_spans: list[TextSpan] = field(default_factory=list)
    hotspots: list[Hotspot] = field(default_factory=list)


@dataclass(slots=True)
class Scene:
    scene_id: str
    page_index: int
    start_ms: int
    end_ms: int
    caption: str
    aliases: list[str]
    video_path: str
    thumbnail_path: str
    hotspot_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BookPackage:
    schema_version: str
    book_id: str
    source_name: str
    title: str
    language: str
    pdf_path: str
    script_path: str
    page_count: int
    pages: list[Page]
    steps: list[ScriptStep]
    click_targets: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Job:
    job_id: str
    book_id: str
    status: str
    stage: str
    progress: float
    created_at: str
    updated_at: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class QARequest:
    book_id: str
    page_index: int
    current_time_ms: int
    hotspot_id: str | None = None
    question_text: str | None = None
    audio_path: str | None = None


@dataclass(slots=True)
class QAResponse:
    request_id: str
    answer_text: str
    page_index: int
    scene_id: str | None
    evidence_span_ids: list[str]
    answer_audio_path: str | None
    latency_ms: int
    status: str


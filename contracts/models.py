"""Core v2 contract models.

Coverage: BookPackage / Page / PageBlock / TextSpan / Hotspot / QuerySet (§1-§5),
knowledge (§6), human correction (§7), generation artifacts (§8), interaction (§9),
job (§10), capability report (§11) and evaluation (§12).

This module is the single source of truth. `docs/DATA_CONTRACT.md` describes the
same structures; `backend/`, `pipeline/` and the frontend types must agree with
both. Adding a field here means updating the doc in the same change.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "2.0.0"
BOOK_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
SHORT_HASH_RE = re.compile(r"^[a-f0-9]{16}$")


def content_hash(data: dict[str, Any]) -> str:
    """sha256 of canonical JSON, excluding the hash field itself, first 16 hex chars."""
    payload = {k: v for k, v in data.items() if k != "hash"}
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContentType(str, Enum):
    narrative = "narrative"
    expository = "expository"
    mixed = "mixed"


class SourceType(str, Enum):
    pdf = "pdf"
    photo = "photo"
    scan = "scan"
    mixed = "mixed"


class BookStatus(str, Enum):
    draft = "draft"
    ingested = "ingested"
    understood = "understood"
    generated = "generated"
    reviewed = "reviewed"
    ready = "ready"
    failed = "failed"


class TextSource(str, Enum):
    embedded_pdf = "embedded_pdf"
    ocr = "ocr"
    vlm = "vlm"
    manual = "manual"
    mixed = "mixed"
    none = "none"


class BlockType(str, Enum):
    title = "title"
    body = "body"
    caption = "caption"
    sfx = "sfx"
    note = "note"
    header = "header"
    footer = "footer"
    other = "other"


class SpanSource(str, Enum):
    embedded_pdf = "embedded_pdf"
    ocr = "ocr"
    vlm = "vlm"
    manual = "manual"


class HotspotSource(str, Enum):
    pdf_annotation = "pdf_annotation"
    vlm = "vlm"
    auto = "auto"
    manual = "manual"


class Status(str, Enum):
    active = "active"
    superseded = "superseded"


class QuerySetSource(str, Enum):
    official_script = "official_script"
    human = "human"
    auto = "auto"


class QueryLang(str, Enum):
    zh = "zh"
    en = "en"
    mixed = "mixed"


class QueryKind(str, Enum):
    control = "control"
    seek = "seek"
    search = "search"
    highlight = "highlight"
    click = "click"
    qa = "qa"


class ControlAction(str, Enum):
    play = "play"
    pause = "pause"
    resume = "resume"
    stop = "stop"


class RenderInfo(_Base):
    dpi: int = Field(ge=36, le=600)
    renderer: str
    version: str


class StyleBible(_Base):
    reference_pages: list[int] = Field(default_factory=list)
    palette: list[str] = Field(default_factory=list)
    line: str | None = None
    texture: str | None = None
    negative_prompts: list[str] = Field(default_factory=list)


class Rights(_Base):
    license: str
    note: str | None = None


class PageBlock(_Base):
    block_id: str
    page_index: int = Field(ge=1)
    type: BlockType
    text: str
    bbox_px: tuple[int, int, int, int]
    source: SpanSource
    confidence: float = Field(ge=0.0, le=1.0)
    reading_order: int = Field(ge=1)
    lang: str | None = None

    @model_validator(mode="after")
    def _check_bbox(self) -> PageBlock:
        x1, y1, x2, y2 = self.bbox_px
        if not (x2 > x1 and y2 > y1):
            raise ValueError(f"invalid bbox for {self.block_id}: {self.bbox_px}")
        return self


class TextSpan(_Base):
    span_id: str
    page_index: int = Field(ge=1)
    text: str
    bbox_px: tuple[int, int, int, int]
    source: SpanSource
    confidence: float = Field(ge=0.0, le=1.0)
    version: int = Field(ge=1)
    status: Status
    hash: str

    @model_validator(mode="after")
    def _check(self) -> TextSpan:
        x1, y1, x2, y2 = self.bbox_px
        if not (x2 > x1 and y2 > y1):
            raise ValueError(f"invalid bbox for {self.span_id}: {self.bbox_px}")
        if not SHORT_HASH_RE.match(self.hash):
            raise ValueError(f"invalid span hash for {self.span_id}")
        return self


class Hotspot(_Base):
    hotspot_id: str
    page_index: int = Field(ge=1)
    label: str
    bbox_px: tuple[int, int, int, int]
    description: str
    source: HotspotSource
    confidence: float = Field(ge=0.0, le=1.0)
    version: int = Field(ge=1)
    status: Status
    hash: str

    @model_validator(mode="after")
    def _check(self) -> Hotspot:
        x1, y1, x2, y2 = self.bbox_px
        if not (x2 > x1 and y2 > y1):
            raise ValueError(f"invalid bbox for {self.hotspot_id}: {self.bbox_px}")
        if not SHORT_HASH_RE.match(self.hash):
            raise ValueError(f"invalid hotspot hash for {self.hotspot_id}")
        return self


class Page(_Base):
    index: int = Field(ge=1)
    image_path: str
    width_px: int = Field(ge=1)
    height_px: int = Field(ge=1)
    width_pt: float | None = None
    height_pt: float | None = None
    text: str
    text_source: TextSource
    text_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    language: str | None = None
    blocks: list[PageBlock] = Field(default_factory=list)
    text_spans: list[TextSpan] = Field(default_factory=list)
    hotspots: list[Hotspot] = Field(default_factory=list)
    sha256: str
    render: RenderInfo | None = None

    @model_validator(mode="after")
    def _check_page(self) -> Page:
        if not SHA256_RE.match(self.sha256):
            raise ValueError(f"invalid sha256 for page {self.index}")
        if self.text_source == TextSource.none and self.text != "":
            raise ValueError(f"page {self.index}: text_source=none requires empty text")
        if self.text_source != TextSource.none and self.text == "":
            raise ValueError(f"page {self.index}: text_source={self.text_source} requires text")

        for block in self.blocks:
            if block.page_index != self.index:
                raise ValueError(f"block {block.block_id} page_index mismatch")
            self._check_bbox(block.bbox_px, f"block {block.block_id}")
        for span in self.text_spans:
            if span.page_index != self.index:
                raise ValueError(f"span {span.span_id} page_index mismatch")
            self._check_bbox(span.bbox_px, f"span {span.span_id}")
        for hotspot in self.hotspots:
            if hotspot.page_index != self.index:
                raise ValueError(f"hotspot {hotspot.hotspot_id} page_index mismatch")
            self._check_bbox(hotspot.bbox_px, f"hotspot {hotspot.hotspot_id}")

        ids = [b.block_id for b in self.blocks] + [s.span_id for s in self.text_spans] + [h.hotspot_id for h in self.hotspots]
        if len(ids) != len(set(ids)):
            raise ValueError(f"page {self.index}: duplicate block/span/hotspot ids")
        return self

    def _check_bbox(self, bbox: tuple[int, int, int, int], name: str) -> None:
        x1, y1, x2, y2 = bbox
        if x1 < 0 or y1 < 0 or x2 > self.width_px or y2 > self.height_px:
            raise ValueError(f"{name}: bbox {bbox} outside page {self.width_px}x{self.height_px}")


class BookPackage(_Base):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    book_id: str
    source_name: str
    title: str
    authors: list[str] = Field(default_factory=list)
    language: str
    languages: list[str] = Field(default_factory=list)
    content_type: ContentType
    source_type: SourceType
    source_path: str
    page_count: int = Field(ge=1)
    pages: list[Page]
    style: StyleBible | None = None
    rights: Rights | None = None
    status: BookStatus
    query_set_ids: list[str] = Field(default_factory=list)
    capabilities_path: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def _check_book(self) -> BookPackage:
        if not BOOK_ID_RE.match(self.book_id):
            raise ValueError(f"invalid book_id: {self.book_id}")
        if self.page_count != len(self.pages):
            raise ValueError(f"page_count {self.page_count} != len(pages) {len(self.pages)}")
        if [p.index for p in self.pages] != list(range(1, len(self.pages) + 1)):
            raise ValueError("page indices must be 1..N and ordered")
        if self.source_path.startswith("/") or re.match(r"^[A-Za-z]:", self.source_path):
            raise ValueError("source_path must be package-relative")
        if ".." in self.source_path.split("/"):
            raise ValueError("source_path must not escape the package")
        return self


class QueryAction(_Base):
    action_id: str
    kind: QueryKind
    text: str
    mandatory: bool
    control_action: ControlAction | None = None
    seek_query: str | None = None
    search_text: str | None = None
    highlight_text: str | None = None
    target: str | None = None
    expected: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _check_required(self) -> QueryAction:
        required = {
            QueryKind.control: "control_action",
            QueryKind.seek: "seek_query",
            QueryKind.search: "search_text",
            QueryKind.highlight: "highlight_text",
            QueryKind.click: "target",
        }
        field_name = required.get(self.kind)
        if field_name and getattr(self, field_name) is None:
            raise ValueError(f"{self.action_id}: kind={self.kind.value} requires {field_name}")
        return self


class QueryItem(_Base):
    query_id: str
    number: int = Field(ge=1)
    instruction: str
    audio_path: str | None = None
    mandatory: bool
    lang: QueryLang
    actions: list[QueryAction] = Field(min_length=1)
    expected: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _check_item(self) -> QueryItem:
        ids = [a.action_id for a in self.actions]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{self.query_id}: duplicate action ids")
        if any(a.mandatory for a in self.actions) and not self.mandatory:
            raise ValueError(f"{self.query_id}: item must be mandatory when any action is mandatory")
        return self


class QuerySet(_Base):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    query_set_id: str
    book_id: str | None = None
    name: str
    language: QueryLang
    source: QuerySetSource
    items: list[QueryItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_set(self) -> QuerySet:
        numbers = [i.number for i in self.items]
        if len(numbers) != len(set(numbers)):
            raise ValueError("duplicate item numbers")
        ids = [i.query_id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate query ids")
        return self


# ---------------------------------------------------------------------------
# §6 知识层
# ---------------------------------------------------------------------------


class FactSource(str, Enum):
    auto = "auto"
    human = "human"


class FactSubjectType(str, Enum):
    character = "character"
    object = "object"
    scene = "scene"
    action = "action"
    concept = "concept"
    formula = "formula"
    passage = "passage"
    other = "other"


class Relation(_Base):
    pred: str
    obj: str


class PageFact(_Base):
    fact_id: str
    book_id: str
    page_index: int = Field(ge=1)
    subject: str
    subject_type: FactSubjectType
    attributes: dict[str, str] = Field(default_factory=dict)
    relations: list[Relation] = Field(default_factory=list)
    bbox_px: tuple[int, int, int, int] | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    source: FactSource
    version: int = Field(ge=1)
    status: Status
    hash: str
    created_at: datetime


class QaIntent(str, Enum):
    identify = "identify"
    count = "count"
    locate = "locate"
    attribute = "attribute"
    why = "why"
    plot = "plot"
    predict = "predict"
    feeling = "feeling"
    compare = "compare"
    vocab = "vocab"
    common = "common"
    other = "other"


class QaScope(str, Enum):
    page = "page"
    book = "book"
    video = "video"


class QaAnswers(_Base):
    strong: str
    weak: str
    guide: str


class Evidence(_Base):
    page_index: int = Field(ge=1)
    bbox_px: tuple[int, int, int, int] | None = None
    span_id: str | None = None
    fact_id: str | None = None
    quote: str | None = None


class VideoAnchor(_Base):
    scene_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> VideoAnchor:
        if self.end_ms <= self.start_ms:
            raise ValueError(f"video anchor {self.scene_id}: end_ms must be > start_ms")
        return self


class QaCard(_Base):
    card_id: str
    book_id: str
    kind: Literal["qa"] = "qa"
    intent: QaIntent
    scope: QaScope
    langs: list[str] = Field(min_length=1)
    question_canonical: str
    variants: list[str] = Field(min_length=5)
    entities: list[str] = Field(default_factory=list)
    answers: dict[str, QaAnswers]
    evidence: list[Evidence] = Field(min_length=1)
    video_anchor: VideoAnchor | None = None
    priority: int = Field(ge=1, le=3)
    source: FactSource
    version: int = Field(ge=1)
    status: Status
    hash: str
    created_at: datetime


class Alias(_Base):
    alias_id: str
    book_id: str
    entity: str
    aliases: list[str] = Field(min_length=3)
    source: FactSource
    version: int = Field(ge=1)
    status: Status
    hash: str


class Narrative(_Base):
    page_index: int = Field(ge=1)
    book_id: str
    text: str
    entities: list[str] = Field(default_factory=list)
    visible_text: list[str] = Field(default_factory=list)
    source: Literal["vlm", "human"]
    confidence: float = Field(ge=0.0, le=1.0)
    version: int = Field(ge=1)
    status: Status
    hash: str


# ---------------------------------------------------------------------------
# §7 人工修正
# ---------------------------------------------------------------------------


class AnnotationTargetType(str, Enum):
    page_block = "page_block"
    text_span = "text_span"
    hotspot = "hotspot"
    page_fact = "page_fact"
    qa_card = "qa_card"
    alias = "alias"
    scene = "scene"
    book = "book"


class Annotation(_Base):
    annotation_id: str
    target_type: AnnotationTargetType
    target_id: str
    field: str
    value: Any = None
    old_value: Any = None
    source: Literal["human"] = "human"
    reviewer: str
    created_at: datetime
    status: Status
    reason: str | None = None
    hash: str


class ReviewReason(str, Enum):
    low_confidence = "low_confidence"
    conflict = "conflict"
    missing = "missing"
    generated = "generated"


class ReviewStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    edited = "edited"


class ReviewItem(_Base):
    review_id: str
    target_type: AnnotationTargetType
    target_id: str
    reason: ReviewReason
    status: ReviewStatus = ReviewStatus.pending
    assignee: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# §8 生成产物
# ---------------------------------------------------------------------------


class GenerationStatus(str, Enum):
    ok = "ok"
    fallback = "fallback"
    failed = "failed"


class Character(_Base):
    character_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    appearance: str = ""
    personality: str = ""
    voice: str | None = None
    role: str | None = None


class Dialogue(_Base):
    speaker: str
    text: str


class Beat(_Base):
    beat_id: str
    description: str
    narration: str
    dialogues: list[Dialogue] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    duration_ms: int = Field(gt=0)


class PageStory(_Base):
    page_index: int = Field(ge=1)
    beats: list[Beat] = Field(min_length=1)
    state_before: str | None = None
    state_after: str | None = None


class StoryPlan(_Base):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    book_id: str
    language: str
    title: str
    logline: str
    characters: list[Character] = Field(default_factory=list)
    style_bible: StyleBible = Field(default_factory=StyleBible)
    pages: list[PageStory] = Field(min_length=1)
    model: str
    prompt_version: str
    source_hash: str
    created_at: datetime


class Subtitle(_Base):
    text: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    lang: str

    @model_validator(mode="after")
    def _check(self) -> Subtitle:
        if self.end_ms <= self.start_ms:
            raise ValueError(f"subtitle end_ms must be > start_ms: {self.text!r}")
        return self


class SceneObject(_Base):
    entity: str
    bbox_px: tuple[int, int, int, int]
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> SceneObject:
        x1, y1, x2, y2 = self.bbox_px
        if not (x2 > x1 and y2 > y1):
            raise ValueError(f"invalid bbox for {self.entity}: {self.bbox_px}")
        if self.end_ms <= self.start_ms:
            raise ValueError(f"scene object {self.entity}: end_ms must be > start_ms")
        return self


class Scene(_Base):
    scene_id: str
    page_index: int = Field(ge=1)
    beat_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    caption: str
    aliases: list[str] = Field(min_length=1)
    entities: list[str] = Field(default_factory=list)
    action: str = ""
    camera: str = ""
    prompt: str = ""
    negative_prompt: str = ""
    keyframe_path: str = ""
    video_path: str = ""
    thumbnail_path: str = ""
    subtitles: list[Subtitle] = Field(default_factory=list)
    objects: list[SceneObject] = Field(default_factory=list)
    hotspot_ids: list[str] = Field(default_factory=list)
    seed: int
    style_score: float | None = Field(default=None, ge=0.0, le=1.0)
    source: FactSource
    status: GenerationStatus

    @model_validator(mode="after")
    def _check(self) -> Scene:
        if self.end_ms <= self.start_ms:
            raise ValueError(f"scene {self.scene_id}: end_ms must be > start_ms")
        return self


class PageMap(_Base):
    page_index: int = Field(ge=1)
    scene_ids: list[str] = Field(default_factory=list)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)


class ScenePlan(_Base):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    book_id: str
    plan_version: int = Field(ge=1)
    page_map: list[PageMap] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    model: str
    prompt_version: str
    source_hash: str
    created_at: datetime

    @model_validator(mode="after")
    def _check(self) -> ScenePlan:
        scene_ids = [scene.scene_id for scene in self.scenes]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("duplicate scene_id in scene plan")
        for mapping in self.page_map:
            for scene_id in mapping.scene_ids:
                if scene_id not in scene_ids:
                    raise ValueError(f"page_map references unknown scene {scene_id}")
        return self


class VideoSegment(_Base):
    segment_id: str
    scene_id: str
    page_index: int = Field(ge=1)
    path: str
    duration_ms: int = Field(gt=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    fps: int = Field(ge=1)
    first_frame_path: str | None = None
    last_frame_path: str | None = None
    model: str
    params: dict[str, Any] = Field(default_factory=dict)
    seed: int
    style_score: float | None = Field(default=None, ge=0.0, le=1.0)
    status: GenerationStatus
    fallback_reason: str | None = None
    created_at: datetime


class GenerationPage(_Base):
    page_index: int = Field(ge=1)
    video_path: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    scene_ids: list[str] = Field(default_factory=list)
    thumbnail_path: str | None = None


class GenerationMetrics(_Base):
    style_score_avg: float | None = None
    fallback_pages: int = 0
    qa_cards: int = 0
    duration_ms: int = 0


class BookGenerationResult(_Base):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    book_id: str
    generation_version: int = Field(ge=1)
    status: str
    pages: list[GenerationPage] = Field(default_factory=list)
    full_video_path: str | None = None
    subtitle_paths: list[str] = Field(default_factory=list)
    audio_paths: list[str] = Field(default_factory=list)
    timeline_path: str | None = None
    manifest_path: str | None = None
    metrics: GenerationMetrics | None = None
    model_versions: dict[str, str] = Field(default_factory=dict)
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    created_at: datetime


class ManifestStage(_Base):
    name: str
    provider: str
    model: str
    model_version: str | None = None
    prompt_version: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = None
    started_at: datetime | None = None
    duration_ms: int = 0
    status: str
    error_code: str | None = None
    degraded: bool = False
    output_hash: str | None = None


class ManifestArtifact(_Base):
    path: str
    sha256: str


class GenerationManifest(_Base):
    manifest_id: str
    book_id: str
    generation_version: int = Field(ge=1)
    input_hash: str
    contract_version: str = SCHEMA_VERSION
    stages: list[ManifestStage] = Field(default_factory=list)
    artifacts: list[ManifestArtifact] = Field(default_factory=list)
    model_versions: dict[str, str] = Field(default_factory=dict)
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    status: str


class TraceStage(_Base):
    name: str
    ms: int = Field(ge=0)
    ok: bool = True


class Trace(_Base):
    trace_id: str
    kind: str
    input: dict[str, Any] = Field(default_factory=dict)
    stages: list[TraceStage] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    latency_ms: int = Field(ge=0)
    output_hash: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# §9 交互协议
# ---------------------------------------------------------------------------


class InteractionKind(str, Enum):
    auto = "auto"
    control = "control"
    seek = "seek"
    search = "search"
    highlight = "highlight"
    click = "click"
    qa = "qa"


class ActionType(str, Enum):
    play = "play"
    pause = "pause"
    resume = "resume"
    stop = "stop"
    seek = "seek"
    highlight = "highlight"
    show_card = "show_card"
    none = "none"


class AnswerTier(str, Enum):
    strong = "strong"
    weak = "weak"
    quote = "quote"
    guide = "guide"


class ClickPoint(_Base):
    x_px: int | None = None
    y_px: int | None = None
    x_norm: float | None = Field(default=None, ge=0.0, le=1.0)
    y_norm: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check(self) -> ClickPoint:
        pixel = self.x_px is not None and self.y_px is not None
        normalized = self.x_norm is not None and self.y_norm is not None
        if not pixel and not normalized:
            raise ValueError("click needs x_px/y_px or x_norm/y_norm")
        return self


class InteractionInput(_Base):
    text: str | None = None
    audio_path: str | None = None
    audio_url: str | None = None
    language: str | None = None
    page_index: int | None = None
    current_time_ms: int | None = None
    click: ClickPoint | None = None


class InteractionContext(_Base):
    last_page_index: int | None = None
    last_scene_id: str | None = None
    last_entities: list[str] = Field(default_factory=list)
    last_lang: str | None = None
    history_turn_ids: list[str] = Field(default_factory=list)


class InteractionRequest(_Base):
    request_id: str | None = None
    book_id: str
    session_id: str
    kind: InteractionKind = InteractionKind.auto
    input: InteractionInput = Field(default_factory=InteractionInput)
    context: InteractionContext = Field(default_factory=InteractionContext)

    @model_validator(mode="after")
    def _check(self) -> InteractionRequest:
        if self.kind == InteractionKind.click and self.input.click is None:
            raise ValueError("kind=click requires input.click")
        if not (self.input.text or self.input.audio_path or self.input.audio_url):
            raise ValueError("input needs text, audio_path or audio_url")
        return self


class InteractionAction(_Base):
    type: ActionType = ActionType.none
    scene_id: str | None = None
    time_ms: int | None = None
    span_ids: list[str] = Field(default_factory=list)
    hotspot_id: str | None = None


class AnswerPayload(_Base):
    text: str
    audio_path: str | None = None
    language: str | None = None
    tier: AnswerTier | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    scene_id: str | None = None
    time_ms: int | None = None


class LatencyBreakdown(_Base):
    asr: int | None = None
    route: int | None = None
    retrieve: int | None = None
    generate: int | None = None
    tts: int | None = None
    total: int = Field(ge=0)


class ErrorInfo(_Base):
    code: str
    message: str
    retryable: bool = False


class InteractionResponse(_Base):
    request_id: str
    book_id: str
    session_id: str
    kind: InteractionKind
    action: InteractionAction = Field(default_factory=InteractionAction)
    answer: AnswerPayload | None = None
    latency: LatencyBreakdown = Field(default_factory=LatencyBreakdown)
    status: Literal["ok", "fallback", "error"] = "ok"
    error: ErrorInfo | None = None

    @model_validator(mode="after")
    def _check(self) -> InteractionResponse:
        if self.status == "error" and self.error is None:
            raise ValueError("status=error requires error")
        return self


class Turn(_Base):
    turn_id: str
    session_id: str
    book_id: str
    ts: datetime
    input_audio: str | None = None
    input_text: str | None = None
    input_image: str | None = None
    kind: InteractionKind
    tier: AnswerTier | None = None
    reply_text: str | None = None
    reply_audio: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    video_time: int | None = None
    latency: LatencyBreakdown | None = None


# ---------------------------------------------------------------------------
# §10 Job
# ---------------------------------------------------------------------------


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    degraded = "degraded"


class JobStage(str, Enum):
    ingest = "ingest"
    ocr = "ocr"
    vlm = "vlm"
    story = "story"
    scene = "scene"
    video = "video"
    tts = "tts"
    compose = "compose"
    index = "index"


class Job(_Base):
    job_id: str
    book_id: str
    status: JobStatus
    stage: JobStage
    progress: float = Field(ge=0.0, le=1.0)
    created_at: datetime
    updated_at: datetime
    error: str | None = None
    error_code: str | None = None
    degraded: bool = False
    retryable: bool = True
    manifest_path: str | None = None


# ---------------------------------------------------------------------------
# §11 能力报告
# ---------------------------------------------------------------------------


class Coverage(_Base):
    text_search: float = Field(ge=0.0, le=1.0)
    video: float = Field(ge=0.0, le=1.0)
    qa: float = Field(ge=0.0, le=1.0)


class NeedsReview(_Base):
    target_type: AnnotationTargetType
    target_id: str
    reason: ReviewReason


class CapabilityReport(_Base):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    book_id: str
    generated_at: datetime
    content_type: ContentType
    languages: list[str] = Field(default_factory=list)
    pages_total: int = Field(ge=0)
    pages_with_text: int = Field(ge=0)
    ocr_pages: int = Field(ge=0)
    blocks: int = Field(ge=0)
    hotspots: int = Field(ge=0)
    scenes: int = Field(ge=0)
    videos: int = Field(ge=0)
    qa_cards: int = Field(ge=0)
    coverage: Coverage = Field(default_factory=lambda: Coverage(text_search=0.0, video=0.0, qa=0.0))
    needs_review: list[NeedsReview] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    status: str


# ---------------------------------------------------------------------------
# §12 评测
# ---------------------------------------------------------------------------


class EvalCase(_Base):
    case_id: str
    book_id: str
    query_set_id: str | None = None
    number: int = Field(ge=1)
    audio_path: str | None = None
    query_text: str | None = None
    kind: InteractionKind
    lang: str | None = None
    mandatory: bool = False
    expected: dict[str, Any] | None = None
    notes: str | None = None


class EvalRun(_Base):
    run_id: str
    cases_path: str
    book_ids: list[str] = Field(default_factory=list)
    model_versions: dict[str, str] = Field(default_factory=dict)
    started_at: datetime
    finished_at: datetime | None = None
    results_path: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    status: str


class EvalResult(_Base):
    case_id: str
    request_id: str | None = None
    kind: InteractionKind
    status: str
    verdict: Literal["ok", "wrong", "miss", "fallback"]
    answer_text: str | None = None
    # 回答档位（契约 §9.2）：strong / weak / quote / guide。
    # 引导（guide）不是答案，评测按档位分桶时不能混进正确率。
    tier: str | None = None
    action: InteractionAction | None = None
    scene_id: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    latency_ms: int = Field(ge=0)
    asr_text: str | None = None
    notes: str | None = None


BOOK_MODEL = BookPackage
QUERY_SET_MODEL = QuerySet

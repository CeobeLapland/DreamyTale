"""Core v2 contract models.

Coverage: BookPackage / Page / PageBlock / TextSpan / Hotspot / QuerySet.
Generation, knowledge and interaction models will be added as the pipeline lands.
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


BOOK_MODEL = BookPackage
QUERY_SET_MODEL = QuerySet

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol


ObjectCategory = Literal[
    "character",
    "animal",
    "object",
    "plant",
    "place",
    "text",
    "other",
]

CATEGORIES = {
    "character",
    "animal",
    "object",
    "plant",
    "place",
    "text",
    "other",
}


@dataclass(frozen=True, slots=True)
class VLMObject:
    label: str
    category: ObjectCategory
    description: str
    confidence: float
    bbox_px: tuple[int, int, int, int] | None = None

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("VLM object label must not be empty")
        if not self.description.strip():
            raise ValueError("VLM object description must not be empty")
        if self.category not in CATEGORIES:
            raise ValueError(f"invalid VLM object category: {self.category}")
        if not 0 <= self.confidence <= 1:
            raise ValueError("VLM object confidence must be between 0 and 1")
        if self.bbox_px is not None:
            if len(self.bbox_px) != 4:
                raise ValueError("VLM object bbox must have four coordinates")
            x1, y1, x2, y2 = self.bbox_px
            if x1 < 0 or y1 < 0 or x1 >= x2 or y1 >= y2:
                raise ValueError("VLM object bbox is invalid")


@dataclass(frozen=True, slots=True)
class VLMPageResult:
    page_index: int
    summary: str
    scene: str
    characters: tuple[str, ...]
    objects: tuple[VLMObject, ...]

    def __post_init__(self) -> None:
        if self.page_index < 1:
            raise ValueError("VLM page_index must start at 1")
        if not self.summary.strip():
            raise ValueError("VLM page summary must not be empty")
        if not self.scene.strip():
            raise ValueError("VLM scene must not be empty")
        if any(not name.strip() for name in self.characters):
            raise ValueError("VLM character names must not be empty")


class VLMAdapter(Protocol):
    def provider_name(self) -> str:
        ...

    def health(self) -> None:
        ...

    def understand(
        self,
        image_path: Path,
        *,
        page_index: int,
        text: str,
        language: str,
    ) -> VLMPageResult:
        ...
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class OCRBlock:
    text: str
    bbox_px: tuple[int, int, int, int]
    confidence: float

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("OCR block text must not be empty")
        if len(self.bbox_px) != 4:
            raise ValueError("OCR block bbox must have four coordinates")
        x1, y1, x2, y2 = self.bbox_px
        if x1 < 0 or y1 < 0 or x1 >= x2 or y1 >= y2:
            raise ValueError("OCR block bbox is invalid")
        if not 0 <= self.confidence <= 1:
            raise ValueError("OCR block confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class OCRResult:
    page_index: int
    text: str
    blocks: tuple[OCRBlock, ...]

    def __post_init__(self) -> None:
        if self.page_index < 1:
            raise ValueError("OCR page_index must start at 1")


class OCRAdapter(Protocol):
    def provider_name(self) -> str:
        ...

    def health(self) -> None:
        ...

    def recognize(
        self,
        image_path: Path,
        *,
        page_index: int,
        language: str,
    ) -> OCRResult:
        ...
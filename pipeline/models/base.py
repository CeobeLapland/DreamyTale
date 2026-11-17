"""Provider interfaces for OCR / VLM.

Business code depends on these protocols, never on a vendor SDK. Swapping a
provider means editing `config/models.yaml`, not touching the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class OCRItem:
    text: str
    bbox_px: tuple[int, int, int, int]
    confidence: float


@dataclass(frozen=True)
class VLMResult:
    text: str
    data: dict[str, Any] | None = None


class OCRProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def recognize(self, image_path: Path) -> list[OCRItem]: ...


class VLMProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def describe(
        self,
        image_path: Path,
        prompt: str,
        json_schema: dict[str, Any] | None = None,
    ) -> VLMResult: ...

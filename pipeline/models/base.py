"""Provider interfaces for OCR / VLM / ASR.

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


@dataclass(frozen=True)
class ASRResult:
    """One transcription: text plus where it came from and how long it took."""

    text: str
    language: str | None = None
    language_probability: float | None = None
    duration_ms: int = 0
    latency_ms: int = 0


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


class ASRProvider(Protocol):
    name: str
    detail: str

    def available(self) -> bool: ...

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
        initial_prompt: str | None = None,
    ) -> ASRResult: ...

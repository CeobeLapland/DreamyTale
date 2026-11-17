"""Null providers: keep the pipeline runnable when nothing is configured."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import OCRItem, VLMResult


class NullOCR:
    name = "null"

    def available(self) -> bool:
        return False

    def recognize(self, image_path: Path) -> list[OCRItem]:
        return []


class NullVLM:
    name = "null"

    def available(self) -> bool:
        return False

    def describe(
        self,
        image_path: Path,
        prompt: str,
        json_schema: dict[str, Any] | None = None,
    ) -> VLMResult:
        return VLMResult(text="", data=None)

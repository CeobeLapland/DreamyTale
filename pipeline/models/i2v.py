from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class I2VRequest:
    image_path: Path
    prompt: str
    negative_prompt: str
    duration_ms: int
    seed: int
    width: int = 1280
    height: int = 720
    fps: int = 12
    image_url: str | None = None


class I2VProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def generate(self, request: I2VRequest, out_path: Path) -> Path: ...


class NullI2V:
    name = "null"

    def __init__(self, detail: str = "I2V provider not configured") -> None:
        self.detail = detail

    def available(self) -> bool:
        return False

    def generate(self, request: I2VRequest, out_path: Path) -> Path:
        raise RuntimeError(self.detail)
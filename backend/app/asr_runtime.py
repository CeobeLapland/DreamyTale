"""Speech input at runtime: one shared ASR provider + the book's own vocabulary.

The prompt and language mapping live in `pipeline.asr_prompt` so the offline
transcription run and the online endpoint hear the book the same way.
"""

from __future__ import annotations

from pathlib import Path
from threading import Lock

from backend.app.models import BookPackage
from pipeline.asr_prompt import answer_language, vocabulary_prompt
from pipeline.models import ASRResult, build_asr

_provider = None
_provider_lock = Lock()

__all__ = ["answer_language", "get_provider", "recognize", "vocabulary_prompt"]


def get_provider():
    global _provider
    if _provider is None:
        with _provider_lock:
            if _provider is None:
                _provider = build_asr()
    return _provider


def recognize(
    audio_path: Path,
    package: BookPackage,
    package_root: Path,
) -> tuple[ASRResult | None, str]:
    """Transcribe one upload; returns (result, reason when unavailable)."""
    provider = get_provider()
    if not provider.available():
        return None, provider.detail or "ASR provider unavailable"
    prompt = vocabulary_prompt(package, package_root)
    try:
        return provider.transcribe(audio_path, initial_prompt=prompt), ""
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller as fallback
        return None, f"{type(exc).__name__}: {exc}"

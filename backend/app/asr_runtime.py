"""Speech input at runtime: one shared ASR provider + the book's own vocabulary.

The prompt and language mapping live in `pipeline.asr_prompt` so the offline
transcription run and the online endpoint hear the book the same way.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from threading import Lock

from backend.app.models import BookPackage
from pipeline.asr_prompt import answer_language, vocabulary_prompt
from pipeline.models import ASRResult, build_asr
from pipeline.models.registry import load_config

_provider = None
_provider_lock = Lock()

__all__ = [
    "answer_language",
    "confidence_threshold",
    "get_provider",
    "is_low_confidence",
    "recognize",
    "vocabulary_prompt",
]


@lru_cache(maxsize=1)
def confidence_threshold() -> float:
    section = load_config().get("asr", {}) or {}
    try:
        return float(section.get("confirm_below", 0.45))
    except (TypeError, ValueError):
        return 0.45


def is_low_confidence(result: ASRResult | None) -> bool:
    """True when the provider reports a probability below the confirmation bar."""
    if result is None or not result.text.strip():
        return False
    confidence = (
        result.confidence
        if result.confidence is not None
        else result.language_probability
    )
    if confidence is None:
        return False
    return confidence < confidence_threshold()


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

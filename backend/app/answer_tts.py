"""Server-side answer audio.

Narration is generated offline by `pipeline/tts.py`; this module handles the
short answer that goes back with an interaction. Audio is cached under
`derived/audio/answer/` by a hash of (language, text), so repeated questions do
not pay the network cost again. Failure is silent: the frontend still has its
browser-speech fallback.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from pathlib import Path
from threading import Lock

from pipeline.tts import edge_tts_available, voice_for

ANSWER_DIR = Path("derived") / "audio" / "answer"
_MAX_CHARS = 220
_LOCK = Lock()

_SPACE = re.compile(r"\s+")


def _spoken_text(text: str) -> str:
    content = _SPACE.sub(" ", str(text or "")).strip()
    if len(content) <= _MAX_CHARS:
        return content
    # Cut at a sentence boundary instead of mid-word.
    cut = content[:_MAX_CHARS]
    for marker in ("。", "！", "？", ". ", "! ", "? "):
        position = cut.rfind(marker)
        if position >= _MAX_CHARS // 2:
            return cut[: position + len(marker)].strip()
    return cut.rstrip("，,、;； ")


def _language_key(language: str | None) -> str:
    return "en" if str(language or "").lower().startswith("en") else "zh"


def answer_audio_path(
    package_root: Path,
    text: str,
    language: str | None = None,
) -> Path:
    content = _spoken_text(text)
    digest = hashlib.sha256(
        f"{_language_key(language)}|{content}".encode("utf-8")
    ).hexdigest()[:16]
    return package_root / ANSWER_DIR / f"{digest}.mp3"


def synthesize_answer(
    package_root: Path,
    text: str,
    language: str | None = None,
) -> str | None:
    """Return a package-relative mp3 path, or None when TTS is unavailable."""
    content = _spoken_text(text)
    if len(content) < 2:
        return None
    path = answer_audio_path(package_root, content, language)
    relative = str(path.relative_to(package_root)).replace("\\", "/")
    if path.is_file() and path.stat().st_size > 0:
        return relative
    if not edge_tts_available():
        return None

    with _LOCK:
        if path.is_file() and path.stat().st_size > 0:
            return relative
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.stem}.tmp.mp3")
        try:
            asyncio.run(
                _speak(content, voice_for(language or "zh-CN"), temporary)
            )
            if not temporary.is_file() or temporary.stat().st_size == 0:
                return None
            os.replace(temporary, path)
        except Exception:  # noqa: BLE001 - audio is optional
            return None
        finally:
            temporary.unlink(missing_ok=True)
    return relative


async def _speak(text: str, voice: str, path: Path) -> None:
    import edge_tts

    await edge_tts.Communicate(text, voice).save(str(path))

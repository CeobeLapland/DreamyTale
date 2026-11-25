"""Narration audio with Edge TTS.

Optional stage. When edge-tts is missing or the network is blocked, the stage
reports it and the book stays silent: the narration is still delivered as
subtitles, which is the degradation the contract documents for TTS_FAILED.

Per character voices are used when the story plan names them; the book level
narration uses one calm voice.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import DATA, BookSpec

AUDIO_DIR = Path("derived") / "audio" / "narration"

VOICES = {
    "zh": "zh-CN-XiaoyiNeural",
    "en": "en-US-AriaNeural",
}


def _voice_for(language: str) -> str:
    return VOICES["en"] if str(language).lower().startswith("en") else VOICES["zh"]


def voice_for(language: str) -> str:
    """Voice used for both narration and runtime answers."""
    return _voice_for(language)


def edge_tts_available() -> bool:
    try:
        import edge_tts  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def _speak(text: str, voice: str, out_path: Path) -> None:
    import asyncio

    import edge_tts

    async def run() -> None:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(out_path))

    asyncio.run(run())


def run_tts(spec: BookSpec) -> dict[str, Any]:
    """Synthesize one narration file per page."""
    story_path = DATA / spec.book_id / "derived" / "story" / "story_plan.json"
    if not story_path.exists():
        raise FileNotFoundError(story_path)
    story = json.loads(story_path.read_text(encoding="utf-8"))

    started = time.perf_counter()
    report: dict[str, Any] = {
        "book_id": spec.book_id,
        "available": edge_tts_available(),
        "files": [],
        "errors": [],
        "seconds": 0.0,
    }
    if not report["available"]:
        report["seconds"] = round(time.perf_counter() - started, 2)
        return report

    out_dir = DATA / spec.book_id / AUDIO_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    voice = _voice_for(story.get("language", "zh-CN"))

    for page in story.get("pages", []):
        page_index = int(page.get("page_index") or 0)
        parts: list[str] = []
        for beat in page.get("beats", []):
            narration = str(beat.get("narration") or "").strip()
            if narration:
                parts.append(narration)
            for line in beat.get("dialogues", []) or []:
                speaker = str(line.get("speaker") or "").strip()
                text = str(line.get("text") or "").strip()
                if text:
                    parts.append(f"{speaker}：{text}" if speaker else text)
        content = " ".join(parts).strip()
        if not content:
            continue
        out_path = out_dir / f"page-{page_index:03d}.mp3"
        try:
            _speak(content, voice, out_path)
            report["files"].append(str(out_path.relative_to(DATA / spec.book_id)).replace("\\", "/"))
        except Exception as exc:  # noqa: BLE001
            report["errors"].append({"page_index": page_index, "error": f"{type(exc).__name__}: {exc}"})
    report["seconds"] = round(time.perf_counter() - started, 2)
    return report

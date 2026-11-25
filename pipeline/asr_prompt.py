"""Shared ASR text helpers: the book's vocabulary prompt and language tags.

Used by the runtime (backend) and the offline transcription run (pipeline), so
both hear the same words the same way.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

from contracts.models import BookPackage

_PROMPT_LIMIT = 180


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _add(terms: list[str], value: object) -> None:
    if isinstance(value, str):
        text = value.strip()
        if text:
            terms.append(text)
    elif isinstance(value, list):
        for item in value:
            _add(terms, item)


def vocabulary_prompt(package: BookPackage, package_root: Path) -> str:
    """Short, book-specific word list for the decoder.

    Only names and labels the pipeline already extracted; never the answers.
    Deliberately **no generic command words** (播放/暂停/找到...): priming the
    decoder with Chinese commands makes it turn a short English "Play" clip
    into a Chinese sentence, and "结束播放" into "继续播放". The commands are
    common words the model already knows; the prompt exists for the book's
    unusual names.
    """
    names: list[str] = []
    _add(names, package.title)

    story = _read_json(package_root / "derived" / "story" / "story_plan.json")
    for character in story.get("characters", []) or []:
        if isinstance(character, dict):
            _add(names, character.get("name"))
            _add(names, character.get("aliases"))

    labels: list[str] = []
    for page in package.pages:
        for hotspot in page.hotspots:
            _add(labels, hotspot.label)

    aliases: list[str] = []
    scene = _read_json(package_root / "derived" / "scene" / "scene_plan.json")
    for item in scene.get("scenes", []) or []:
        if isinstance(item, dict):
            _add(aliases, item.get("aliases"))

    # Entity frequency: a word that shows up on many pages is more likely to
    # be asked about than a one-off credit from the title page.
    counts: collections.Counter[str] = collections.Counter()
    first_seen: dict[str, int] = {}
    for page in story.get("pages", []) or []:
        if not isinstance(page, dict):
            continue
        for beat in page.get("beats", []) or []:
            if not isinstance(beat, dict):
                continue
            for entity in beat.get("entities", []) or []:
                if not isinstance(entity, str):
                    continue
                text = entity.strip()
                if not text:
                    continue
                first_seen.setdefault(text, len(first_seen))
                counts[text] += 1
    ranked = sorted(counts, key=lambda term: (-counts[term], first_seen.get(term, 0)))

    selected: list[str] = []
    seen: set[str] = set()
    length = 0
    for term in [*names, *labels, *aliases, *ranked]:
        if term in seen:
            continue
        seen.add(term)
        if length + len(term) + 1 > _PROMPT_LIMIT:
            break
        selected.append(term)
        length += len(term) + 1
    return " ".join(selected)


def answer_language(spoken: str | None, fallback: str | None) -> str | None:
    """Map Whisper's short code to the contract's language tag."""
    if not spoken:
        return fallback
    lowered = spoken.lower()
    if lowered.startswith("zh"):
        return "zh-CN"
    if lowered.startswith("en"):
        return "en"
    return spoken

"""Story stage: BookPackage + page narratives -> StoryPlan (DATA_CONTRACT §8.1).

The StoryPlan is the single source for everything downstream (scenes, video,
TTS, QA), so it has to be right even when the model is weak or missing.

Shape of the stage:
  * one request for the book (logline, characters, style bible);
  * one request per page (the beats of that page);
  * a deterministic fallback for every page the model fails on, so the stage
    always produces a complete, contract-valid plan.

Small local models handle one narrow question better than one big question, so
the work is split into many small requests instead of one huge one.
"""

from __future__ import annotations

import json
import time
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contracts.models import (
    Beat,
    BookPackage,
    Character,
    Dialogue,
    Page,
    PageStory,
    StoryPlan,
    StyleBible,
    content_hash,
)

from .config import DATA, BookSpec
from .manual import auto_narrative_records, load_narrative_corrections
from .models.base import VLMResult

PROMPT_VERSION = "story-v1"
DEFAULT_DURATION_MS = 6000
MAX_BEATS_PER_PAGE = 2

BOOK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "logline": {"type": "string"},
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "appearance": {"type": "string"},
                    "personality": {"type": "string"},
                    "role": {"type": "string"},
                },
                "required": ["name", "appearance", "personality", "aliases", "role"],
            },
        },
        "style_bible": {
            "type": "object",
            "properties": {
                "palette": {"type": "array", "items": {"type": "string"}},
                "line": {"type": "string"},
                "texture": {"type": "string"},
                "negative_prompts": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["palette", "line", "texture", "negative_prompts"],
        },
    },
    "required": ["logline"],
}

BEAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "narration": {"type": "string"},
                    "dialogues": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "speaker": {"type": "string"},
                                "text": {"type": "string"},
                            },
                            "required": ["speaker", "text"],
                        },
                    },
                    "entities": {"type": "array", "items": {"type": "string"}},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "duration_ms": {"type": "integer"},
                },
                "required": ["description", "narration", "keywords"],
            },
        }
    },
    "required": ["beats"],
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _language_rule(language: str) -> str:
    """The story follows the book, but the keywords stay Chinese.

    The official commands for the English books are mixed: the seek/click
    instructions are Chinese ("找到蝙蝠装扮的画面"), so the aliases that make
    seek work have to be Chinese even when the book is English.
    """
    if str(language).lower().startswith("en"):
        return (
            "Write description, narration and dialogues in English. "
            "Write keywords in Chinese."
        )
    return "所有字段用中文书写。"

def _page_digest(
    book: BookPackage,
    narratives: dict[int, dict[str, Any]],
    limit: int = 160,
) -> str:
    lines: list[str] = []
    for page in book.pages:
        page_text = _story_page_text(page, book.language)
        narrative = str(
            narratives.get(page.index, {}).get("text") or ""
        ).strip()
        source = narrative or page_text
        if not source:
            continue
        lines.append(f"[p{page.index}] {source[:limit]}")
    return "\n".join(lines)

def _clean_list(values: Any, limit: int = 8) -> list[str]:
    if not isinstance(values, list):
        return []
    seen: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.append(text)
    return seen[:limit]


def _clean_style(raw: Any) -> StyleBible:
    data = raw if isinstance(raw, dict) else {}
    return StyleBible(
        reference_pages=[],
        palette=_clean_list(data.get("palette"), 6),
        line=str(data.get("line") or "手绘水彩绘本风格，细线勾边").strip(),
        texture=str(data.get("texture") or "纸张纹理，轻微颗粒").strip(),
        negative_prompts=_clean_list(
            data.get("negative_prompts") or ["照片写实", "3D 渲染", "文字变形"], 6
        ),
    )


def _clean_characters(raw: Any, book_id: str) -> list[Character]:
    characters: list[Character] = []
    if not isinstance(raw, list):
        return characters
    for index, item in enumerate(raw[:6], start=1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        characters.append(
            Character(
                character_id=f"char-{book_id}-{index:03d}",
                name=name,
                aliases=_clean_list(item.get("aliases"), 5),
                appearance=str(item.get("appearance") or "").strip(),
                personality=str(item.get("personality") or "").strip(),
                role=str(item.get("role") or "").strip() or None,
            )
        )
    return characters

def _clean_page_text_for_story(text: str) -> str:
    """Drop page numbers, hotspot labels and tiny OCR fragments."""
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue

        if re.fullmatch(
            r"[（(]?\s*(?:第\s*)?\d+\s*(?:页)?\s*[）).。]?",
            line,
        ):
            continue

        if re.fullmatch(r"[\d\W_]+", line):
            continue

        words = line.split()
        letters = "".join(ch for ch in line if ch.isalpha())
        uppercase_words = sum(
            1 for word in words if word and word.isupper()
        )

        if letters and letters.isupper() and len(words) <= 5:
            continue
        if len(words) <= 4 and uppercase_words >= max(1, len(words) - 1):
            continue
        if len(words) == 1 and len(line) <= 20:
            continue

        lines.append(line)

    return " ".join(lines).strip()

def _story_page_text(page: Page, language: str) -> str:
    """Filter English OCR labels before they reach subtitles and TTS."""
    page_text = _clean_page_text_for_story(page.text)

    if not str(language).lower().startswith("en"):
        return page_text
    if page.text_source != "ocr":
        return page_text

    blocks: list[str] = []
    for block in sorted(page.blocks, key=lambda item: item.reading_order):
        if block.source != "ocr":
            continue

        text = _clean_page_text_for_story(block.text)
        if not text:
            continue

        words = re.findall(r"[A-Za-z]+", text)
        if len(words) >= 3 or (
            len(words) >= 2 and re.search(r"[.!?]", text)
        ):
            blocks.append(text)

    return _clean_page_text_for_story(" ".join(blocks))

def _fallback_beats(
    book_id: str,
    page_index: int,
    page_text: str,
    narrative: str,
    entities: list[str],
) -> list[Beat]:
    """Use real page text; never insert fake page-number narration."""
    body = _clean_page_text_for_story(narrative or page_text or "")
    description = body[:120] if body else "The story continues."
    narration = body

    return [
        Beat(
            beat_id=f"beat-{book_id}-{page_index:03d}-01",
            description=description,
            narration=narration,
            dialogues=[],
            entities=entities[:6],
            duration_ms=DEFAULT_DURATION_MS,
        )
    ]


def _clean_beats(
    book_id: str,
    page_index: int,
    raw: Any,
    fallback: list[Beat],
) -> tuple[list[Beat], dict[str, list[str]]]:
    """Return the beats and the keywords per beat.

    The keywords are not part of the contract's Beat model; they are how a
    child would ask for this moment, and they become the scene aliases that
    make `seek` work.
    """
    items = raw.get("beats") if isinstance(raw, dict) else None
    if not isinstance(items, list) or not items:
        return fallback, {}
    beats: list[Beat] = []
    keywords: dict[str, list[str]] = {}
    for index, item in enumerate(items[:MAX_BEATS_PER_PAGE], start=1):
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or "").strip()
        narration = str(item.get("narration") or "").strip()
        if not description and not narration:
            continue
        dialogues: list[Dialogue] = []
        for line in item.get("dialogues") or []:
            if not isinstance(line, dict):
                continue
            speaker = str(line.get("speaker") or "").strip()
            text = str(line.get("text") or "").strip()
            if speaker and text:
                dialogues.append(Dialogue(speaker=speaker, text=text))
        try:
            duration = int(item.get("duration_ms") or DEFAULT_DURATION_MS)
        except (TypeError, ValueError):
            duration = DEFAULT_DURATION_MS
        beat_id = f"beat-{book_id}-{page_index:03d}-{index:02d}"
        beats.append(
            Beat(
                beat_id=beat_id,
                description=description or narration,
                narration=narration or description,
                dialogues=dialogues,
                entities=_clean_list(item.get("entities"), 8),
                duration_ms=max(3000, min(duration, 15000)),
            )
        )
        keywords[beat_id] = _clean_list(item.get("keywords"), 4)
    if not beats:
        return fallback, {}
    return beats, keywords


def _book_plan_prompt(book: BookPackage, digest: str, language: str) -> str:
    return (
        "你是一位儿童绘本编辑。下面是这本书每一页的文字（有些书正文在图里，所以也可能只有画面描述）。\n"
        "请给出三样东西：\n"
        "1) logline：一句话故事梗概；\n"
        "2) characters：角色列表，最多 4 个。每个角色必须写：name（书里的叫法）、"
        "appearance（一句话外形，如“扎马尾，穿粉色连衣裙”）、personality（一句话性格）、"
        "aliases（昵称或别的叫法，没有就空数组）、role（主角或配角）；\n"
        "3) style_bible：画风，包括 palette（配色，3-5 个）、line（线条）、texture（材质）、"
        "negative_prompts（负面提示词，3-4 个）。\n"
        "不要编造书里没有的情节或角色。\n"
        f"{_language_rule(language)}\n"
        "每页内容：\n"
        f"{digest}"
    )


def _page_plan_prompt(
    book: BookPackage,
    page_index: int,
    page_text: str,
    narrative: str,
    logline: str,
    characters: list[Character],
    language: str,
) -> str:
    names = "、".join(item.name for item in characters) or "无"
    details = "；".join(
        f"{item.name}（{item.appearance or '外形未描述'}，{item.personality or '性格未描述'}）"
        for item in characters
    ) or "无"
    return (
        f"你是一位儿童绘本编剧。这是《{book.title}》的第 {page_index} 页。\n"
        f"全书梗概：{logline}\n"
        f"角色：{names}\n"
        f"角色设定：{details}\n"
        "请把这一页拆成 1 个节拍（最多 2 个）。每个节拍包含：\n"
        "- description：这一页画面上发生了什么；\n"
        "- narration：这一页的旁白，可以直接朗读；\n"
        "- dialogues：角色台词，没有就给空数组；\n"
        "- entities：这一页出现的实体；\n"
        "- keywords：2-4 个孩子会怎么描述这一刻的短语（比如“城堡晃动”“两人吵架”），"
        "用中文写，因为用户用中文语音指令定位画面；\n"
        "- duration_ms：这一段大约多少毫秒（建议 6000）。\n"
        "只写画面里有的东西，不要编造。\n"
        f"{_language_rule(language)}\n"
        f"本页文字：{page_text or '（这一页没有文字层）'}\n"
        f"本页画面：{narrative or '（没有画面描述）'}"
    )


def _plan_book(llm: Any, book: BookPackage, digest: str, language: str) -> tuple[dict[str, Any], str]:
    result: VLMResult = llm.chat(_book_plan_prompt(book, digest, language), json_schema=BOOK_SCHEMA)
    data = result.data if isinstance(result.data, dict) else {}
    return data, str(result.text or "")


def run_story(spec: BookSpec, llm: Any) -> dict[str, Any]:
    book_path = DATA / spec.book_id / "book.json"
    if not book_path.exists():
        raise FileNotFoundError(book_path)
    out_dir = DATA / spec.book_id / "derived" / "story"
    plan_path = out_dir / "story_plan.json"
    available = llm.available()
    if not available and plan_path.is_file():
        # Never replace a good plan with the fallback version: the fallback is
        # for a missing model, not for a plan that was already written.
        return {
            "book_id": spec.book_id,
            "model": getattr(llm, "model", ""),
            "available": False,
            "skipped": True,
            "reason": "llm_unavailable_keeping_existing_plan",
            "plan_path": str(plan_path),
            "pages_llm": 0,
            "pages_fallback": 0,
            "characters": 0,
            "beats": 0,
            "errors": [],
            "seconds": 0.0,
        }
    book = BookPackage.model_validate(json.loads(book_path.read_text(encoding="utf-8")))

    narratives = {
        int(record["page_index"]): record
        for record in auto_narrative_records(spec.book_id)
        if record.get("page_index")
    }
    corrections = load_narrative_corrections(spec.book_id)
    for index, correction in corrections.items():
        narratives[index] = {
            **narratives.get(index, {}),
            "text": str(correction.get("text") or ""),
            "entities": list(correction.get("entities") or []),
            "source": "human",
        }

    started = time.perf_counter()
    report: dict[str, Any] = {
        "book_id": spec.book_id,
        "model": getattr(llm, "model", ""),
        "available": available,
        "pages_llm": 0,
        "pages_fallback": 0,
        "errors": [],
        "seconds": 0.0,
    }

    digest = _page_digest(book, narratives)
    book_data: dict[str, Any] = {}
    if available:
        try:
            book_data, _ = _plan_book(llm, book, digest, book.language)
        except Exception as exc:  # noqa: BLE001
            report["errors"].append({"stage": "book", "error": f"{type(exc).__name__}: {exc}"})

    logline = str(book_data.get("logline") or "").strip() or f"{book.title} 的故事"
    characters = _clean_characters(book_data.get("characters"), spec.book_id)
    style = _clean_style(book_data.get("style_bible"))

    pages: list[PageStory] = []
    keyword_map: dict[str, list[str]] = {}
    previous_state: str | None = None
    for page in book.pages:
        page_text = _story_page_text(page, book.language)
        narrative = str(
            narratives.get(page.index, {}).get("text") or ""
        ).strip()
        entities = _clean_list(
            narratives.get(page.index, {}).get("entities"),
            8,
        )
        fallback = _fallback_beats(
            spec.book_id,
            page.index,
            page_text,
            narrative,
            entities,
        )

        beats: list[Beat] = []
        if available:
            try:
                result = llm.chat(
                    _page_plan_prompt(
                        book,
                        page.index,
                        page_text,
                        narrative,
                        logline,
                        characters,
                        book.language,
                    ),
                    json_schema=BEAT_SCHEMA,
                )
                beats, keywords = _clean_beats(
                    spec.book_id,
                    page.index,
                    result.data,
                    fallback,
                )
                keyword_map.update(keywords)
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(
                    {
                        "page_index": page.index,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                beats = fallback
        else:
            beats = fallback

        if beats == fallback:
            report["pages_fallback"] += 1
        else:
            report["pages_llm"] += 1

        pages.append(
            PageStory(
                page_index=page.index,
                beats=beats,
                state_before=previous_state,
                state_after=beats[-1].description,
            )
        )
        previous_state = beats[-1].description

    plan = StoryPlan(
        book_id=spec.book_id,
        language=book.language,
        title=book.title,
        logline=logline,
        characters=characters,
        style_bible=style,
        pages=pages,
        model=getattr(llm, "model", "") or "fallback",
        prompt_version=PROMPT_VERSION,
        source_hash=content_hash(book.model_dump(mode="json")),
        created_at=_now(),
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(
        json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # Keywords are not part of the contract's Beat model; the scene stage reads
    # them to build the aliases that make `seek` work.
    (out_dir / "beat_keywords.json").write_text(
        json.dumps(keyword_map, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report["seconds"] = round(time.perf_counter() - started, 2)
    report["plan_path"] = str(plan_path)
    report["characters"] = len(characters)
    report["beats"] = sum(len(page.beats) for page in pages)
    (DATA / spec.book_id / "derived" / "story_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report

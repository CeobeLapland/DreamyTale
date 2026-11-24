"""Runtime LLM answer: the contract's `weak` tier.

When no QaCard matches, the service may still answer from the book itself:
retrieve the most relevant pages, give the model only that text, and require a
page citation. If the model cannot answer from the context, return None so the
caller falls back to the `guide` answer. No open-domain chat.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from contracts.models import BookPackage, Evidence
from contracts.retrieval import char_coverage, normalize, overlap_score, query_core
from pipeline.models import build_llm

from backend.app.guide import page_start_times

_SYSTEM = (
    "你是一名绘本伴读老师。只能依据给出的书中内容回答，不能使用书外知识，"
    "不能编造。答案要短，尽量用原文里的词；没有依据就说不知道。"
)

_REFUSALS = (
    "书中没有",
    "没有提到",
    "无法回答",
    "不知道",
    "抱歉",
    "未提及",
    "not mentioned",
    "cannot answer",
    "i don't know",
)

_BOILERPLATE = (
    "出版社",
    "出版",
    "内容中心著",
    "版权所有",
    "isbn",
    "阅读树",
    "分级读物",
)

_NUMBER_PHRASE = re.compile(
    r"([0-9零一二三四五六七八九十百千万两]+)\s*"
    r"(块|个|只|岁|页|次|位|张|本|条|朵|棵|颗|件|天|年|月|日)"
)

_provider = None
_provider_lock = Lock()


@dataclass(frozen=True)
class LLMAnswer:
    text: str
    page_index: int
    quote: str
    scene_id: str | None
    time_ms: int | None
    evidence: list[Evidence]
    latency_ms: int
    model: str


def _get_provider():
    global _provider
    if _provider is None:
        with _provider_lock:
            if _provider is None:
                _provider = build_llm()
    return _provider


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _narratives(package_root: Path) -> dict[int, str]:
    path = package_root / "derived" / "understanding" / "narrative.jsonl"
    if not path.is_file():
        return {}
    result: dict[int, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("status") == "active":
            result[int(record.get("page_index") or 0)] = str(record.get("text") or "")
    return result


def _story_by_page(package_root: Path) -> dict[int, str]:
    plan = _read_json(package_root / "derived" / "story" / "story_plan.json")
    result: dict[int, str] = {}
    for page in plan.get("pages", []) or []:
        chunks: list[str] = []
        for beat in page.get("beats", []) or []:
            for key in ("narration", "description"):
                text = str(beat.get(key) or "").strip()
                if text:
                    chunks.append(text)
        if chunks:
            result[int(page.get("page_index") or 0)] = " ".join(chunks)
    return result


def _scenes_by_page(package_root: Path) -> dict[int, dict]:
    plan = _read_json(package_root / "derived" / "scene" / "scene_plan.json")
    result: dict[int, dict] = {}
    for scene in plan.get("scenes", []) or []:
        page = int(scene.get("page_index") or 0)
        if page and page not in result:
            result[page] = scene
    return result


def _rank_pages(
    package: BookPackage,
    package_root: Path,
    question: str,
    limit: int = 4,
) -> list[tuple[int, float]]:
    core = query_core(question) or normalize(question)
    narratives = _narratives(package_root)
    stories = _story_by_page(package_root)
    recency = any(word in question for word in ("最后", "后来", "结尾", "终于", "end"))
    scored: list[tuple[int, float]] = []
    for page in package.pages:
        haystack = " ".join(
            [
                str(page.text or ""),
                narratives.get(page.index, ""),
                stories.get(page.index, ""),
            ]
        )
        text = normalize(haystack)
        if not text:
            continue
        score = overlap_score(core, text) * 1.0
        if core:
            score += char_coverage(core, text) * 2.0
        if recency:
            # "最后/后来" questions usually live on later pages; this only
            # breaks ties, it does not outrank a strong lexical match.
            score += page.index * 0.01
        if score > 0:
            scored.append((page.index, round(score, 3)))
    scored.sort(key=lambda item: item[1], reverse=True)
    if not scored:
        # No lexical overlap: let the model see the first pages rather than
        # refusing before it has read anything.
        return [(page.index, 0.0) for page in package.pages[:limit]]
    return scored[:limit]


def _context(package: BookPackage, package_root: Path, pages: list[int]) -> str:
    narratives = _narratives(package_root)
    stories = _story_by_page(package_root)
    by_index = {page.index: page for page in package.pages}
    blocks: list[str] = []
    for page_index in pages:
        page = by_index.get(page_index)
        if page is None:
            continue
        text = str(page.text or "").strip()
        narrative = narratives.get(page_index, "").strip()
        story = stories.get(page_index, "").strip()
        parts = [f"第 {page_index} 页"]
        if text:
            parts.append(f"正文：{text[:220]}")
        if narrative:
            parts.append(f"画面：{narrative[:220]}")
        if story:
            parts.append(f"旁白：{story[:220]}")
        blocks.append("；".join(parts))
    return "\n".join(blocks)


def _scene_for_page(package_root: Path, page_index: int) -> tuple[str | None, int | None]:
    scene = _scenes_by_page(package_root).get(page_index)
    if scene is None:
        start = page_start_times(package_root).get(page_index)
        return None, start
    starts = page_start_times(package_root)
    return str(scene.get("scene_id") or "") or None, starts.get(
        page_index, int(scene.get("start_ms") or 0)
    )


_SPLIT = re.compile(r"[。！？!?\n]+")


def _sentences_by_page(
    package: BookPackage,
    package_root: Path,
) -> list[tuple[int, str]]:
    narratives = _narratives(package_root)
    stories = _story_by_page(package_root)
    rows: list[tuple[int, str]] = []
    for page in package.pages:
        page_text = str(page.text or "")
        # Cover/title pages are a pile of labels, not sentences. Letting the
        # model cite them produces "作者是……出版社" nonsense.
        title_page = bool(page_text) and not re.search(r"[。！？!?，,.;；:：]", page_text)
        for source in (
            page_text,
            narratives.get(page.index, ""),
            stories.get(page.index, ""),
        ):
            if title_page and source == page_text:
                continue
            for sentence in _SPLIT.split(source):
                text = sentence.strip()
                if len(text) >= 4:
                    rows.append((page.index, text))
    return rows


def _cause_clause(answer: str) -> str:
    lowered = answer.lower()
    for marker in ("因为", "because"):
        index = lowered.find(marker)
        if index < 0:
            continue
        clause = answer[index + len(marker) :]
        for stop in ("所以", "，", ",", "。", "；", ";"):
            position = clause.find(stop)
            if position > 0:
                clause = clause[:position]
                break
        return clause.strip()
    return ""


def _character_names(package_root: Path) -> list[str]:
    plan = _read_json(package_root / "derived" / "story" / "story_plan.json")
    return [
        str(character.get("name") or "").strip()
        for character in plan.get("characters", []) or []
        if str(character.get("name") or "").strip()
    ]


def _number_phrases(text: str) -> set[str]:
    return {
        match.group(1) + match.group(2)
        for match in _NUMBER_PHRASE.finditer(text)
    }


def _ground(
    answer: str,
    question: str,
    package: BookPackage,
    package_root: Path,
) -> tuple[int, str] | None:
    """Find the sentence that supports the answer; None means unsupported."""
    normalized_answer = normalize(answer)
    core = query_core(question) or normalize(question)
    cause = normalize(_cause_clause(answer))
    required_numbers = _number_phrases(answer)
    characters = _character_names(package_root)
    question_characters = [name for name in characters if name in question]
    best: tuple[float, int, str] | None = None
    for page_index, sentence in _sentences_by_page(package, package_root):
        normalized_sentence = normalize(sentence)
        if not normalized_sentence:
            continue
        if any(phrase not in normalized_sentence for phrase in required_numbers):
            continue
        if question_characters:
            if not any(name in sentence for name in question_characters):
                # Do not cite a different character's sentence for this question.
                if any(name in sentence for name in characters):
                    continue
        overlap = overlap_score(normalized_answer, normalized_sentence)
        coverage = char_coverage(normalized_answer, normalized_sentence)
        if overlap < 2 and not (len(normalized_answer) >= 2 and coverage >= 0.6):
            continue
        if cause:
            cause_overlap = overlap_score(cause, normalized_sentence)
            cause_coverage = char_coverage(cause, normalized_sentence)
            if cause_overlap == 0 and cause_coverage < 0.5:
                continue
        score = overlap + coverage * 2 + overlap_score(core, normalized_sentence) * 0.5
        if best is None or score > best[0]:
            best = (score, page_index, sentence)
    if best is None:
        return None
    return best[1], best[2]


def _evidence_for(page, quote: str) -> Evidence:
    """bbox of the spans that make up the grounded sentence.

    A sentence may be split across several text spans ("高高积" + "木" +
    "倒一地花花很生气"). Unioning the spans whose text appears in the quote
    gives the player a real box instead of evidence with no location.
    """
    normalized = normalize(quote)
    spans = [
        span
        for span in page.text_spans
        if len(normalize(span.text)) >= 2 and normalize(span.text) in normalized
    ]
    if not spans:
        head = normalized[:10]
        for span in page.text_spans:
            if head and head in normalize(span.text):
                spans = [span]
                break
    if not spans:
        return Evidence(page_index=page.index, quote=quote[:120])
    boxes = [tuple(span.bbox_px) for span in spans]
    bbox = (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )
    return Evidence(
        page_index=page.index,
        bbox_px=bbox,
        span_id=spans[0].span_id,
        quote=quote[:120],
    )


def build_llm_answer(
    package: BookPackage,
    package_root: Path,
    question: str,
    language: str | None = None,
) -> LLMAnswer | None:
    """Answer from the book with an LLM; None means 'use the guide'."""
    if not question.strip() or not package.pages:
        return None
    if any(word in question.lower() for word in ("作者", "author")):
        authors = [str(author).strip() for author in package.authors if str(author).strip()]
        if not authors:
            return None
        quote = "、".join(authors)
        return LLMAnswer(
            text=f"作者是{quote}。",
            page_index=1,
            quote=quote,
            scene_id=None,
            time_ms=page_start_times(package_root).get(1),
            evidence=[Evidence(page_index=1, quote=quote)],
            latency_ms=0,
            model="book-metadata",
        )
    provider = _get_provider()
    if not provider.available():
        return None

    ranked = _rank_pages(package, package_root, question)
    context = _context(package, package_root, [page for page, _ in ranked])
    if not context:
        return None

    prompt = (
        f"问题：{question}\n\n"
        f"书中内容：\n{context}\n\n"
        "请只根据上面的书中内容回答。答案要短（中文不超过 40 字，英文不超过 30 词），"
        "尽量使用原文里的词。如果问数量，只回答最终数量，不要罗列过程。"
        "如果问原因，用“因为……”回答，原因必须是同一页文字或画面里的事件。"
        "如果书中没有依据，只回答“不知道”。不要复述问题，不要问回去，不要解释。"
    )
    started = time.perf_counter()
    try:
        result = provider.chat(prompt, system=_SYSTEM)
    except Exception:  # noqa: BLE001 - runtime must fall back, not crash
        return None
    latency_ms = int((time.perf_counter() - started) * 1000)
    answer = re.sub(r"^```(?:json)?|```$", "", str(result.text or ""), flags=re.I | re.M).strip()
    if not answer or len(answer) > 200:
        return None
    if any(marker in answer.lower() for marker in _REFUSALS):
        return None
    if any(marker in answer.lower() for marker in _BOILERPLATE):
        return None
    normalized_answer = normalize(answer)
    normalized_question = normalize(question)
    if not normalized_answer or normalized_answer in normalized_question:
        return None
    if answer.rstrip().endswith(("?", "？")):
        return None

    grounded = _ground(answer, question, package, package_root)
    if grounded is None:
        return None
    page_index, quote = grounded

    scene_id, time_ms = _scene_for_page(package_root, page_index)
    page = next(
        (item for item in package.pages if item.index == page_index), None
    )
    evidence = (
        [_evidence_for(page, quote)]
        if page is not None
        else [Evidence(page_index=page_index, bbox_px=None, span_id=None, quote=quote[:120])]
    )
    return LLMAnswer(
        text=answer,
        page_index=page_index,
        quote=quote[:120],
        scene_id=scene_id,
        time_ms=time_ms,
        evidence=evidence,
        latency_ms=latency_ms,
        model=getattr(provider, "model", "") or provider.name,
    )

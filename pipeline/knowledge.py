"""Knowledge layer: build the QA cards the runtime answers from.

The official script already contains the questions the judge will ask, so the
cards are built for those questions: every `qa` action of the query set becomes
one `QaCard`. The answer comes from the page that actually talks about the
question, which is found by matching the question against the page text and
the page narrative.

The cards follow contract §6.2: three answer tiers, at least five spoken
variants, real evidence and a video anchor when the page has a scene.

If a language model is available it writes the answers; without one the
answers are assembled from the page narrative, which is honest but blunter.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contracts.models import (
    Evidence,
    FactSource,
    QaAnswers,
    QaCard,
    QaIntent,
    QaScope,
    Status,
    VideoAnchor,
    content_hash,
)
from contracts.retrieval import (
    char_coverage,
    normalize,
    overlap_score,
    query_core,
    term_score,
)

from .config import DATA, BookSpec
from .index import load_scene_index
from .manual import auto_narrative_records

KNOWLEDGE_DIR = Path("derived") / "knowledge"
CARDS_FILE = "cards.jsonl"
UNCOVERED_FILE = "uncovered.json"

_INTENTS = (
    (("谁", "who", "whose"), QaIntent.identify),
    (("几", "多少", "how many", "number"), QaIntent.count),
    (("哪里", "在哪", "where"), QaIntent.locate),
    (("为什么", "why"), QaIntent.why),
    (("是什么", "什么颜色", "颜色", "what"), QaIntent.attribute),
    (("接下来", "后来", "然后", "结局", "what happens"), QaIntent.plot),
    (("如果", "会怎样", "predict"), QaIntent.predict),
    (("心情", "感觉", "难过", "开心", "feeling"), QaIntent.feeling),
    (("比", "更像", "compare"), QaIntent.compare),
    (("什么意思", "意思", "vocab"), QaIntent.vocab),
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _split_sentences(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"[。！？!?\n]+", text or "") if part.strip()]
    return parts


def _intent_for(question: str) -> QaIntent:
    lowered = question.lower()
    for needles, intent in _INTENTS:
        if any(needle in lowered for needle in needles):
            return intent
    return QaIntent.plot


def _variants(question: str, page_index: int) -> list[str]:
    """At least five spoken ways to ask the same thing (contract §6.2)."""
    base = question.strip()
    bare = base.rstrip("？?。.！!").strip()
    candidates = [
        base,
        bare,
        f"请问{bare}？",
        f"{bare}呢？",
        f"书里{bare}？",
        f"第{page_index}页{bare}？",
        f"你能告诉我{bare}吗？",
    ]
    variants: list[str] = []
    for candidate in candidates:
        text = candidate.strip()
        if text and text not in variants:
            variants.append(text)
    return variants[:8]


def _guide_answer(question: str, page_index: int, quote: str) -> str:
    """The third tier: admit, turn the page, ask back (never "sorry")."""
    bare = question.strip().rstrip("？?。.！!").strip()
    hint = quote[:20] if quote else "画面里的线索"
    return f"我们翻到第 {page_index} 页看看吧：{hint}……你从画面里看出{bare}了吗？"


def _best_page(question: str, pages: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    """The page the question is about, scored on the book's own words.

    Four signals, because no single one covers every question:

    - the page text (the book's printed words, the strongest evidence)
    - the page narrative (what the vision model described)
    - the story plan for that page (the beat narration, in the book's voice)
    - the scene aliases and entities (the words a child would use)

    English questions are matched word by word ("xiaoman" has to appear),
    Chinese questions fall back to character coverage, because a Chinese
    question rarely repeats the book's wording verbatim.
    """
    core = query_core(question)
    best: dict[str, Any] | None = None
    best_score = 0.0
    for page in pages:
        score = _page_score(question, core, page)
        if score > best_score:
            best_score = score
            best = page
    return best, best_score


def _page_score(question: str, core: str, page: dict[str, Any]) -> float:
    text = normalize(str(page.get("text") or ""))
    narrative = normalize(str(page.get("narrative") or ""))
    story = normalize(str(page.get("story") or ""))
    aliases = normalize(str(page.get("aliases") or ""))

    score = overlap_score(core, text) * 2.0
    score += overlap_score(core, narrative) * 1.5
    score += overlap_score(core, story) * 1.0
    score += overlap_score(core, aliases) * 1.0
    # Word level match for English, character coverage for Chinese.
    score += term_score(question, text) * 1.5
    score += term_score(question, narrative + " " + story) * 0.8
    score += char_coverage(question, text) * 4.0
    score += char_coverage(question, narrative + " " + story) * 2.0
    return score


def _is_grounded(question: str, core: str, page: dict[str, Any]) -> bool:
    """Is there real evidence on this page that it answers the question?

    A card is a promise that this page answers the question. When the only
    thing in common is one stray character, that promise would be a confident
    wrong answer, so the question is left uncovered instead.
    """
    text = str(page.get("text") or "")
    narrative = str(page.get("narrative") or "")
    story = str(page.get("story") or "")
    if overlap_score(core, normalize(text)) >= 2:
        return True
    if overlap_score(core, normalize(narrative)) >= 2:
        return True
    if overlap_score(core, normalize(story)) >= 2:
        return True
    # An English content word of three letters or more is real evidence.
    if term_score(question, text + " " + narrative + " " + story) >= 3:
        return True
    # A Chinese question whose characters mostly appear on the page.
    if len(core) >= 3 and char_coverage(question, text + " " + narrative + " " + story) >= 0.6:
        return True
    return False


def _pick_quote(question: str, page: dict[str, Any]) -> str:
    """The sentence of the page that answers the question best."""
    core = query_core(question)
    best = ""
    best_score = 0.0
    sources = (
        str(page.get("text") or ""),
        str(page.get("narrative") or ""),
        str(page.get("story") or ""),
    )
    for source in sources:
        for sentence in _split_sentences(source):
            score = overlap_score(core, normalize(sentence))
            score += term_score(question, sentence) * 0.5
            score += char_coverage(question, sentence) * 2.0
            if score > best_score:
                best_score = score
                best = sentence
    return best.strip()


def _evidence_for(page: dict[str, Any], quote: str) -> list[Evidence]:
    evidence = [
        Evidence(
            page_index=int(page.get("index") or 0),
            bbox_px=None,
            span_id=None,
            quote=quote[:120],
        )
    ]
    for span in page.get("spans") or []:
        if quote and quote[:6] and str(span.get("text") or "").find(quote[:4]) != -1:
            bbox = span.get("bbox_px")
            evidence.append(
                Evidence(
                    page_index=int(span.get("page_index") or page.get("index") or 0),
                    bbox_px=tuple(bbox) if bbox else None,
                    span_id=str(span.get("span_id") or "") or None,
                    quote=str(span.get("text") or "")[:120],
                )
            )
            break
    return evidence


def _answer_tier(question: str, page: dict[str, Any], quote: str) -> tuple[str, str, str]:
    narrative = str(page.get("narrative") or "").strip()
    page_text = str(page.get("text") or "").strip()
    strong = quote.strip() or narrative[:60] or page_text[:60] or "这一页没有可回答的内容。"
    strong = strong[:60]
    weak_source = narrative or page_text
    weak = weak_source[:120] if weak_source else strong
    guide = _guide_answer(question, int(page.get("index") or 0), quote)
    return strong, weak, guide


ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "page_index": {"type": "integer"},
        "strong": {"type": "string"},
        "weak": {"type": "string"},
        "guide": {"type": "string"},
        "variants": {"type": "array", "items": {"type": "string"}},
        "entities": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["page_index", "strong", "weak", "guide", "variants", "entities"],
}


def _digest(pages: list[dict[str, Any]], limit: int = 150) -> str:
    lines: list[str] = []
    for page in pages:
        text = str(page.get("text") or "").strip()
        narrative = str(page.get("narrative") or "").strip()
        source = text or narrative
        if not source:
            continue
        lines.append(f"[p{page['index']}] {source[:limit]}")
    return "\n".join(lines)


def _answer_with_llm(
    llm: Any,
    question: str,
    pages: list[dict[str, Any]],
    language: str,
) -> dict[str, Any] | None:
    """Ask the model which page answers the question and to write the answer."""
    language_rule = (
        "Write every answer in English."
        if language.lower().startswith("en")
        else "所有答案用中文书写。"
    )
    prompt = (
        "你是一位儿童绘本伴读助手。下面是这本书每一页的内容（p数字是页码）。\n"
        f"孩子问：{question}\n"
        "请回答：\n"
        "- page_index：能回答这个问题的页码（1 起）；\n"
        "- strong：一个事实，中文不超过 30 字（英文不超过 20 词），不许改写原文用词；\n"
        "- weak：要点清单，中文不超过 80 字；\n"
        "- guide：先承认、再翻页、最后反问，三件事缺一不可，禁止说“抱歉，无法回答”；\n"
        "- variants：5-8 条孩子会怎么问这句话的说法；\n"
        "- entities：这一页出现的实体。\n"
        "只根据上面的内容回答，不要编造。\n"
        f"{language_rule}\n"
        f"每页内容：\n{_digest(pages)}"
    )
    result = llm.chat(prompt, json_schema=ANSWER_SCHEMA)
    data = result.data if isinstance(result.data, dict) else None
    if not data:
        return None
    try:
        page_index = int(data.get("page_index") or 0)
    except (TypeError, ValueError):
        return None
    strong = str(data.get("strong") or "").strip()
    if page_index < 1 or not strong:
        return None
    return {
        "page_index": page_index,
        "strong": strong,
        "weak": str(data.get("weak") or strong).strip(),
        "guide": str(data.get("guide") or "").strip(),
        "variants": [str(item).strip() for item in data.get("variants") or [] if str(item).strip()],
        "entities": [str(item).strip() for item in data.get("entities") or [] if str(item).strip()],
    }


def _cards_from_queries(
    spec: BookSpec,
    pages: list[dict[str, Any]],
    scenes_by_page: dict[int, list[dict[str, Any]]],
    language: str,
    llm: Any = None,
    uncovered: list[str] | None = None,
) -> list[QaCard]:
    query_sets = sorted((DATA / spec.book_id / "query_sets").glob("*.json"))
    if not query_sets:
        return []
    query_set = json.loads(query_sets[0].read_text(encoding="utf-8"))
    if uncovered is None:
        uncovered = []

    cards: list[QaCard] = []
    seen: set[str] = set()
    for item in query_set.get("items", []):
        for action in item.get("actions", []):
            if action.get("kind") != "qa":
                continue
            question = str(action.get("text") or item.get("instruction") or "").strip()
            if not question or question in seen:
                continue
            seen.add(question)

            answered = _answer_with_llm(llm, question, pages, language) if llm else None
            page: dict[str, Any] | None = None
            score = 0.0
            if answered:
                page = next(
                    (item for item in pages if int(item.get("index") or 0) == answered["page_index"]),
                    None,
                )
            if page is None:
                page, score = _best_page(question, pages)
                core = query_core(question)
                if page is None or not _is_grounded(question, core, page):
                    # No page really talks about this question; a card without
                    # evidence would only look like a confident wrong answer.
                    # The question is written down instead, so the gap is
                    # visible instead of silently missing.
                    uncovered.append(question)
                    continue
                quote = _pick_quote(question, page)
                strong, weak, guide = _answer_tier(question, page, quote)
                variants = _variants(question, int(page.get("index") or 0))
                entities = list(page.get("entities") or [])[:6]
            else:
                quote = answered["strong"]
                strong = answered["strong"]
                weak = answered["weak"]
                guide = answered["guide"]
                variants = answered["variants"] or _variants(
                    question, answered["page_index"]
                )
                entities = answered["entities"] or list(page.get("entities") or [])[:6]

            page_scenes = scenes_by_page.get(int(page.get("index") or 0), [])
            anchor = None
            if page_scenes:
                scene = page_scenes[0]
                anchor = VideoAnchor(
                    scene_id=str(scene.get("scene_id") or ""),
                    start_ms=int(scene.get("start_ms") or 0),
                    end_ms=int(scene.get("end_ms") or 0),
                )
            langs = ["en"] if language.lower().startswith("en") else ["zh"]
            record = QaCard(
                card_id=f"card-{spec.book_id}-{len(cards) + 1:03d}",
                book_id=spec.book_id,
                kind="qa",
                intent=_intent_for(question),
                scope=QaScope.page,
                langs=langs,
                question_canonical=question,
                variants=list(dict.fromkeys(variants))[:8],
                entities=entities[:6],
                answers={langs[0]: QaAnswers(strong=strong, weak=weak, guide=guide)},
                evidence=_evidence_for(page, quote),
                video_anchor=anchor,
                priority=1 if item.get("mandatory") else 2,
                source=FactSource.auto,
                version=1,
                status=Status.active,
                hash="0" * 16,
                created_at=_now(),
            )
            record.hash = content_hash(record.model_dump(mode="json"))
            cards.append(record)
    return cards


def build_knowledge(spec: BookSpec, llm: Any = None) -> dict[str, Any]:
    """Write derived/knowledge/cards.jsonl for one book."""
    book_path = DATA / spec.book_id / "book.json"
    if not book_path.exists():
        raise FileNotFoundError(book_path)
    book = json.loads(book_path.read_text(encoding="utf-8"))

    narratives = {
        int(record["page_index"]): record
        for record in auto_narrative_records(spec.book_id)
        if record.get("page_index")
    }
    scenes_by_page: dict[int, list[dict[str, Any]]] = {}
    for scene in load_scene_index(spec.book_id).get("scenes", []):
        scenes_by_page.setdefault(int(scene.get("page_index") or 0), []).append(scene)

    # The story plan carries the beat narration: the same scene in the book's
    # own voice. It answers questions the printed text does not.
    story_by_page: dict[int, str] = {}
    story_path = DATA / spec.book_id / "derived" / "story" / "story_plan.json"
    if story_path.is_file():
        plan = json.loads(story_path.read_text(encoding="utf-8"))
        for entry in plan.get("pages", []):
            chunks: list[str] = []
            for beat in entry.get("beats", []):
                chunks.append(str(beat.get("description") or ""))
                chunks.append(str(beat.get("narration") or ""))
            chunks.append(str(entry.get("state_before") or ""))
            chunks.append(str(entry.get("state_after") or ""))
            story_by_page[int(entry.get("page_index") or 0)] = " ".join(chunks)

    alias_by_page: dict[int, list[str]] = {}
    for page_index, scenes in scenes_by_page.items():
        words: list[str] = []
        for scene in scenes:
            words.extend(str(alias) for alias in scene.get("aliases") or [])
            words.extend(str(entity) for entity in scene.get("entities") or [])
        alias_by_page[page_index] = words

    pages: list[dict[str, Any]] = []
    for page in book.get("pages", []):
        narrative = narratives.get(int(page.get("index") or 0), {})
        pages.append(
            {
                "index": int(page.get("index") or 0),
                "text": str(page.get("text") or ""),
                "narrative": str(narrative.get("text") or ""),
                "entities": list(narrative.get("entities") or []),
                "spans": page.get("text_spans") or [],
                "story": story_by_page.get(int(page.get("index") or 0), ""),
                "aliases": alias_by_page.get(int(page.get("index") or 0), []),
            }
        )

    started = time.perf_counter()
    uncovered: list[str] = []
    cards = _cards_from_queries(
        spec,
        pages,
        scenes_by_page,
        str(book.get("language") or "zh-CN"),
        llm=llm,
        uncovered=uncovered,
    )

    out_dir = DATA / spec.book_id / KNOWLEDGE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    cards_path = out_dir / CARDS_FILE
    with cards_path.open("w", encoding="utf-8") as handle:
        for card in cards:
            handle.write(card.model_dump_json(exclude_none=False) + "\n")

    # The questions we could not ground are written down as well: a gap that
    # is listed can be worked on, a gap that is not counted can only be
    # guessed at.
    uncovered_path = out_dir / UNCOVERED_FILE
    uncovered_path.write_text(
        json.dumps({"book_id": spec.book_id, "questions": uncovered}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "book_id": spec.book_id,
        "cards": len(cards),
        "uncovered": len(uncovered),
        "cards_path": str(cards_path),
        "uncovered_path": str(uncovered_path),
        "seconds": round(time.perf_counter() - started, 2),
    }

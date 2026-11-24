"""引导式回答：问题没有答案卡时，仍然给得出可看的东西。

契约 §6.2 规定 `guide` 这一档必须三件事缺一不可：**承认 + 翻页 + 反问**，
并且禁止"抱歉，我无法回答"。`docs/ARCHITECTURE.md` §4.5 把它写成降级链的一环：

    qa 无命中 → 引用原句 → 引导（承认 + 翻页 + 反问）

分工上，这里**不做任何检索**：

- 命中问答卡时，答案、该引哪句、该翻到第几页，都是 pipeline 早就烘焙在
  `QaCard.answers.guide` 和 `QaCard.video_anchor` 里的，运行时读出来即可。
- 没有卡时，正确的动作是**留在孩子正在看的那一页**，引这一页的原句，
  把问题还给他。翻到哪一页不是运行时该猜的事——猜错了比不翻更糟。

所以这个模块只做一件事：把"当前页 + 这一页的原句"组织成契约要求的三段话。
找不到原句就只说承认和翻页，绝不编一句话出来。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.models import BookPackage, Evidence

_SENTENCE_SPLIT = re.compile(r"[。！？!?\n]+")

# 引用原句时，单个字没有指向性；短于这个长度的片段多半是页码或页眉。
_MIN_QUOTE_LENGTH = 8
_MAX_QUOTE_LENGTH = 60


@dataclass(frozen=True, slots=True)
class GuideAnswer:
    """一次引导：文字、翻页动作、证据。"""

    text: str
    page_index: int
    scene_id: str | None
    time_ms: int | None
    evidence: list[Evidence]


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(text or "") if part.strip()]


def page_start_times(package_root: Path) -> dict[int, int]:
    """每一页在全书视频里的起始时间（毫秒，全书绝对时间）。

    `Scene.start_ms` 是相对页面的，播放器要的是全书绝对时间，
    两者差一个页偏移。不换算的话每次定位都落在第 0 毫秒，也就是第一页。
    """
    path = package_root / "derived" / "scene" / "timeline.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    starts: dict[int, int] = {}
    for page in data.get("pages", []) or []:
        try:
            starts[int(page["page_index"])] = int(page.get("start_ms") or 0)
        except (KeyError, TypeError, ValueError):
            continue
    return starts


def _narratives_by_page(package_root: Path) -> dict[int, str]:
    """每一页的视觉模型叙述（纯图绘本没有文字层时用得上）。"""
    path = package_root / "derived" / "understanding" / "narrative.jsonl"
    if not path.is_file():
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    result: dict[int, str] = {}
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(record, dict)
            and record.get("status") == "active"
            and record.get("page_index") is not None
        ):
            result[int(record["page_index"])] = str(record.get("text") or "")
    return result


def _quote_of(page: Any) -> tuple[str, Evidence | None]:
    """这一页的第一句成话的原句，连同它在页图上的位置。

    只取第一句，不做挑选：既然已经决定停在这一页，
    念这一页的开头那句就够了，挑来挑去又是检索。
    """
    text = str(getattr(page, "text", "") or "")
    sentences = [
        sentence for sentence in _sentences(text) if len(sentence) >= _MIN_QUOTE_LENGTH
    ]
    if not sentences:
        return "", None

    quote = sentences[0]
    evidence = Evidence(
        page_index=int(getattr(page, "index", 0) or 0),
        bbox_px=None,
        span_id=None,
        quote=quote[:120],
    )
    # 句子的开头通常落在某一个 span 上，用它把证据框定位到页图上。
    head = quote[:6]
    for span in getattr(page, "text_spans", []) or []:
        span_text = str(getattr(span, "text", "") or "")
        if not span_text:
            continue
        if span_text in quote or head.startswith(span_text):
            evidence = Evidence(
                page_index=int(getattr(span, "page_index", 0) or 0) or evidence.page_index,
                bbox_px=tuple(span.bbox_px) if getattr(span, "bbox_px", None) else None,
                span_id=str(getattr(span, "span_id", "") or "") or None,
                quote=quote[:120],
            )
            break
    return quote, evidence


def _trim(quote: str, limit: int = _MAX_QUOTE_LENGTH) -> str:
    """截到句子边界，不要把词截断半截。"""
    if len(quote) <= limit:
        return quote
    cut = quote[:limit]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip("，,、;； ")


def _compose(language: str, page_index: int, quote: str, question: str) -> str:
    """承认 + 翻页 + 反问，三件事都在。

    引得到原句就引；引不到就不引——宁可少一句，也不能编一句。
    """
    tail = (question or "").strip().rstrip("？?。.!！").strip()
    if language.lower().startswith("en"):
        parts = [
            "I could not find a line in this book that answers that directly.",
            f"Let's turn to page {page_index}",
        ]
        if quote:
            parts[-1] += f": {quote}"
        parts.append(f"What do you see that answers “{tail}”?")
        return " ".join(parts)

    parts = [
        "这本书里我没有找到直接回答这个问题的句子。",
        f"我们翻到第 {page_index} 页看看",
    ]
    if quote:
        parts[-1] += f"：{quote.rstrip('。！？.!? ')}。"
    parts.append(f"你从画面里能看出{tail}吗？")
    return "".join(parts)


def build_guide_answer(
    package: BookPackage,
    package_root: Path,
    question: str,
    language: str | None,
    current_page: int | None = None,
    page_index: int | None = None,
    scene_id: str | None = None,
) -> GuideAnswer | None:
    """为没有答案卡的问题做一次引导。

    停在孩子正在看的那一页（`current_page`）；调用方若已经从卡片
    拿到了确定的页码与场景，直接传 `page_index` / `scene_id` 即可。
    """
    if not package.pages:
        return None

    spoken = language or package.language or "zh-CN"

    target = page_index or current_page
    if target is None:
        target = package.pages[0].index
    page = next((item for item in package.pages if item.index == target), None)
    if page is None:
        return None

    quote, evidence = _quote_of(page)
    if not quote:
        # 这一页没有成句的文字（纯图绘本）：改用画面描述，
        # 让孩子至少知道这一页画了什么。
        narrative = _narratives_by_page(package_root).get(target, "")
        if narrative:
            quote = narrative
            evidence = Evidence(
                page_index=target, bbox_px=None, span_id=None, quote=quote[:120]
            )

    starts = page_start_times(package_root)
    return GuideAnswer(
        text=_compose(spoken, target, _trim(quote), question),
        page_index=target,
        scene_id=scene_id,
        time_ms=starts.get(target, 0),
        evidence=[evidence] if evidence is not None else [],
    )

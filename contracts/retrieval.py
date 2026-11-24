"""Retrieval helpers shared by the pipeline and the backend.

Pure functions on plain data, no file paths and no imports from either side:
the pipeline builds the index, the backend serves the same index, and both
must answer a query the same way (otherwise the coverage report would promise
more than the API can do).
"""

from __future__ import annotations

import re
from typing import Any

STOPWORDS = (
    "找到",
    "看一下",
    "看看",
    "找一下",
    "请",
    "一下",
    "画面",
    "场景",
    "片段",
    "部分",
    "视频",
    "那个",
    "这个",
    "的那",
    "的",
    "里",
    "中",
    "页",
    "地",
    "和",
    "与",
    "并",
    "在",
    "到",
    "有",
    "上",
)


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", "", text)
    return text.strip("“”\"'‘’ ")


QUESTION_WORDS = (
    "是什么",
    "为什么",
    "是不是",
    "什么",
    "哪里",
    "哪儿",
    "怎么",
    "怎样",
    "多少",
    "谁",
    "几",
    "吗",
    "呢",
    "呀",
    "啊",
)


def query_core(query: str) -> str:
    """Strip the instruction and question words so only the content is left.

    "他们在搭什么？" -> "他们在搭": the question word would otherwise match any
    page that happens to contain "什么".
    """
    text = normalize(query)
    for word in STOPWORDS:
        text = text.replace(word, " ")
    for word in QUESTION_WORDS:
        text = text.replace(word, " ")
    return re.sub(r"\s+", "", text)


def longest_common_substring(left: str, right: str) -> int:
    if not left or not right:
        return 0
    previous = [0] * (len(right) + 1)
    best = 0
    for i in range(1, len(left) + 1):
        current = [0] * (len(right) + 1)
        for j in range(1, len(right) + 1):
            if left[i - 1] == right[j - 1]:
                current[j] = previous[j - 1] + 1
                if current[j] > best:
                    best = current[j]
        previous = current
    return best


def overlap_score(core: str, searchable: str) -> int:
    """How much of the query is covered by the candidate text.

    A greedy longest-match scan: every position takes the longest phrase (4, 3
    then 2 characters) that the candidate contains, and those characters are
    consumed. Counting every match instead of only the longest one is what
    separates "搭了九块积木" (九块 + 积木) from a scene that merely says "积木".
    """
    if not core or not searchable:
        return 0
    score = 0
    index = 0
    while index < len(core):
        for size in (4, 3, 2):
            if index + size > len(core):
                continue
            if core[index : index + size] in searchable:
                score += size
                index += size
                break
        else:
            index += 1
    return score


INSTRUCTION_PREFIXES = (
    "请帮我",
    "帮我",
    "请",
    "查找一下",
    "查找",
    "找一下",
    "搜索一下",
    "搜索",
    "高亮文字",
    "高亮",
    "显示",
    "找到",
)

INSTRUCTION_SUFFIXES = (
    "的画面",
    "这个画面",
    "那部分",
    "这个部分",
    "片段",
    "画面",
    "场景",
    "视频",
    "部分",
    "这一段",
    "这句",
    "这句话",
    "文字",
)

_QUOTE_PAIRS = (("“", "”"), ("「", "」"), ("『", "』"), ('"', '"'), ("'", "'"))


def extract_target(text: str) -> str:
    """The thing the user wants to find, without the instruction around it.

    "高亮文字“bats”" -> "bats"; "找到搭了九块积木的画面" -> "搭了九块积木".
    Without this the service searches for the whole sentence and finds
    nothing, which looks like a missing feature instead of a parsing gap.
    """
    stripped = (text or "").strip()
    if not stripped:
        return ""
    for opener, closer in _QUOTE_PAIRS:
        if opener == closer:
            if stripped.count(opener) >= 2:
                inner = stripped.split(opener)[1]
                if inner.strip():
                    return inner.strip()
            continue
        start = stripped.find(opener)
        if start != -1:
            end = stripped.find(closer, start + 1)
            if end != -1:
                inner = stripped[start + 1 : end].strip()
                if inner:
                    return inner
    for prefix in INSTRUCTION_PREFIXES:
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :].strip()
            break
    for suffix in INSTRUCTION_SUFFIXES:
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)].strip()
            break
    return stripped.strip("“”\"'‘’ 　")


def search_index(index: dict[str, Any], query: str) -> list[dict[str, Any]]:
    """Entries whose text contains the query."""
    needle = normalize(query)
    if not needle:
        return []
    hits: list[dict[str, Any]] = []
    for entry in index.get("entries", []) or []:
        if needle in normalize(str(entry.get("text") or "")):
            hits.append(entry)
    return hits


def find_scene(index: dict[str, Any], query: str) -> dict[str, Any] | None:
    """Best scene for a free text query.

    Exact alias matches win; otherwise the scene whose caption, subtitles and
    page narrative share the longest common substring with the query wins.
    """
    needle = normalize(query)
    if not needle:
        return None
    core = query_core(query) or needle
    best: dict[str, Any] | None = None
    best_score = 0
    for scene in index.get("scenes", []) or []:
        searchable = normalize(str(scene.get("text") or scene.get("caption") or ""))
        # How much of the query the scene covers decides; a short alias that
        # happens to appear ("积木") must not outrank a scene that covers the
        # whole phrase ("搭了九块积木").
        primary = overlap_score(core, searchable) if searchable else 0
        tiebreak = 0
        for alias in scene.get("aliases") or []:
            alias_text = normalize(str(alias))
            if alias_text and (alias_text == needle or alias_text in needle or needle in alias_text):
                tiebreak = max(tiebreak, len(alias_text))
        for entity in scene.get("entities") or []:
            entity_text = normalize(str(entity))
            if entity_text and (entity_text == needle or needle in entity_text):
                tiebreak = max(tiebreak, len(entity_text))
        if not primary:
            primary = longest_common_substring(core, searchable)
        score = primary * 10 + min(tiebreak, 9)
        if score > best_score:
            best_score = score
            best = scene
    if best is not None and best_score >= 20:
        return best
    return None

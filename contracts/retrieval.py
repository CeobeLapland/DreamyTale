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


def query_core(query: str) -> str:
    """Strip the instruction words so only the content of the query is left."""
    text = normalize(query)
    for word in STOPWORDS:
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
        score = 0
        for alias in scene.get("aliases") or []:
            alias_text = normalize(str(alias))
            if alias_text and (alias_text == needle or alias_text in needle or needle in alias_text):
                score = max(score, len(alias_text) + 2)
        for entity in scene.get("entities") or []:
            entity_text = normalize(str(entity))
            if entity_text and (entity_text == needle or needle in entity_text):
                score = max(score, len(entity_text) + 1)
        searchable = normalize(str(scene.get("text") or scene.get("caption") or ""))
        if searchable:
            score = max(score, longest_common_substring(core, searchable))
        if score > best_score:
            best_score = score
            best = scene
    if best is not None and best_score >= 3:
        return best
    return None

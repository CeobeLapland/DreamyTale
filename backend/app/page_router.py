"""Runtime cross-lingual page routing.

Click hotspots are resolved offline; seek is resolved online. When a Chinese
seek phrase ("找到电影海报的画面") meets an English scene caption ("a movie
poster on the wall"), lexical matching returns nothing. This module asks the
text model to pick the page from the book's own page descriptions, and the
caller then chooses a scene on that page. If the model cannot find evidence,
the caller keeps its normal guide/fallback path.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from backend.app.models import BookPackage
from pipeline.models import build_llm

PAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "page_index": {"type": "integer"},
        "found": {"type": "boolean"},
    },
    "required": ["page_index", "found"],
}

_provider = None
_provider_lock = Lock()


def _get_provider():
    global _provider
    if _provider is None:
        with _provider_lock:
            if _provider is None:
                _provider = build_llm()
    return _provider


def _read_narratives(package_root: Path) -> dict[int, str]:
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


def _scene_captions(package_root: Path) -> dict[int, list[str]]:
    path = package_root / "derived" / "scene" / "scene_plan.json"
    if not path.is_file():
        return {}
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    result: dict[int, list[str]] = {}
    for scene in plan.get("scenes", []) or []:
        page = int(scene.get("page_index") or 0)
        caption = str(scene.get("caption") or "").strip()
        if page and caption:
            result.setdefault(page, []).append(caption)
    return result


def route_page(
    package: BookPackage,
    package_root: Path | None,
    target: str,
) -> int | None:
    """Pick the page that most likely shows `target`; None means no evidence."""
    if not target.strip() or package_root is None or not package.pages:
        return None
    provider = _get_provider()
    if not provider.available():
        return None

    narratives = _read_narratives(package_root)
    captions = _scene_captions(package_root)
    rows: list[str] = []
    for page in package.pages:
        parts = [
            str(page.text or "").strip(),
            narratives.get(page.index, ""),
            " ".join(captions.get(page.index, [])),
        ]
        description = " ".join(part for part in parts if part)
        if description:
            rows.append(f"第 {page.index} 页：{description[:300]}")
    if not rows:
        return None

    prompt = (
        f"用户想找绘本里的“{target}”。下面是每一页的正文、画面描述和分镜说明。\n"
        "请判断这个对象/场景最可能出现在第几页；只依据描述，不要猜。\n\n"
        + "\n".join(rows)
        + "\n\n返回 JSON：{\"page_index\": 5, \"found\": true}。"
        "找不到就返回 {\"page_index\": 0, \"found\": false}。"
    )
    try:
        result = provider.chat(prompt, json_schema=PAGE_SCHEMA)
    except Exception:  # noqa: BLE001 - seek must degrade, not crash
        return None
    data = result.data if isinstance(result.data, dict) else None
    if not data or not data.get("found"):
        return None
    try:
        page_index = int(data.get("page_index") or 0)
    except (TypeError, ValueError):
        return None
    return page_index if any(page.index == page_index for page in package.pages) else None

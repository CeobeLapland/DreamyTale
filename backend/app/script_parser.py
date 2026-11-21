"""命题组脚本 -> v2 QuerySet。

v2 把脚本从 `book.json` 拆成独立产物（docs/DATA_CONTRACT.md §5、§13），
本模块负责三件事：把中文动作分类成 `QueryKind`、按契约要求填齐每个 kind 的必填字段、
把 QuerySet 落到 `query_sets/<book_id>-script-v1.json`（与 pipeline 产物同名同构）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from backend.app.models import (
    ControlAction,
    QueryAction,
    QueryItem,
    QueryKind,
    QueryLang,
    QuerySet,
    QuerySetSource,
)


_STEP_PATTERN = re.compile(r"^\s*(\d+)\.\s*(.*?)\s*$")
_MANDATORY_PATTERN = re.compile(r"[（(]\s*必选\s*[）)]")
_CLICK_PATTERN = re.compile(r"\[点击\]\s*(.*?)(?:\s*\|\s*(.*))?$")
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")
_LATIN_PATTERN = re.compile(r"[A-Za-z]")
_SEARCH_PREFIX_PATTERN = re.compile(
    r"^(查找|搜索|find(\s+the)?(\s+(text|words?))?)\s*",
    re.IGNORECASE,
)
_QUOTE_PATTERN = re.compile(r"[“\"]([^”\"]+)[”\"]")

# v1 的动作类型 -> v2 的 QueryKind；v2 没有 "other"，非受控动作一律落到 qa。
_LEGACY_KINDS = {
    "control": QueryKind.control,
    "find_scene": QueryKind.seek,
    "search_text": QueryKind.search,
    "highlight": QueryKind.highlight,
    "click": QueryKind.click,
    "question": QueryKind.qa,
    "other": QueryKind.qa,
}

_CONTROL_KEYWORDS: tuple[tuple[str, ControlAction], ...] = (
    ("结束", ControlAction.stop),
    ("停止", ControlAction.stop),
    ("继续", ControlAction.resume),
    ("恢复", ControlAction.resume),
    ("暂停", ControlAction.pause),
    ("播放", ControlAction.play),
)

_CONTROL_EXACT: dict[str, ControlAction] = {
    "播放": ControlAction.play,
    "play": ControlAction.play,
    "暂停": ControlAction.pause,
    "pause": ControlAction.pause,
    "继续": ControlAction.resume,
    "resume": ControlAction.resume,
    "结束播放": ControlAction.stop,
    "停止播放": ControlAction.stop,
    "stop": ControlAction.stop,
}


def _detect_lang(text: str) -> QueryLang:
    has_cjk = bool(_CJK_PATTERN.search(text))
    has_latin = bool(_LATIN_PATTERN.search(text))
    if has_cjk and has_latin:
        return QueryLang.mixed
    if has_cjk:
        return QueryLang.zh
    if has_latin:
        return QueryLang.en
    return QueryLang.mixed


def _control_action(text: str) -> ControlAction | None:
    """从中文/英文指令里解出播放控制动作；解不出就返回 None。"""
    normalized = text.strip().lower().rstrip("。.！!？?")
    exact = _CONTROL_EXACT.get(normalized)
    if exact is not None:
        return exact
    for keyword, action in _CONTROL_KEYWORDS:
        if keyword in normalized:
            return action
    return None


def _classify(text: str, last_search_text: str | None = None) -> QueryKind:
    """保留 v1 的中文分类逻辑，映射到 v2 的 kind 枚举。

    和 pipeline 的判定保持一致：带引号的“找到 xxx”当成文字检索，其余“找到”当成画面跳转。
    """
    normalized = text.strip().lower()
    if normalized.startswith("[点击]"):
        return QueryKind.click
    if _control_action(text) is not None:
        return QueryKind.control
    if "高亮" in normalized:
        return QueryKind.highlight
    if "查找" in normalized:
        return QueryKind.search
    if "找到" in normalized or normalized.startswith("find") or normalized.startswith("show me"):
        if _extract_quote(text) and "画面" not in text:
            return QueryKind.search
        return QueryKind.seek
    if text.rstrip().endswith(("?", "？")):
        return QueryKind.qa
    # v1 的 "other" 在 v2 没有对应枚举，兜底成问答交给理解阶段。
    return QueryKind.qa


def classify_instruction(text: str) -> QueryKind:
    """对外暴露的动作分类（交互路由和脚本解析共用同一套判断）。"""
    return _classify(text)


def control_action_for(text: str) -> ControlAction | None:
    """从指令里解出播放控制动作；解不出返回 None。"""
    return _control_action(text)


def _extract_quote(text: str) -> str | None:
    match = _QUOTE_PATTERN.search(text)
    return match.group(1).strip() if match else None


def _search_text(text: str) -> str:
    quote = _extract_quote(text)
    if quote:
        return quote
    value = _SEARCH_PREFIX_PATTERN.sub("", text)
    value = value.replace("几个字", "").replace("文字", "").strip()
    return value.strip("“”\"' ")


def _highlight_text(text: str, last_search_text: str | None = None) -> str:
    quote = _extract_quote(text)
    if quote:
        return quote
    value = re.sub(r"^高亮\s*", "", text).strip()
    value = value.strip("“”\"' ")
    # “高亮这句话”这类指代句沿用上一步的检索目标，和 pipeline 行为一致。
    if not value or value == "这句话":
        return last_search_text or "这句话"
    return value


def _click_target(text: str) -> str | None:
    match = _CLICK_PATTERN.search(text)
    if match is None:
        return None
    target = match.group(1).strip()
    if target.startswith("点击"):
        target = target.removeprefix("点击").strip()
    return target or None


def _required_fields(
    kind: QueryKind,
    text: str,
    target: str | None,
    last_search_text: str | None = None,
) -> dict[str, Any]:
    """按契约补齐 kind 对应的必填字段。"""
    if kind is QueryKind.control:
        action = _control_action(text)
        if action is None:
            return {}
        return {"control_action": action}
    if kind is QueryKind.seek:
        return {"seek_query": text}
    if kind is QueryKind.search:
        return {"search_text": _search_text(text)}
    if kind is QueryKind.highlight:
        return {"highlight_text": _highlight_text(text, last_search_text)}
    if kind is QueryKind.click:
        return {"target": target}
    return {}


def _build_action(
    action_id: str,
    kind: QueryKind,
    text: str,
    *,
    mandatory: bool,
    target: str | None = None,
    last_search_text: str | None = None,
) -> QueryAction:
    extra = _required_fields(kind, text, target, last_search_text)
    if kind is QueryKind.control and "control_action" not in extra:
        # 契约要求 control 必须带 control_action；解不出来就降级成问答，不编一个动作。
        kind = QueryKind.qa
        extra = {}
    return QueryAction(
        action_id=action_id,
        kind=kind,
        text=text,
        mandatory=mandatory,
        **extra,
    )


def parse_script_items(text: str, *, book_id: str) -> list[QueryItem]:
    """把脚本正文拆成 v2 QueryItem 列表。"""
    entries: list[dict[str, Any]] = []
    seen_numbers: set[int] = set()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        step_match = _STEP_PATTERN.match(line)
        if step_match:
            number = int(step_match.group(1))
            if number in seen_numbers:
                raise ValueError(f"Duplicate script step number {number}")
            seen_numbers.add(number)
            raw = step_match.group(2)
            entries.append(
                {
                    "number": number,
                    "instruction": _MANDATORY_PATTERN.sub("", raw).strip(),
                    "mandatory": bool(_MANDATORY_PATTERN.search(raw)),
                    "extra": [],
                }
            )
            continue

        if not entries:
            continue

        mandatory = bool(_MANDATORY_PATTERN.search(line))
        cleaned = _MANDATORY_PATTERN.sub("", line).strip()
        entries[-1]["extra"].append((cleaned, mandatory))
        entries[-1]["mandatory"] = entries[-1]["mandatory"] or mandatory

    items: list[QueryItem] = []
    last_search_text: str | None = None
    for entry in entries:
        number = entry["number"]
        instruction = entry["instruction"]
        query_id = f"{book_id}-q{number:03d}"
        kind = _classify(instruction, last_search_text)
        actions = [
            _build_action(
                f"{query_id}-a01",
                kind,
                instruction,
                mandatory=bool(entry["mandatory"]),
                last_search_text=last_search_text,
            )
        ]
        if kind is QueryKind.search:
            last_search_text = _search_text(instruction)
        for position, (extra_text, extra_mandatory) in enumerate(entry["extra"], start=2):
            kind = _classify(extra_text, last_search_text)
            target = _click_target(extra_text) if kind is QueryKind.click else None
            actions.append(
                _build_action(
                    f"{query_id}-a{position:02d}",
                    kind,
                    extra_text,
                    mandatory=extra_mandatory,
                    target=target,
                    last_search_text=last_search_text,
                )
            )
        items.append(
            QueryItem(
                query_id=query_id,
                number=number,
                instruction=instruction,
                audio_path=None,
                mandatory=bool(entry["mandatory"]),
                lang=_detect_lang(instruction),
                actions=actions,
                expected=None,
            )
        )
    return items


def build_query_set(
    items: Iterable[QueryItem],
    *,
    book_id: str,
    query_set_id: str | None = None,
    name: str = "命题组脚本",
    language: QueryLang = QueryLang.mixed,
    source: QuerySetSource = QuerySetSource.official_script,
) -> QuerySet:
    return QuerySet(
        query_set_id=query_set_id or f"{book_id}-script-v1",
        book_id=book_id,
        name=name,
        language=language,
        source=source,
        items=list(items),
    )


def parse_script(
    text: str,
    *,
    book_id: str,
    query_set_id: str | None = None,
) -> QuerySet:
    """解析命题组脚本，返回 v2 QuerySet。"""
    items = parse_script_items(text, book_id=book_id)
    return build_query_set(items, book_id=book_id, query_set_id=query_set_id)


def query_set_from_legacy_steps(
    steps: Iterable[Mapping[str, Any]],
    *,
    book_id: str,
    query_set_id: str | None = None,
) -> QuerySet:
    """把 v1 `book.json` 里的 `steps` 升级成 v2 QuerySet。"""
    items: list[QueryItem] = []
    for position, step in enumerate(steps, start=1):
        number = int(step.get("number", position))
        query_id = f"{book_id}-q{number:03d}"
        instruction = str(step.get("instruction", ""))
        actions: list[QueryAction] = []
        for action_position, raw_action in enumerate(step.get("actions", []) or [], start=1):
            if not isinstance(raw_action, Mapping):
                continue
            kind = _LEGACY_KINDS.get(str(raw_action.get("type", "")), QueryKind.qa)
            action_text = str(raw_action.get("text", ""))
            target = raw_action.get("target")
            actions.append(
                _build_action(
                    str(raw_action.get("action_id") or f"{query_id}-a{action_position:02d}"),
                    kind,
                    action_text,
                    mandatory=bool(raw_action.get("mandatory", False)),
                    target=str(target) if target else None,
                )
            )
        if not actions:
            actions.append(
                _build_action(
                    f"{query_id}-a01",
                    _classify(instruction),
                    instruction,
                    mandatory=bool(step.get("mandatory", False)),
                )
            )
        # 契约要求：只要有一个必选动作，整个 item 就必须必选。
        mandatory = bool(step.get("mandatory", False)) or any(
            action.mandatory for action in actions
        )
        items.append(
            QueryItem(
                query_id=query_id,
                number=number,
                instruction=instruction,
                audio_path=step.get("audio_path"),
                mandatory=mandatory,
                lang=_detect_lang(instruction),
                actions=actions,
                expected=None,
            )
        )
    return build_query_set(items, book_id=book_id, query_set_id=query_set_id)


def query_set_path(package_root: Path, query_set_id: str) -> Path:
    return package_root / "query_sets" / f"{query_set_id}.json"


def write_query_set(query_set: QuerySet, package_root: Path) -> Path:
    """QuerySet 独立落盘，不写进 book.json。"""
    path = query_set_path(package_root, query_set.query_set_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(query_set.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path

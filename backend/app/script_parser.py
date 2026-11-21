from __future__ import annotations

import re

from backend.app.models import ScriptAction, ScriptStep


_STEP_PATTERN = re.compile(r"^\s*(\d+)\.\s*(.*?)\s*$")
_MANDATORY_PATTERN = re.compile(r"[（(]\s*必选\s*[）)]")
_CLICK_PATTERN = re.compile(r"\[点击\]\s*(.*?)(?:\s*\|\s*(.*))?$")


def _classify_action(text: str) -> str:
    normalized = text.strip().lower()
    if normalized.startswith("[点击]"):
        return "click"
    if any(token in normalized for token in ("播放", "暂停", "继续")) or normalized in {
        "play",
        "pause",
        "continue",
    }:
        return "control"
    if "找到" in normalized:
        return "find_scene"
    if "高亮" in normalized:
        return "highlight"
    if "查找" in normalized:
        return "search_text"
    if text.rstrip().endswith(("?", "？")):
        return "question"
    return "other"


def _action_id(step_number: int, action_index: int) -> str:
    return f"step-{step_number:03d}-a{action_index:02d}"


def _parse_click(text: str, mandatory: bool, action_id: str) -> ScriptAction:
    match = _CLICK_PATTERN.search(text)
    if match is None:
        return ScriptAction(
            action_id=action_id,
            type="click",
            text=text,
            mandatory=mandatory,
        )
    target = match.group(1).strip()
    if target.startswith("点击"):
        target = target.removeprefix("点击").strip()
    return ScriptAction(
        action_id=action_id,
        type="click",
        text=text,
        mandatory=mandatory,
        target=target or None,
    )


def parse_script(text: str) -> list[ScriptStep]:
    steps: list[ScriptStep] = []
    current: ScriptStep | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        step_match = _STEP_PATTERN.match(line)
        if step_match:
            number = int(step_match.group(1))
            if any(step.number == number for step in steps):
                raise ValueError(f"Duplicate script step number {number}")
            instruction = step_match.group(2)
            mandatory = bool(_MANDATORY_PATTERN.search(instruction))
            instruction = _MANDATORY_PATTERN.sub("", instruction).strip()
            action = ScriptAction(
                action_id=_action_id(number, 1),
                type=_classify_action(instruction),
                text=instruction,
                mandatory=mandatory,
            )
            current = ScriptStep(
                number=number,
                instruction=instruction,
                mandatory=mandatory,
                actions=[action],
            )
            steps.append(current)
            continue

        if current is None:
            continue

        mandatory = bool(_MANDATORY_PATTERN.search(line))
        cleaned = _MANDATORY_PATTERN.sub("", line).strip()
        action_id = _action_id(current.number, len(current.actions) + 1)
        action = (
            _parse_click(cleaned, mandatory, action_id)
            if cleaned.startswith("[点击]")
            else ScriptAction(
                action_id=action_id,
                type=_classify_action(cleaned),
                text=cleaned,
                mandatory=mandatory,
            )
        )
        current.actions.append(action)
        current.mandatory = current.mandatory or mandatory

    return steps


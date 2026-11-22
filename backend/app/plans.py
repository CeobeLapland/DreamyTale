from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from backend.app.models import BookGenerationResult, ScenePlan, StoryPlan


def load_story_plan(package_root: Path) -> StoryPlan:
    path = package_root / "derived" / "story" / "story_plan.json"
    return _load_model(path, StoryPlan, "story plan")


def load_scene_plan(package_root: Path) -> ScenePlan:
    path = package_root / "derived" / "scene" / "scene_plan.json"
    return _load_model(path, ScenePlan, "scene plan")


def load_generation_result(package_root: Path) -> BookGenerationResult:
    path = package_root / "derived" / "generation_result.json"
    return _load_model(path, BookGenerationResult, "generation result")


def load_timeline(package_root: Path) -> dict[str, object]:
    path = package_root / "derived" / "scene" / "timeline.json"
    data = _load_json(path, "timeline")
    if not isinstance(data, dict):
        raise ValueError("timeline JSON must contain an object")
    return data


def _load_model(path: Path, model_type, label: str):
    data = _load_json(path, label)
    try:
        return model_type.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"invalid {label}: {exc}") from exc


def _load_json(path: Path, label: str):
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid {label} JSON: {exc}") from exc
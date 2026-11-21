from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from backend.app.models import ScenePlan, StoryPlan


def load_story_plan(package_root: Path) -> StoryPlan:
    path = package_root / "story" / "story_plan.json"
    return _load_model(path, StoryPlan, "story plan")


def load_scene_plan(package_root: Path) -> ScenePlan:
    path = package_root / "scene" / "scene_plan.json"
    return _load_model(path, ScenePlan, "scene plan")


def _load_model(path: Path, model_type, label: str):
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path.name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid {label} JSON: {exc}") from exc
    try:
        return model_type.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"invalid {label}: {exc}") from exc
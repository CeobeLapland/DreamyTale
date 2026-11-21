from __future__ import annotations

import copy
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from backend.app.models import (
    BookPackage,
    Hotspot,
    Page,
    ScriptAction,
    ScriptStep,
    TextSpan,
)


SCHEMA_VERSION = "1.0.0"
ACTION_TYPES = {
    "control",
    "find_scene",
    "question",
    "click",
    "search_text",
    "highlight",
    "other",
}
TEXT_SOURCES = {"embedded_pdf", "ocr", "manual"}
SPAN_SOURCES = {"embedded_pdf", "ocr", "manual", "vlm"}
HOTSPOT_SOURCES = {"pdf_annotation", "vlm", "manual"}
LANGUAGES = {"zh-CN", "en"}


class ContractError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _as_posix_path(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\\", "/")
    return value


def normalize_book_package(data: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize legacy manifests into the versioned data contract."""
    package = copy.deepcopy(dict(data))
    package.setdefault("schema_version", SCHEMA_VERSION)
    package.setdefault("title", package.get("source_name", package.get("book_id", "")))

    pages = package.get("pages")
    if isinstance(pages, list):
        for page in pages:
            if not isinstance(page, dict):
                continue
            page["image_path"] = _as_posix_path(page.get("image_path"))
            page.setdefault("text_source", "embedded_pdf")
            page.setdefault("text_spans", [])
            page.setdefault("hotspots", [])

    steps = package.get("steps")
    click_targets: set[str] = set()
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            number = step.get("number")
            actions = step.get("actions")
            if not isinstance(actions, list) or not isinstance(number, int):
                continue
            for index, action in enumerate(actions, start=1):
                if not isinstance(action, dict):
                    continue
                action.setdefault("action_id", f"step-{number:03d}-a{index:02d}")
                if action.get("type") == "click" and action.get("target"):
                    click_targets.add(str(action["target"]))
            if step.get("audio_path"):
                step["audio_path"] = _as_posix_path(step["audio_path"])

    package["pdf_path"] = _as_posix_path(package.get("pdf_path"))
    package["script_path"] = _as_posix_path(package.get("script_path"))
    package["click_targets"] = sorted(click_targets)
    return package


def _is_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = PurePosixPath(value.replace("\\", "/"))
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and bool(path.parts)
    )


def _validate_bbox(
    value: Any,
    field: str,
    page: dict[str, Any],
    errors: list[str],
) -> None:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(not isinstance(item, int) or isinstance(item, bool) for item in value)
    ):
        errors.append(f"{field} must be a four-integer array")
        return
    x1, y1, x2, y2 = value
    width = page.get("width_px")
    height = page.get("height_px")
    if (
        not isinstance(width, int)
        or isinstance(width, bool)
        or not isinstance(height, int)
        or isinstance(height, bool)
    ):
        return
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        errors.append(f"{field} is outside the page image bounds")


def validate_book_package(
    data: Mapping[str, Any],
    *,
    package_root: Path | None = None,
) -> list[str]:
    package = normalize_book_package(data)
    errors: list[str] = []

    required_strings = (
        "schema_version",
        "book_id",
        "source_name",
        "title",
        "language",
        "pdf_path",
        "script_path",
    )
    for field in required_strings:
        if not isinstance(package.get(field), str) or not package[field]:
            errors.append(f"{field} must be a non-empty string")

    if package.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if package.get("language") not in LANGUAGES:
        errors.append("language must be zh-CN or en")
    for field in ("pdf_path", "script_path"):
        if not _is_relative_path(package.get(field)):
            errors.append(f"{field} must be a safe package-relative path")

    pages = package.get("pages")
    if not isinstance(pages, list) or not pages:
        errors.append("pages must be a non-empty array")
        pages = []
    if package.get("page_count") != len(pages):
        errors.append("page_count must equal len(pages)")

    page_indexes: list[int] = []
    span_ids: set[str] = set()
    hotspot_ids: set[str] = set()
    seen_page_indexes: set[int] = set()

    for position, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            errors.append(f"pages[{position - 1}] must be an object")
            continue
        index = page.get("index")
        if not isinstance(index, int) or isinstance(index, bool):
            errors.append(f"pages[{position - 1}].index must be an integer")
            continue
        if index in seen_page_indexes:
            errors.append(f"duplicate page index {index}")
        seen_page_indexes.add(index)
        page_indexes.append(index)

        if not _is_relative_path(page.get("image_path")):
            errors.append(f"page {index} image_path must be a safe relative path")
        if page.get("text_source") not in TEXT_SOURCES:
            errors.append(f"page {index} text_source is invalid")
        for field in ("width_pt", "height_pt"):
            if not isinstance(page.get(field), (int, float)) or page[field] <= 0:
                errors.append(f"page {index} {field} must be positive")
        for field in ("width_px", "height_px"):
            if not isinstance(page.get(field), int) or page[field] <= 0:
                errors.append(f"page {index} {field} must be a positive integer")

        spans = page.get("text_spans")
        if not isinstance(spans, list):
            errors.append(f"page {index} text_spans must be an array")
            spans = []
        for span_position, span in enumerate(spans):
            prefix = f"page {index} text_spans[{span_position}]"
            if not isinstance(span, dict):
                errors.append(f"{prefix} must be an object")
                continue
            span_id = span.get("span_id")
            if not isinstance(span_id, str) or not span_id:
                errors.append(f"{prefix}.span_id must be non-empty")
            elif span_id in span_ids:
                errors.append(f"duplicate span_id {span_id}")
            else:
                span_ids.add(span_id)
            if span.get("page_index") != index:
                errors.append(f"{prefix}.page_index must match page index")
            if not isinstance(span.get("text"), str) or not span["text"]:
                errors.append(f"{prefix}.text must be non-empty")
            if span.get("source") not in SPAN_SOURCES:
                errors.append(f"{prefix}.source is invalid")
            _validate_bbox(span.get("bbox_px"), f"{prefix}.bbox_px", page, errors)

        hotspots = page.get("hotspots")
        if not isinstance(hotspots, list):
            errors.append(f"page {index} hotspots must be an array")
            hotspots = []
        for hotspot_position, hotspot in enumerate(hotspots):
            prefix = f"page {index} hotspots[{hotspot_position}]"
            if not isinstance(hotspot, dict):
                errors.append(f"{prefix} must be an object")
                continue
            hotspot_id = hotspot.get("hotspot_id")
            if not isinstance(hotspot_id, str) or not hotspot_id:
                errors.append(f"{prefix}.hotspot_id must be non-empty")
            elif hotspot_id in hotspot_ids:
                errors.append(f"duplicate hotspot_id {hotspot_id}")
            else:
                hotspot_ids.add(hotspot_id)
            if hotspot.get("page_index") != index:
                errors.append(f"{prefix}.page_index must match page index")
            for field in ("label", "description"):
                if not isinstance(hotspot.get(field), str) or not hotspot[field]:
                    errors.append(f"{prefix}.{field} must be non-empty")
            if hotspot.get("source") not in HOTSPOT_SOURCES:
                errors.append(f"{prefix}.source is invalid")
            _validate_bbox(hotspot.get("bbox_px"), f"{prefix}.bbox_px", page, errors)

    if page_indexes and page_indexes != list(range(1, len(pages) + 1)):
        errors.append("page indexes must start at 1 and be consecutive")

    if package_root is not None:
        for field in ("pdf_path", "script_path"):
            path = package.get(field)
            if _is_relative_path(path) and not (package_root / path).is_file():
                errors.append(f"{field} does not exist: {path}")
        for page in pages:
            if not isinstance(page, dict) or not _is_relative_path(page.get("image_path")):
                continue
            if not (package_root / page["image_path"]).is_file():
                errors.append(f"page {page.get('index')} image does not exist")

    steps = package.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("steps must be a non-empty array")
        steps = []
    step_numbers: list[int] = []
    action_ids: set[str] = set()
    expected_click_targets: set[str] = set()

    for position, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"steps[{position}] must be an object")
            continue
        number = step.get("number")
        if not isinstance(number, int) or isinstance(number, bool):
            errors.append(f"steps[{position}].number must be an integer")
            continue
        step_numbers.append(number)
        if not isinstance(step.get("instruction"), str) or not step["instruction"]:
            errors.append(f"step {number} instruction must be non-empty")
        if not isinstance(step.get("mandatory"), bool):
            errors.append(f"step {number} mandatory must be boolean")
        if not _is_relative_path(step.get("audio_path")):
            errors.append(f"step {number} audio_path must be a safe relative path")
        elif package_root is not None and not (package_root / step["audio_path"]).is_file():
            errors.append(f"step {number} audio does not exist")

        actions = step.get("actions")
        if not isinstance(actions, list) or not actions:
            errors.append(f"step {number} actions must be a non-empty array")
            continue
        for action_position, action in enumerate(actions):
            prefix = f"step {number} actions[{action_position}]"
            if not isinstance(action, dict):
                errors.append(f"{prefix} must be an object")
                continue
            action_id = action.get("action_id")
            if not isinstance(action_id, str) or not action_id:
                errors.append(f"{prefix}.action_id must be non-empty")
            elif action_id in action_ids:
                errors.append(f"duplicate action_id {action_id}")
            else:
                action_ids.add(action_id)
            if action.get("type") not in ACTION_TYPES:
                errors.append(f"{prefix}.type is invalid")
            if not isinstance(action.get("text"), str) or not action["text"]:
                errors.append(f"{prefix}.text must be non-empty")
            if not isinstance(action.get("mandatory"), bool):
                errors.append(f"{prefix}.mandatory must be boolean")
            if action.get("type") == "click":
                target = action.get("target")
                if not isinstance(target, str) or not target:
                    errors.append(f"{prefix}.target is required for click")
                else:
                    expected_click_targets.add(target)

    if step_numbers:
        if len(step_numbers) != len(set(step_numbers)):
            errors.append("script step numbers must be unique")
        if step_numbers != list(range(1, len(step_numbers) + 1)):
            errors.append("script step numbers must start at 1 and be consecutive")

    declared_click_targets = package.get("click_targets")
    if (
        not isinstance(declared_click_targets, list)
        or any(not isinstance(target, str) for target in declared_click_targets)
        or set(declared_click_targets) != expected_click_targets
    ):
        errors.append("click_targets must match click action targets")

    return errors


def book_package_from_dict(
    data: Mapping[str, Any],
    *,
    package_root: Path | None = None,
) -> BookPackage:
    package = normalize_book_package(data)
    errors = validate_book_package(package, package_root=package_root)
    if errors:
        raise ContractError(errors)

    pages = [
        Page(
            index=page["index"],
            image_path=page["image_path"],
            text=page.get("text", ""),
            text_source=page["text_source"],
            width_pt=page["width_pt"],
            height_pt=page["height_pt"],
            width_px=page["width_px"],
            height_px=page["height_px"],
            text_spans=[TextSpan(**span) for span in page["text_spans"]],
            hotspots=[Hotspot(**hotspot) for hotspot in page["hotspots"]],
        )
        for page in package["pages"]
    ]
    steps = [
        ScriptStep(
            number=step["number"],
            instruction=step["instruction"],
            mandatory=step["mandatory"],
            audio_path=step["audio_path"],
            actions=[ScriptAction(**action) for action in step["actions"]],
        )
        for step in package["steps"]
    ]
    return BookPackage(
        schema_version=package["schema_version"],
        book_id=package["book_id"],
        source_name=package["source_name"],
        title=package["title"],
        language=package["language"],
        pdf_path=package["pdf_path"],
        script_path=package["script_path"],
        page_count=package["page_count"],
        pages=pages,
        steps=steps,
        click_targets=package["click_targets"],
    )

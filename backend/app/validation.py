"""数据契约校验（v2）。

事实源是 `contracts/models.py`：这里不再手写字段规则，而是把归一化后的数据喂给
pydantic v2 模型，再把 pydantic 的报错整理成人能读的字符串列表。

`normalize_book_package` 同时承担 v1 -> v2 升级：旧 `pdf_path` 变 `source_path`，
旧 `script_path`/`steps`/`click_targets` 从 `book.json` 里拆出去（脚本属于 QuerySet），
并补齐 v2 新增的必填字段。
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from pydantic import ValidationError

from backend.app.models import (
    SCHEMA_VERSION,
    BookPackage,
    QuerySet,
    content_hash,
)


# v2 BookPackage 允许的顶层字段；v1 的 pdf_path/script_path/steps/click_targets 不在其中。
_BOOK_FIELDS = (
    "schema_version",
    "book_id",
    "source_name",
    "title",
    "authors",
    "language",
    "languages",
    "content_type",
    "source_type",
    "source_path",
    "page_count",
    "pages",
    "style",
    "rights",
    "status",
    "query_set_ids",
    "capabilities_path",
    "created_at",
    "updated_at",
)
_PAGE_FIELDS = (
    "index",
    "image_path",
    "width_px",
    "height_px",
    "width_pt",
    "height_pt",
    "text",
    "text_source",
    "text_confidence",
    "language",
    "blocks",
    "text_spans",
    "hotspots",
    "sha256",
    "render",
)
_SPAN_FIELDS = (
    "span_id",
    "page_index",
    "text",
    "bbox_px",
    "source",
    "confidence",
    "version",
    "status",
    "hash",
)
_HOTSPOT_FIELDS = (
    "hotspot_id",
    "page_index",
    "label",
    "bbox_px",
    "description",
    "source",
    "confidence",
    "version",
    "status",
    "hash",
)
# v1 遗留字段，迁移后不再出现在 book.json 里。
_LEGACY_BOOK_FIELDS = ("pdf_path", "script_path", "steps", "click_targets")

_DEFAULT_CONFIDENCE = {
    "embedded_pdf": 0.99,
    "ocr": 0.9,
    "vlm": 0.8,
    "manual": 0.99,
    "mixed": 0.9,
}


class ContractError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_posix_path(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\\", "/")
    return value


def _is_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = PurePosixPath(value.replace("\\", "/"))
    return not path.is_absolute() and ".." not in path.parts and bool(path.parts)


def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _content_sha256(payload: Any) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _pick(data: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {name: copy.deepcopy(data[name]) for name in fields if name in data}


def _normalize_bbox(value: Any) -> Any:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return [int(item) for item in value]
    return value


def _normalize_span(span: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _pick(span, _SPAN_FIELDS)
    normalized["bbox_px"] = _normalize_bbox(normalized.get("bbox_px"))
    normalized.setdefault("version", 1)
    normalized.setdefault("status", "active")
    source = str(normalized.get("source", "embedded_pdf"))
    normalized["source"] = source
    if "confidence" not in normalized:
        normalized["confidence"] = _DEFAULT_CONFIDENCE.get(source, 0.9)
    if "hash" not in normalized:
        normalized["hash"] = content_hash(dict(normalized))
    return normalized


def _normalize_hotspot(hotspot: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _pick(hotspot, _HOTSPOT_FIELDS)
    normalized["bbox_px"] = _normalize_bbox(normalized.get("bbox_px"))
    normalized.setdefault("version", 1)
    normalized.setdefault("status", "active")
    source = str(normalized.get("source", "auto"))
    normalized["source"] = source
    if "confidence" not in normalized:
        normalized["confidence"] = _DEFAULT_CONFIDENCE.get(source, 0.9)
    if "hash" not in normalized:
        normalized["hash"] = content_hash(dict(normalized))
    return normalized


def _infer_render(page: Mapping[str, Any]) -> dict[str, Any] | None:
    """能从页面像素尺寸反推 DPI 时给出 render；反推不出就留空，不编数据。"""
    width_pt = page.get("width_pt")
    width_px = page.get("width_px")
    if not isinstance(width_pt, (int, float)) or not isinstance(width_px, int):
        return None
    if width_pt <= 0 or width_px <= 0:
        return None
    dpi = round(72 * width_px / width_pt)
    if not 36 <= dpi <= 600:
        return None
    return {"dpi": dpi, "renderer": "legacy", "version": "unknown"}


def _normalize_page(
    page: Mapping[str, Any],
    *,
    package_root: Path | None,
) -> dict[str, Any]:
    normalized = _pick(page, _PAGE_FIELDS)
    normalized["image_path"] = _as_posix_path(normalized.get("image_path"))

    text = normalized.get("text")
    text = text if isinstance(text, str) else ""
    text_source = normalized.get("text_source")
    if not text.strip():
        # v2：无字页必须是 text_source=none 且 text 为空。
        text_source = "none"
    elif not text_source:
        text_source = "embedded_pdf"
    normalized["text"] = text
    normalized["text_source"] = text_source
    if normalized.get("text_confidence") is None and text_source != "none":
        normalized["text_confidence"] = _DEFAULT_CONFIDENCE.get(str(text_source), 0.9)
    if text_source == "none":
        normalized["text_confidence"] = None

    normalized["blocks"] = [
        dict(block) for block in normalized.get("blocks", []) or [] if isinstance(block, dict)
    ]
    normalized["text_spans"] = [
        _normalize_span(span)
        for span in normalized.get("text_spans", []) or []
        if isinstance(span, dict)
    ]
    normalized["hotspots"] = [
        _normalize_hotspot(hotspot)
        for hotspot in normalized.get("hotspots", []) or []
        if isinstance(hotspot, dict)
    ]

    if not normalized.get("sha256"):
        digest = None
        image_path = normalized.get("image_path")
        if package_root is not None and _is_relative_path(image_path):
            digest = _sha256_file(package_root / image_path)
        normalized["sha256"] = digest or _content_sha256(normalized)
    if not normalized.get("render"):
        normalized["render"] = _infer_render(normalized)
    return normalized


def normalize_book_package(
    data: Mapping[str, Any],
    *,
    package_root: Path | None = None,
) -> dict[str, Any]:
    """把任意版本的书包数据归一化成 v2 BookPackage 形状。

    v1 -> v2 的映射：pdf_path -> source_path + source_type；script_path/steps/click_targets
    被移出 book.json（脚本属于 QuerySet）；补齐 content_type/status/created_at 等字段。
    """
    raw = copy.deepcopy(dict(data))
    package = _pick(raw, _BOOK_FIELDS)

    package["schema_version"] = SCHEMA_VERSION
    package.setdefault("authors", [])
    package.setdefault("languages", [])
    package.setdefault("query_set_ids", [])
    package.setdefault("capabilities_path", None)
    package.setdefault("style", None)
    package.setdefault("rights", None)
    package.setdefault("created_at", _utc_now())
    package.setdefault("updated_at", package["created_at"])

    if not package.get("source_path") and isinstance(raw.get("pdf_path"), str):
        package["source_path"] = raw["pdf_path"]
    package["source_path"] = _as_posix_path(package.get("source_path", ""))
    package.setdefault("source_type", "pdf")
    package.setdefault("content_type", "narrative")
    package.setdefault("status", "ingested")

    if not package.get("title"):
        package["title"] = package.get("source_name") or package.get("book_id") or ""
    if not package.get("source_name"):
        package["source_name"] = package["title"]
    if not package.get("language"):
        package["language"] = "zh-CN"
    if not package["languages"]:
        package["languages"] = [package["language"]]

    pages = raw.get("pages")
    normalized_pages = [
        _normalize_page(page, package_root=package_root)
        for page in pages
        if isinstance(page, dict)
    ] if isinstance(pages, list) else []
    package["pages"] = normalized_pages
    # page_count 不做纠正：写错页数必须报错，而不是被静默改对。
    package.setdefault("page_count", len(normalized_pages))

    for legacy_field in _LEGACY_BOOK_FIELDS:
        package.pop(legacy_field, None)
    return package


def _format_validation_errors(exc: ValidationError) -> list[str]:
    messages: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ())) or "book"
        message = error.get("msg", "invalid value")
        messages.append(f"{location}: {message}")
    return messages


def _query_set_audio_paths(package_root: Path) -> list[str]:
    paths: list[str] = []
    query_dir = package_root / "query_sets"
    if not query_dir.is_dir():
        return paths
    for path in sorted(query_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in data.get("items", []) or []:
            audio_path = item.get("audio_path")
            if isinstance(audio_path, str) and audio_path:
                paths.append(audio_path)
    return paths


def _collect_audio_paths(data: Mapping[str, Any], package_root: Path | None) -> list[str]:
    paths: list[str] = []
    steps = data.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict) and isinstance(step.get("audio_path"), str):
                paths.append(step["audio_path"])
    if package_root is not None:
        paths.extend(_query_set_audio_paths(package_root))
    return paths


def validate_book_package(
    data: Mapping[str, Any],
    *,
    package_root: Path | None = None,
) -> list[str]:
    """校验 v2 书包；返回人类可读的错误列表，空列表表示通过。"""
    package = normalize_book_package(data)
    errors: list[str] = []

    try:
        BookPackage.model_validate(package)
    except ValidationError as exc:
        errors.extend(_format_validation_errors(exc))

    for page in package.get("pages", []):
        if not isinstance(page, dict):
            continue
        image_path = page.get("image_path")
        if not _is_relative_path(image_path):
            errors.append(
                f"page {page.get('index')} image_path must be a safe package-relative path"
            )

    if not _is_relative_path(package.get("source_path")):
        errors.append("source_path must be a safe package-relative path")

    if package_root is not None:
        source_path = package.get("source_path")
        if _is_relative_path(source_path) and not (package_root / source_path).is_file():
            errors.append(f"source_path does not exist: {source_path}")
        for page in package.get("pages", []):
            if not isinstance(page, dict):
                continue
            image_path = page.get("image_path")
            if _is_relative_path(image_path) and not (package_root / image_path).is_file():
                errors.append(f"page {page.get('index')} image does not exist")
        for audio_path in _collect_audio_paths(data, package_root):
            if not _is_relative_path(audio_path):
                errors.append(f"audio_path must be a safe package-relative path: {audio_path}")
            elif not (package_root / audio_path).is_file():
                errors.append(f"audio does not exist: {audio_path}")

    return errors


def book_package_from_dict(
    data: Mapping[str, Any],
    *,
    package_root: Path | None = None,
) -> BookPackage:
    package = normalize_book_package(data, package_root=package_root)
    errors = validate_book_package(package, package_root=package_root)
    if errors:
        raise ContractError(errors)
    return BookPackage.model_validate(package)


def query_set_from_dict(
    data: Mapping[str, Any],
    *,
    package_root: Path | None = None,
) -> QuerySet:
    """校验 v2 QuerySet；`package_root` 存在时额外检查音频文件。"""
    errors: list[str] = []
    try:
        query_set = QuerySet.model_validate(data)
    except ValidationError as exc:
        errors.extend(_format_validation_errors(exc))
    if errors:
        raise ContractError(errors)

    if package_root is not None:
        for item in query_set.items:
            if item.audio_path and not (package_root / item.audio_path).is_file():
                errors.append(f"audio does not exist: {item.audio_path}")
    if errors:
        raise ContractError(errors)
    return query_set

"""Human corrections: append-only annotations over auto products.

Contract §7: auto records are immutable. A human correction is a new
`Annotation`; the effective value is the latest active annotation for
(target_type, target_id, field). Conflicts do not silently overwrite: they are
written to `derived/review/queue.jsonl` as `ReviewItem`s.

Canonical layout used by the code:

    data/books/<id>/manual/annotations.jsonl     human input (append-only)
    data/books/<id>/derived/review/queue.jsonl   generated review items

`docs/DATA_CONTRACT.md` §2 still says `derived/review/annotations.jsonl`; that
line is inconsistent with §7 and with this code and should be corrected by the
three owners.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contracts.models import (
    Annotation,
    AnnotationTargetType,
    BookPackage,
    QaCard,
    ReviewItem,
    ReviewReason,
    ReviewStatus,
    Status,
    content_hash,
)

from .config import DATA

MANUAL_DIR = "manual"
ANNOTATIONS_FILE = "annotations.jsonl"
REVIEW_DIR = Path("derived") / "review"
QUEUE_FILE = "queue.jsonl"


def annotations_path(book_id: str, package_root: Path | None = None) -> Path:
    root = package_root or (DATA / book_id)
    return root / MANUAL_DIR / ANNOTATIONS_FILE


def review_queue_path(book_id: str, package_root: Path | None = None) -> Path:
    root = package_root or (DATA / book_id)
    return root / REVIEW_DIR / QUEUE_FILE


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def load_annotations(
    book_id: str,
    package_root: Path | None = None,
) -> list[Annotation]:
    records: list[Annotation] = []
    for raw in _load_jsonl(annotations_path(book_id, package_root)):
        try:
            records.append(Annotation.model_validate(raw))
        except Exception:  # noqa: BLE001 - one bad line must not break runtime
            continue
    return records


def active_annotations(
    book_id: str,
    package_root: Path | None = None,
) -> dict[tuple[str, str, str], Annotation]:
    """Latest active annotation per (target_type, target_id, field)."""
    active: dict[tuple[str, str, str], Annotation] = {}
    for annotation in load_annotations(book_id, package_root):
        if annotation.status is not Status.active:
            continue
        key = (
            annotation.target_type.value,
            annotation.target_id,
            annotation.field,
        )
        active[key] = annotation
    return active


def load_review_items(
    book_id: str,
    package_root: Path | None = None,
) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for raw in _load_jsonl(review_queue_path(book_id, package_root)):
        try:
            items.append(ReviewItem.model_validate(raw))
        except Exception:  # noqa: BLE001
            continue
    return items


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _next_id(prefix: str, book_id: str, existing: int) -> str:
    return f"{prefix}-{book_id}-{existing + 1:03d}"


def make_annotation(
    book_id: str,
    target_type: AnnotationTargetType,
    target_id: str,
    field: str,
    value: Any,
    reviewer: str,
    *,
    old_value: Any = None,
    reason: str | None = None,
    sequence: int | None = None,
    package_root: Path | None = None,
) -> Annotation:
    if sequence is None:
        sequence = len(_load_jsonl(annotations_path(book_id, package_root)))
    record = {
        "annotation_id": _next_id("annotation", book_id, sequence),
        "target_type": target_type.value,
        "target_id": target_id,
        "field": field,
        "value": value,
        "old_value": old_value,
        "source": "human",
        "reviewer": reviewer,
        "created_at": _now().isoformat().replace("+00:00", "Z"),
        "status": Status.active.value,
        "reason": reason,
    }
    record["hash"] = content_hash(record)
    return Annotation.model_validate(record)


def append_annotation(
    book_id: str,
    annotation: Annotation,
    package_root: Path | None = None,
) -> Path:
    path = annotations_path(book_id, package_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(annotation.model_dump(mode="json"), ensure_ascii=False) + "\n"
        )
    return path


def append_review_item(
    book_id: str,
    item: ReviewItem,
    package_root: Path | None = None,
) -> Path:
    path = review_queue_path(book_id, package_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n")
    return path


def _get_field(target: Any, field: str) -> Any:
    current = target
    for part in field.split("."):
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, (list, tuple)) and part.isdigit():
            index = int(part)
            current = current[index] if 0 <= index < len(current) else None
        else:
            current = getattr(current, part, None)
    return current


def _as_json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return list(value)
    return value


def _set_field(target: Any, field: str, value: Any) -> None:
    parts = field.split(".")
    current = target
    for part in parts[:-1]:
        if isinstance(current, dict):
            current = current.setdefault(part, {})
        elif isinstance(current, (list, tuple)) and part.isdigit():
            current = current[int(part)]
        else:
            current = getattr(current, part)
    last = parts[-1]
    if isinstance(current, dict):
        current[last] = value
    elif isinstance(current, (list, tuple)) and last.isdigit():
        current[int(last)] = value  # type: ignore[index]
    else:
        setattr(current, last, value)


def _find_target(
    package: BookPackage | None,
    cards: list[QaCard] | None,
    target_type: AnnotationTargetType,
    target_id: str,
) -> Any | None:
    if target_type is AnnotationTargetType.book:
        return package
    if target_type is AnnotationTargetType.qa_card:
        return next((card for card in cards or [] if card.card_id == target_id), None)
    if package is None:
        return None
    if target_type is AnnotationTargetType.hotspot:
        for page in package.pages:
            for hotspot in page.hotspots:
                if hotspot.hotspot_id == target_id:
                    return hotspot
    if target_type is AnnotationTargetType.text_span:
        for page in package.pages:
            for span in page.text_spans:
                if span.span_id == target_id:
                    return span
    if target_type is AnnotationTargetType.page_block:
        for page in package.pages:
            for block in page.blocks:
                if block.block_id == target_id:
                    return block
    return None


def create_annotation(
    book_id: str,
    target_type: AnnotationTargetType,
    target_id: str,
    field: str,
    value: Any,
    reviewer: str,
    *,
    reason: str | None = None,
    old_value: Any = None,
    package: BookPackage | None = None,
    cards: list[QaCard] | None = None,
    package_root: Path | None = None,
) -> tuple[Annotation, ReviewItem | None]:
    target = _find_target(package, cards, target_type, target_id)
    if target is None:
        raise ValueError(f"annotation target not found: {target_type.value} {target_id}")

    current = _as_json(_get_field(target, field))
    conflict = old_value is not None and current is not None and old_value != current
    annotation = make_annotation(
        book_id,
        target_type,
        target_id,
        field,
        value,
        reviewer,
        old_value=current if old_value is None else old_value,
        reason=reason,
        package_root=package_root,
    )
    append_annotation(book_id, annotation, package_root)

    review: ReviewItem | None = None
    if conflict:
        sequence = len(load_review_items(book_id, package_root))
        review = ReviewItem(
            review_id=_next_id("review", book_id, sequence),
            target_type=target_type,
            target_id=target_id,
            reason=ReviewReason.conflict,
            status=ReviewStatus.pending,
            created_at=_now(),
            notes=(
                f"{field}: reviewer expected {old_value!r}, "
                f"current auto value is {current!r}"
            ),
        )
        append_review_item(book_id, review, package_root)
    return annotation, review


def apply_annotations_to_package(
    package: BookPackage,
    annotations: dict[tuple[str, str, str], Annotation] | None = None,
    *,
    package_root: Path | None = None,
) -> BookPackage:
    """Return a copy with human values applied; auto records are not modified."""
    if annotations is None:
        annotations = active_annotations(package.book_id, package_root)
    if not annotations:
        return package
    effective = package.model_copy(deep=True)
    for (target_type, target_id, field), annotation in annotations.items():
        if target_type == AnnotationTargetType.book.value:
            target = effective
        elif target_type == AnnotationTargetType.hotspot.value:
            target = next(
                (
                    hotspot
                    for page in effective.pages
                    for hotspot in page.hotspots
                    if hotspot.hotspot_id == target_id
                ),
                None,
            )
        elif target_type == AnnotationTargetType.text_span.value:
            target = next(
                (
                    span
                    for page in effective.pages
                    for span in page.text_spans
                    if span.span_id == target_id
                ),
                None,
            )
        elif target_type == AnnotationTargetType.page_block.value:
            target = next(
                (
                    block
                    for page in effective.pages
                    for block in page.blocks
                    if block.block_id == target_id
                ),
                None,
            )
        else:
            continue
        if target is not None:
            _set_field(target, field, annotation.value)
    return effective


def apply_annotations_to_cards(
    cards: list[QaCard],
    annotations: dict[tuple[str, str, str], Annotation] | None = None,
    *,
    book_id: str | None = None,
    package_root: Path | None = None,
) -> list[QaCard]:
    if annotations is None:
        if not book_id:
            return cards
        annotations = active_annotations(book_id, package_root)
    if not annotations:
        return cards
    effective = [card.model_copy(deep=True) for card in cards]
    by_id = {card.card_id: card for card in effective}
    for (target_type, target_id, field), annotation in annotations.items():
        if target_type != AnnotationTargetType.qa_card.value:
            continue
        card = by_id.get(target_id)
        if card is not None:
            _set_field(card, field, annotation.value)
    return effective

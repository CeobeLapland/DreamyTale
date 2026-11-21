"""能力报告（契约 §11）。

报告只统计包里真实存在的东西：页数、有字页、块、热区、场景、视频、问答卡，
以及当前还做不到什么。缺什么就记 0 并写进 limitations，不做乐观估计。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from backend.app.models import (
    SCHEMA_VERSION,
    AnnotationTargetType,
    BookPackage,
    CapabilityReport,
    ContentType,
    Coverage,
    NeedsReview,
    ReviewReason,
)


# 置信度低于这个值的识别结果需要人工看一眼。
_LOW_CONFIDENCE = 0.6


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _count_scenes(package_root: Path) -> int:
    plan = _read_json(package_root / "derived" / "scene" / "scene_plan.json")
    scenes = plan.get("scenes")
    return len(scenes) if isinstance(scenes, list) else 0


def _count_videos(package_root: Path) -> int:
    video_dir = package_root / "derived" / "video"
    if not video_dir.is_dir():
        return 0
    return len(list(video_dir.glob("*.mp4")))


def _count_qa_cards(package_root: Path) -> int:
    cards_path = package_root / "derived" / "knowledge" / "cards.jsonl"
    if not cards_path.is_file():
        return 0
    count = 0
    with cards_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def _count_qa_items(package_root: Path) -> int:
    query_dir = package_root / "query_sets"
    if not query_dir.is_dir():
        return 0
    count = 0
    for path in sorted(query_dir.glob("*.json")):
        data = _read_json(path)
        for item in data.get("items", []) or []:
            for action in item.get("actions", []) or []:
                if action.get("kind") == "qa":
                    count += 1
                    break
    return count


def build_capability_report(
    package: BookPackage,
    package_root: Path,
) -> CapabilityReport:
    pages_total = package.page_count
    pages_with_text = sum(1 for page in package.pages if page.text.strip())
    ocr_pages = sum(1 for page in package.pages if page.text_source == "ocr")
    blocks = sum(len(page.blocks) for page in package.pages)
    hotspots = sum(len(page.hotspots) for page in package.pages)
    scenes = _count_scenes(package_root)
    videos = _count_videos(package_root)
    qa_cards = _count_qa_cards(package_root)
    qa_items = _count_qa_items(package_root)

    needs_review: list[NeedsReview] = []
    for page in package.pages:
        for span in page.text_spans:
            if span.confidence < _LOW_CONFIDENCE:
                needs_review.append(
                    NeedsReview(
                        target_type=AnnotationTargetType.text_span,
                        target_id=span.span_id,
                        reason=ReviewReason.low_confidence,
                    )
                )
        for hotspot in page.hotspots:
            if hotspot.confidence < _LOW_CONFIDENCE:
                needs_review.append(
                    NeedsReview(
                        target_type=AnnotationTargetType.hotspot,
                        target_id=hotspot.hotspot_id,
                        reason=ReviewReason.low_confidence,
                    )
                )

    limitations: list[str] = []
    if pages_with_text < pages_total:
        limitations.append(
            f"{pages_total - pages_with_text}/{pages_total} 页没有文字层，需要 OCR/VLM 补齐"
        )
    if not scenes:
        limitations.append("还没有生成场景时间轴，无法按画面跳转")
    if not videos:
        limitations.append("还没有生成视频，只能用静态页播放")
    if not qa_cards:
        limitations.append("还没有问答卡，问答只能给引导而不是答案")
    limitations.append("未接入语音识别与问答模型，语音输入不会被转写")

    coverage = Coverage(
        text_search=pages_with_text / pages_total if pages_total else 0.0,
        video=min(1.0, videos / pages_total) if pages_total else 0.0,
        qa=min(1.0, qa_cards / qa_items) if qa_items else 0.0,
    )
    ready = (
        pages_total > 0
        and pages_with_text == pages_total
        and scenes > 0
        and videos > 0
        and qa_cards > 0
    )

    return CapabilityReport(
        schema_version=SCHEMA_VERSION,
        book_id=package.book_id,
        generated_at=datetime.now(timezone.utc).replace(microsecond=0),
        content_type=ContentType(package.content_type),
        languages=list(package.languages),
        pages_total=pages_total,
        pages_with_text=pages_with_text,
        ocr_pages=ocr_pages,
        blocks=blocks,
        hotspots=hotspots,
        scenes=scenes,
        videos=videos,
        qa_cards=qa_cards,
        coverage=coverage,
        needs_review=needs_review,
        limitations=limitations,
        status="ready" if ready else "draft",
    )


def write_capability_report(
    report: CapabilityReport,
    package_root: Path,
) -> Path:
    path = package_root / "derived" / "capability.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path

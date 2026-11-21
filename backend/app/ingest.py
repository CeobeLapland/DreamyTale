"""官方压缩包 -> v2 单书包。

产物布局与 pipeline 一致：`book.json` 是 v2 BookPackage，命题组脚本单独落在
`query_sets/<book_id>-script-v1.json`，页面图落在 `pages/`，原始素材落在 `source/`。

渲染用 pypdfium2；文本层用 pypdf 抽取，坐标用 pypdfium2 的字符框换算成页图像素，
两者都不引入新依赖。
"""

from __future__ import annotations

import io
import json
import re
import shutil
import hashlib
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
from pypdf import PdfReader

from backend.app.archive import ArchiveIndex
from backend.app.models import (
    BlockType,
    BookPackage,
    Page,
    PageBlock,
    QueryItem,
    RenderInfo,
    Rights,
    SpanSource,
    Status,
    TextSource,
    TextSpan,
    content_hash,
)
from backend.app.script_parser import build_query_set, parse_script_items, write_query_set
from backend.app.validation import SCHEMA_VERSION, ContractError, validate_book_package


# 命题组的授权水印不属于正文，和 pipeline 一样在入库时剔除。
_WATERMARK_MARKERS = ("仅供", "请勿外传", "参赛使用")


def book_id_from_key(book_key: str) -> str:
    match = re.search(r"(\d+)$", book_key)
    number = match.group(1) if match else "01"
    if "中文" in book_key:
        return f"zh-{int(number):02d}"
    if "英文" in book_key:
        return f"en-{int(number):02d}"
    return re.sub(r"[^a-zA-Z0-9]+", "-", book_key).strip("-").lower() or "book"


def _language(book_key: str) -> str:
    return "en" if "英文" in book_key else "zh-CN"


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _renderer_version() -> str:
    try:
        return metadata.version("pypdfium2")
    except metadata.PackageNotFoundError:
        return "unknown"


def _same_line(
    previous: tuple[int, int, int, int], current: tuple[int, int, int, int]
) -> bool:
    """判断两个字符框是否属于同一行。

    横排文字同一行基线一致，框纵向高度接近；斜排水印的相邻字符纵向会平移。
    两种情况都用“纵向重叠比例 + 中心距离”判断，换行时两者都不成立。
    """
    overlap = min(previous[3], current[3]) - max(previous[1], current[1])
    smaller = min(previous[3] - previous[1], current[3] - current[1])
    if smaller > 0 and overlap / smaller >= 0.3:
        return True
    previous_center = (previous[1] + previous[3]) / 2
    current_center = (current[1] + current[3]) / 2
    previous_height = previous[3] - previous[1]
    current_height = current[3] - current[1]
    distance = abs(previous_center - current_center)
    return distance <= 0.8 * max(previous_height, current_height)


def _union(
    first: tuple[int, int, int, int], second: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    return (
        min(first[0], second[0]),
        min(first[1], second[1]),
        max(first[2], second[2]),
        max(first[3], second[3]),
    )


def _collect_chars(
    page: pdfium.PdfPage,
    *,
    width_px: int,
    height_px: int,
    width_pt: float,
    height_pt: float,
) -> list[tuple[str, tuple[int, int, int, int] | None]]:
    """按内容流顺序取出字符及其页图像素框。"""
    scale_x = width_px / width_pt if width_pt else 1.0
    scale_y = height_px / height_pt if height_pt else 1.0
    chars: list[tuple[str, tuple[int, int, int, int] | None]] = []

    text_page = page.get_textpage()
    try:
        for index in range(text_page.count_chars()):
            char = text_page.get_text_range(index, 1)
            box = text_page.get_charbox(index)
            if box is None:
                chars.append((char, None))
                continue
            left, bottom, right, top = box
            x1 = max(0, min(width_px, round(left * scale_x)))
            x2 = max(0, min(width_px, round(right * scale_x)))
            # pdfium 的坐标原点在左下角，翻转到左上角原点。
            y1 = max(0, min(height_px, round((height_pt - top) * scale_y)))
            y2 = max(0, min(height_px, round((height_pt - bottom) * scale_y)))
            if x2 <= x1 or y2 <= y1:
                chars.append((char, None))
                continue
            chars.append((char, (x1, y1, x2, y2)))
    finally:
        text_page.close()
    return chars


def _match_lines(
    text_lines: list[str],
    chars: list[tuple[str, tuple[int, int, int, int] | None]],
) -> list[tuple[str, list[tuple[int, int, int, int]]]] | None:
    """把 pdfium 字符按 pypdf 抽出的行对齐。

    pypdf 的行切分能正确处理斜排水印，几何切分做不到；两者字符流同源，可以逐字对齐。
    对不上就返回 None，交给几何切分兜底。
    """
    matched: list[tuple[str, list[tuple[int, int, int, int]]]] = []
    index = 0
    for line in text_lines:
        target = "".join(line.split())
        collected: list[tuple[int, int, int, int]] = []
        collected_text = ""
        while index < len(chars) and len(collected_text) < len(target):
            char, box = chars[index]
            index += 1
            if char.isspace():
                continue
            if not target.startswith(collected_text + char):
                return None
            collected_text += char
            if box is not None:
                collected.append(box)
        if collected_text != target:
            return None
        if not collected:
            # 这一行没有可见字形（例如印前文件名的隐藏文本层），不产出块。
            continue
        matched.append((line.strip(), collected))
    return matched


def _group_geometric(
    chars: list[tuple[str, tuple[int, int, int, int] | None]],
) -> list[tuple[str, list[tuple[int, int, int, int]]]]:
    """按纵向位置把字符归行，作为对齐失败时的兜底。"""
    lines: list[dict[str, list]] = []
    previous_box: tuple[int, int, int, int] | None = None
    for char, box in chars:
        if box is None:
            # 空格没有有效框但属于所在行，保留以免英文单词被粘在一起。
            if lines:
                lines[-1]["chars"].append(char)
            continue
        if lines and previous_box is not None and _same_line(previous_box, box):
            lines[-1]["chars"].append(char)
            lines[-1]["boxes"].append(box)
        else:
            lines.append({"chars": [char], "boxes": [box]})
        previous_box = box
    return [("".join(line["chars"]).strip(), line["boxes"]) for line in lines]


def _extract_lines(
    page: pdfium.PdfPage,
    *,
    text_lines: list[str],
    width_px: int,
    height_px: int,
    width_pt: float,
    height_pt: float,
) -> list[tuple[str, tuple[int, int, int, int]]]:
    """把文本层还原成行，行框换算成页图像素坐标。

    只保留有可见字形的行：PDF 里不可见的文本层（印前文件名之类）不是页面正文，
    按无字页处理，交给 OCR 阶段补。
    """
    chars = _collect_chars(
        page,
        width_px=width_px,
        height_px=height_px,
        width_pt=width_pt,
        height_pt=height_pt,
    )
    matched = _match_lines(text_lines, chars) if text_lines else None
    if matched is None:
        grouped = _group_geometric(chars)
    else:
        grouped = [(text, boxes) for text, boxes in matched]

    extracted: list[tuple[str, tuple[int, int, int, int]]] = []
    for text, boxes in grouped:
        text = text.strip()
        if not text or not boxes:
            continue
        extracted.append((text, _union_all(boxes)))
    return extracted


def _union_all(boxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    box = boxes[0]
    for char_box in boxes[1:]:
        box = _union(box, char_box)
    return box


def _join_page_text(text: str, language: str) -> str:
    if language.lower().startswith("zh"):
        return re.sub(r"\s+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _span_hash(
    page_index: int,
    text: str,
    bbox_px: tuple[int, int, int, int],
) -> str:
    return content_hash(
        {
            "page_index": page_index,
            "text": text,
            "bbox_px": list(bbox_px),
            "source": SpanSource.embedded_pdf.value,
            "confidence": 0.99,
            "version": 1,
            "status": Status.active.value,
        }
    )


def _build_page(
    book_id: str,
    language: str,
    index: int,
    image_path: str,
    sha256: str,
    width_px: int,
    height_px: int,
    width_pt: float,
    height_pt: float,
    lines: list[tuple[str, tuple[int, int, int, int]]],
    dpi: int,
) -> Page:
    blocks: list[PageBlock] = []
    spans: list[TextSpan] = []
    body_lines: list[tuple[str, tuple[int, int, int, int]]] = []

    for order, (line_text, bbox_px) in enumerate(lines, start=1):
        if any(marker in line_text for marker in _WATERMARK_MARKERS):
            continue
        body_lines.append((line_text, bbox_px))
        blocks.append(
            PageBlock(
                block_id=f"block-{book_id}-{index:03d}-{order:03d}",
                page_index=index,
                type=BlockType.body,
                text=line_text,
                bbox_px=bbox_px,
                source=SpanSource.embedded_pdf,
                confidence=0.99,
                reading_order=order,
                lang=language,
            )
        )
        spans.append(
            TextSpan(
                span_id=f"span-{book_id}-{index:03d}-{order:03d}",
                page_index=index,
                text=line_text,
                bbox_px=bbox_px,
                source=SpanSource.embedded_pdf,
                confidence=0.99,
                version=1,
                status=Status.active,
                hash=_span_hash(index, line_text, bbox_px),
            )
        )

    if body_lines:
        # 以过滤掉水印后的行为准，避免把命题组授权水印写进正文。
        text = _join_page_text("\n".join(line for line, _ in body_lines), language)
    else:
        # 没有可见字形（无字页或整页都是水印）：按无字页处理，交给 OCR 阶段补。
        text = ""
    text = text.strip()
    text_source = TextSource.embedded_pdf if text else TextSource.none

    return Page(
        index=index,
        image_path=image_path,
        width_px=width_px,
        height_px=height_px,
        width_pt=width_pt,
        height_pt=height_pt,
        text=text,
        text_source=text_source,
        text_confidence=0.99 if text else None,
        language=language,
        blocks=blocks,
        text_spans=spans,
        hotspots=[],
        sha256=sha256,
        render=RenderInfo(dpi=dpi, renderer="pypdfium2", version=_renderer_version()),
    )


def _attach_audio(
    items: list[QueryItem],
    audio_by_number: dict[int, tuple[str, Any]],
    archive: ArchiveIndex,
    package_root: Path,
) -> list[QueryItem]:
    missing = [item.number for item in items if item.number not in audio_by_number]
    if missing:
        raise ValueError(f"Missing audio for steps: {missing}")
    for item in items:
        audio_name, _ = audio_by_number[item.number]
        audio_path = f"audio/{item.number:02d}.wav"
        _write_bytes(package_root / audio_path, archive.read(audio_name))
        item.audio_path = audio_path
    return items


def ingest_book(
    archive_path: Path,
    book_key: str,
    output_root: Path,
    *,
    render_scale: float = 2.0,
    force: bool = False,
) -> Path:
    archive = ArchiveIndex.load(archive_path)
    pdf_name, script_name, audio_directory = archive.find_book_files(book_key)
    package_id = book_id_from_key(book_key)
    package_root = output_root / package_id

    if package_root.exists():
        if not force:
            raise FileExistsError(
                f"{package_root} already exists; pass --force to replace it"
            )
        shutil.rmtree(package_root)

    pdf_bytes = archive.read(pdf_name)
    script_bytes = archive.read(script_name)
    script_text = script_bytes.decode("utf-8-sig")
    language = _language(book_key)

    audio_entries = archive.audio_entries(audio_directory)
    audio_by_number: dict[int, tuple[str, Any]] = {}
    for number, name, info in audio_entries:
        previous = audio_by_number.get(number)
        if previous is not None:
            raise ValueError(f"Duplicate audio index {number}: {previous[0]} and {name}")
        audio_by_number[number] = (name, info)

    _write_bytes(package_root / "source/book.pdf", pdf_bytes)
    _write_bytes(package_root / "source/script.txt", script_bytes)
    _write_bytes(
        package_root / "source/original-audio.mapping.json",
        json.dumps(
            {
                str(number): name
                for number, (name, _) in sorted(audio_by_number.items())
            },
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8"),
    )

    items = parse_script_items(script_text, book_id=package_id)
    _attach_audio(items, audio_by_number, archive, package_root)
    query_set = build_query_set(items, book_id=package_id)

    reader = PdfReader(io.BytesIO(pdf_bytes))
    document = pdfium.PdfDocument(pdf_bytes)
    dpi = max(36, min(600, round(72 * render_scale)))
    pages: list[Page] = []
    try:
        for index, source_page in enumerate(reader.pages, start=1):
            # 文本层用 pypdf 抽（行切分能正确处理斜排水印），坐标用 pdfium 的字符框。
            text_lines = [
                line.strip()
                for line in (source_page.extract_text() or "").splitlines()
                if line.strip()
            ]
            width_pt = float(source_page.mediabox.width)
            height_pt = float(source_page.mediabox.height)
            image_path = f"pages/{index:03d}.png"
            rendered = document[index - 1].render(scale=render_scale)
            image = rendered.to_pil()
            image_file = package_root / image_path
            image_file.parent.mkdir(parents=True, exist_ok=True)
            image.save(image_file, format="PNG", optimize=True)
            lines = _extract_lines(
                document[index - 1],
                text_lines=text_lines,
                width_px=image.width,
                height_px=image.height,
                width_pt=width_pt,
                height_pt=height_pt,
            )
            pages.append(
                _build_page(
                    book_id=package_id,
                    language=language,
                    index=index,
                    image_path=image_path,
                    sha256=_sha256_bytes(image_file),
                    width_px=image.width,
                    height_px=image.height,
                    width_pt=width_pt,
                    height_pt=height_pt,
                    lines=lines,
                    dpi=dpi,
                )
            )
    finally:
        document.close()

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    package = BookPackage(
        schema_version=SCHEMA_VERSION,
        book_id=package_id,
        source_name=book_key,
        title=book_key,
        authors=[],
        language=language,
        languages=[language],
        content_type="narrative",
        source_type="pdf",
        source_path="source/book.pdf",
        page_count=len(pages),
        pages=pages,
        style=None,
        rights=Rights(license="competition_sample", note="命题组授权样本，仅用于本次比赛"),
        status="ingested",
        query_set_ids=[query_set.query_set_id],
        capabilities_path=None,
        created_at=now,
        updated_at=now,
    )

    (package_root / "derived").mkdir(parents=True, exist_ok=True)
    payload = package.model_dump(mode="json")
    errors = validate_book_package(payload, package_root=package_root)
    if errors:
        raise ContractError(errors)

    write_query_set(query_set, package_root)
    (package_root / "book.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return package_root


def _sha256_bytes(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

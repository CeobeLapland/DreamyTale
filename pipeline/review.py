"""Render a page with PDF/OCR boxes for visual review.

This is a reviewer aid, not the frontend: it writes a local PNG under
`data/books/<id>/derived/review/`, so a human can verify that the text layer and
OCR agree before scene/QA work starts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import DATA

COLORS: dict[str, tuple[int, int, int, int]] = {
    "pdf": (0, 110, 230, 255),
    "ocr": (0, 165, 80, 255),
    "note": (130, 130, 130, 255),
    "header": (190, 190, 190, 255),
    "footer": (190, 190, 190, 255),
    "target": (255, 190, 0, 255),
}


def _font(size: int):
    from PIL import ImageFont

    for path in (
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _label(draw: Any, xy: tuple[int, int], text: str, font: Any, color: tuple[int, int, int, int]) -> None:
    x, y = xy
    box = draw.textbbox((x, y), text, font=font, stroke_width=2)
    draw.rectangle((box[0] - 3, box[1] - 2, box[2] + 3, box[3] + 2), fill=(255, 255, 255, 225))
    draw.text((x, y), text, font=font, fill=color, stroke_width=2, stroke_fill=(255, 255, 255))


def render_overlay(
    book_id: str,
    page_index: int,
    target: str | None = None,
    out_path: Path | None = None,
) -> Path:
    from PIL import Image, ImageDraw

    book_dir = DATA / book_id
    book = json.loads((book_dir / "book.json").read_text(encoding="utf-8"))
    page = next((p for p in book["pages"] if p["index"] == page_index), None)
    if page is None:
        raise ValueError(f"page {page_index} not found in {book_id}")

    image = Image.open(book_dir / page["image_path"]).convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _font(24)
    small = _font(20)

    for block in page["blocks"]:
        source = block.get("source")
        kind = block.get("type")
        if source == "ocr":
            color = COLORS["ocr"]
        elif kind == "note":
            color = COLORS["note"]
        elif kind in {"header", "footer"}:
            color = COLORS["header"]
        else:
            color = COLORS["pdf"]
        bbox = tuple(block["bbox_px"])
        draw.rectangle(bbox, outline=color, width=4)
        label = f"{source}:{kind} {block['text'][:20]}"
        _label(draw, (bbox[0], max(0, bbox[1] - 28)), label, small, color)

        if target and target in block.get("text", ""):
            draw.rectangle(bbox, outline=COLORS["target"], width=8)
            _label(draw, (bbox[0], max(0, bbox[1] - 56)), f"TARGET: {target}", font, COLORS["target"])

    legend_lines = [
        ("PDF text block", COLORS["pdf"]),
        ("OCR accepted", COLORS["ocr"]),
        ("note / header", COLORS["note"]),
        ("target phrase", COLORS["target"]),
    ]
    legend_w = 330
    legend_h = 24 + len(legend_lines) * 34
    draw.rectangle((16, 16, 16 + legend_w, 16 + legend_h), fill=(255, 255, 255, 235), outline=(80, 80, 80, 255), width=2)
    draw.text((28, 24), f"{book_id} p{page_index:03d}", font=font, fill=(20, 20, 20, 255))
    for i, (text, color) in enumerate(legend_lines):
        y = 62 + i * 34
        draw.rectangle((30, y + 4, 52, y + 22), outline=color, width=3)
        draw.text((64, y), text, font=small, fill=(30, 30, 30, 255))

    result = Image.alpha_composite(image, overlay).convert("RGB")
    if result.width > 2000:
        result = result.resize((2000, round(result.height * 2000 / result.width)), Image.LANCZOS)

    out_path = out_path or (book_dir / "derived" / "review" / f"overlay_p{page_index:03d}.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(out_path)
    return out_path

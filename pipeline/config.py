"""Static configuration for the local pipeline.

Book specs are data, not logic: adding a book must not require touching stage code.
Competition materials live outside Git and can be configured through
DREAMYTALE_MATERIALS.

Some macOS ZIP tools extract UTF-8 Chinese filenames using a legacy encoding.
This config therefore resolves both normal names and their mojibake variants.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "books"

DEFAULT_MATERIALS = ROOT / "企业预选赛绘本素材" / "绘本素材"
MATERIALS = Path(
    os.environ.get("DREAMYTALE_MATERIALS", str(DEFAULT_MATERIALS))
).expanduser().resolve()

DEFAULT_DPI = 144


def require_materials() -> Path:
    """Return the configured materials directory or raise a clear error."""
    if not MATERIALS.is_dir():
        raise FileNotFoundError(
            "competition materials directory not found: "
            f"{MATERIALS}. Set DREAMYTALE_MATERIALS to the directory "
            "containing the official PDF, TXT and WAV files."
        )
    return MATERIALS


def resolve_material(name: str) -> Path:
    """Resolve a material name, including legacy mojibake from ZIP extraction."""
    root = require_materials()
    exact = root / name
    if exact.exists():
        return exact

    for entry in root.iterdir():
        if name in _decoded_name_variants(entry.name):
            return entry

    raise FileNotFoundError(
        f"material not found: {name} in {root}"
    )


def _decoded_name_variants(name: str) -> set[str]:
    """Decode UTF-8 filenames that were extracted with a legacy code page."""
    variants = {name}
    for encoding in ("gb18030", "gbk", "cp437", "latin1"):
        try:
            decoded = name.encode(encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        variants.add(decoded)
    return variants


@dataclass(frozen=True)
class BookSpec:
    book_id: str
    pdf_name: str
    audio_dir: str
    script_name: str
    language: str
    content_type: str
    source_name: str

    @property
    def pdf_path(self) -> Path:
        return resolve_material(self.pdf_name)

    @property
    def audio_path(self) -> Path:
        return resolve_material(self.audio_dir)

    @property
    def script_path(self) -> Path:
        return resolve_material(self.script_name)


BOOKS: list[BookSpec] = [
    BookSpec(
        "zh-01",
        "中文绘本01.pdf",
        "中文绘本01",
        "中文绘本01.txt",
        "zh-CN",
        "narrative",
        "中文绘本01",
    ),
    BookSpec(
        "zh-02",
        "中文绘本02.pdf",
        "中文绘本02",
        "中文绘本02.txt",
        "zh-CN",
        "narrative",
        "中文绘本02",
    ),
    BookSpec(
        "zh-03",
        "中文绘本03.pdf",
        "中文绘本03",
        "中文绘本03.txt",
        "zh-CN",
        "narrative",
        "中文绘本03",
    ),
    BookSpec(
        "en-01",
        "英文绘本01.pdf",
        "英文绘本01",
        "英文绘本01.txt",
        "en",
        "narrative",
        "英文绘本01",
    ),
    BookSpec(
        "en-02",
        "英文绘本02.pdf",
        "英文绘本02",
        "英文绘本02.txt",
        "en",
        "narrative",
        "英文绘本02",
    ),
    BookSpec(
        "en-03",
        "英文绘本03.pdf",
        "英文绘本03",
        "英文绘本03.txt",
        "en",
        "narrative",
        "英文绘本03",
    ),
]


def find_book(book_id: str) -> BookSpec:
    for spec in BOOKS:
        if spec.book_id == book_id:
            return spec

    known = ", ".join(spec.book_id for spec in BOOKS)
    raise KeyError(f"unknown book_id {book_id!r}; known: {known}")
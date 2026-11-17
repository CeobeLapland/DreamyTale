"""Static configuration for the local pipeline.

Book specs are data, not logic: adding a book must not require touching stage code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "books"
MATERIALS = ROOT / "企业预选赛绘本素材" / "绘本素材"
DEFAULT_DPI = 144


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
        return MATERIALS / self.pdf_name

    @property
    def audio_path(self) -> Path:
        return MATERIALS / self.audio_dir

    @property
    def script_path(self) -> Path:
        return MATERIALS / self.script_name


BOOKS: list[BookSpec] = [
    BookSpec("zh-01", "中文绘本01.pdf", "中文绘本01", "中文绘本01.txt", "zh-CN", "narrative", "中文绘本01"),
    BookSpec("zh-02", "中文绘本02.pdf", "中文绘本02", "中文绘本02.txt", "zh-CN", "narrative", "中文绘本02"),
    BookSpec("zh-03", "中文绘本03.pdf", "中文绘本03", "中文绘本03.txt", "zh-CN", "narrative", "中文绘本03"),
    BookSpec("en-01", "英文绘本01.pdf", "英文绘本01", "英文绘本01.txt", "en", "narrative", "英文绘本01"),
    BookSpec("en-02", "英文绘本02.pdf", "英文绘本02", "英文绘本02.txt", "en", "narrative", "英文绘本02"),
    BookSpec("en-03", "英文绘本03.pdf", "英文绘本03", "英文绘本03.txt", "en", "narrative", "英文绘本03"),
]


def find_book(book_id: str) -> BookSpec:
    for spec in BOOKS:
        if spec.book_id == book_id:
            return spec
    known = ", ".join(s.book_id for s in BOOKS)
    raise KeyError(f"unknown book_id {book_id!r}; known: {known}")

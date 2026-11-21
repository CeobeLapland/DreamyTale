from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path


_IGNORED_PARTS = {"__MACOSX", ".DS_Store"}


def decode_zip_name(name: str) -> str:
    """Decode legacy ZIP names commonly produced by macOS archive tools."""
    try:
        return name.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def is_ignored_member(name: str) -> bool:
    parts = set(Path(name).parts)
    basename = posixpath.basename(name)
    return bool(parts & _IGNORED_PARTS) or basename.startswith("._")


@dataclass(frozen=True, slots=True)
class ArchiveIndex:
    archive_path: Path
    entries: dict[str, zipfile.ZipInfo]

    @classmethod
    def load(cls, archive_path: Path) -> "ArchiveIndex":
        entries: dict[str, zipfile.ZipInfo] = {}
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                if info.is_dir() or is_ignored_member(info.filename):
                    continue
                entries[decode_zip_name(info.filename)] = info
        return cls(archive_path=archive_path, entries=entries)

    def read(self, name: str) -> bytes:
        with zipfile.ZipFile(self.archive_path) as archive:
            return archive.read(self.entries[name])

    def find_book_files(self, book_key: str) -> tuple[str, str, str]:
        pdf_matches = [
            name
            for name in self.entries
            if posixpath.basename(name) == f"{book_key}.pdf"
        ]
        script_matches = [
            name
            for name in self.entries
            if posixpath.basename(name) == f"{book_key}.txt"
        ]
        audio_directories = {
            posixpath.dirname(name)
            for name in self.entries
            if posixpath.basename(posixpath.dirname(name)) == book_key
            and name.lower().endswith(".wav")
        }
        if len(pdf_matches) != 1:
            raise ValueError(f"Expected one PDF for {book_key}, found {len(pdf_matches)}")
        if len(script_matches) != 1:
            raise ValueError(f"Expected one script for {book_key}, found {len(script_matches)}")
        if len(audio_directories) != 1:
            raise ValueError(
                f"Expected one audio directory for {book_key}, found {len(audio_directories)}"
            )
        return pdf_matches[0], script_matches[0], audio_directories.pop()

    def audio_entries(self, directory: str) -> list[tuple[int, str, zipfile.ZipInfo]]:
        indexed: list[tuple[int, str, zipfile.ZipInfo]] = []
        for name, info in self.entries.items():
            if posixpath.dirname(name) != directory or not name.lower().endswith(".wav"):
                continue
            match = re.match(r"^(\d+)(?:\(|\.wav$)", posixpath.basename(name), re.IGNORECASE)
            if match is None:
                continue
            indexed.append((int(match.group(1)), name, info))
        return sorted(indexed, key=lambda item: item[0])

    def list_books(self) -> list[str]:
        books = []
        for name in self.entries:
            basename = posixpath.basename(name)
            if basename.lower().endswith(".pdf"):
                books.append(basename[:-4])
        return sorted(books)


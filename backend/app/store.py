"""单书包读写。

书包的磁盘布局和契约一致：`book.json`（v2 BookPackage）加 `query_sets/*.json`（v2 QuerySet）。
脚本不再塞进 book.json，所以这里额外提供 QuerySet 的读写。
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.app.models import BookPackage, QuerySet
from backend.app.script_parser import query_set_from_legacy_steps, write_query_set
from backend.app.validation import (
    ContractError,
    book_package_from_dict,
    normalize_book_package,
    query_set_from_dict,
    validate_book_package,
)


class BookStoreError(RuntimeError):
    pass


class BookNotFoundError(BookStoreError):
    pass


class InvalidBookPackageError(BookStoreError):
    def __init__(self, book_id: str, errors: list[str]) -> None:
        self.book_id = book_id
        self.errors = errors
        super().__init__(f"invalid book package {book_id}: {'; '.join(errors)}")


class BookStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _package_root(self, book_id: str) -> Path:
        if not book_id or book_id in {".", ".."} or "/" in book_id or "\\" in book_id:
            raise BookNotFoundError(f"invalid book id: {book_id}")
        return self.root / book_id

    def package_root(self, book_id: str) -> Path:
        """Directory of one book package; the pipeline writes its artifacts here."""
        return self._package_root(book_id)

    def list_book_ids(self) -> list[str]:
        return sorted(
            path.parent.name
            for path in self.root.glob("*/book.json")
            if path.is_file()
        )

    def load(self, book_id: str) -> BookPackage:
        package_root = self._package_root(book_id)
        manifest_path = package_root / "book.json"
        if not manifest_path.is_file():
            raise BookNotFoundError(book_id)
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            return book_package_from_dict(data, package_root=package_root)
        except json.JSONDecodeError as exc:
            raise InvalidBookPackageError(book_id, [f"invalid JSON: {exc}"]) from exc
        except ContractError as exc:
            raise InvalidBookPackageError(book_id, exc.errors) from exc

    def list_query_set_ids(self, book_id: str) -> list[str]:
        package_root = self._package_root(book_id)
        query_dir = package_root / "query_sets"
        if not query_dir.is_dir():
            return []
        return sorted(path.stem for path in query_dir.glob("*.json"))

    def load_query_set(self, book_id: str, query_set_id: str) -> QuerySet:
        package_root = self._package_root(book_id)
        path = package_root / "query_sets" / f"{query_set_id}.json"
        if not path.is_file():
            raise BookNotFoundError(f"{book_id}/{query_set_id}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise InvalidBookPackageError(book_id, [f"invalid JSON: {exc}"]) from exc
        try:
            return query_set_from_dict(data, package_root=package_root)
        except ContractError as exc:
            raise InvalidBookPackageError(book_id, exc.errors) from exc

    def validate(self, book_id: str) -> list[str]:
        package_root = self._package_root(book_id)
        manifest_path = package_root / "book.json"
        if not manifest_path.is_file():
            raise BookNotFoundError(book_id)
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return [f"invalid JSON: {exc}"]
        return validate_book_package(data, package_root=package_root)

    def migrate(self, book_id: str) -> bool:
        """把旧版 book.json 升级到 v2，并把脚本拆成独立 QuerySet 文件。"""
        package_root = self._package_root(book_id)
        manifest_path = package_root / "book.json"
        if not manifest_path.is_file():
            raise BookNotFoundError(book_id)
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        legacy_steps = data.get("steps")
        normalized = normalize_book_package(data, package_root=package_root)

        query_set_written = False
        if isinstance(legacy_steps, list) and legacy_steps:
            query_set = query_set_from_legacy_steps(legacy_steps, book_id=book_id)
            write_query_set(query_set, package_root)
            query_set_written = True
            query_set_ids = normalized.setdefault("query_set_ids", [])
            if query_set.query_set_id not in query_set_ids:
                query_set_ids.append(query_set.query_set_id)

        errors = validate_book_package(normalized, package_root=package_root)
        if errors:
            raise InvalidBookPackageError(book_id, errors)
        if normalized == data and not query_set_written:
            return False
        _write_json(manifest_path, normalized)
        return True

    def resolve_asset(self, book_id: str, asset_path: str) -> Path:
        package_root = self._package_root(book_id).resolve()
        if not package_root.is_dir():
            raise BookNotFoundError(book_id)
        relative = Path(asset_path.replace("/", "\\"))
        candidate = (package_root / relative).resolve()
        if not candidate.is_relative_to(package_root) or not candidate.is_file():
            raise BookNotFoundError(f"{book_id}/{asset_path}")
        return candidate


def _write_json(path: Path, data: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)

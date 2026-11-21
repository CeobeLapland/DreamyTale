from __future__ import annotations

from collections.abc import Callable

from backend.app.adapters.ocr import OCRAdapter
from backend.app.models import BookPackage
from backend.app.ocr_results import apply_ocr_result
from backend.app.store import BookStore


ProgressReporter = Callable[[str, float], None]


def run_ocr_stage(
    book_store: BookStore,
    book_id: str,
    adapter: OCRAdapter,
    *,
    report: ProgressReporter | None = None,
) -> BookPackage:
    package = book_store.load(book_id)
    package_root = book_store.root / package.book_id
    provider = adapter.provider_name()

    adapter.health()
    if report is not None:
        report("ocr", 0.0)

    total = len(package.pages)
    for position, page in enumerate(package.pages, start=1):
        image_path = book_store.resolve_asset(
            package.book_id,
            page.image_path,
        )
        result = adapter.recognize(
            image_path,
            page_index=page.index,
            language=package.language,
        )
        apply_ocr_result(
            package_root,
            result,
            provider=provider,
        )
        if report is not None:
            report("ocr", position / total)

    return book_store.load(package.book_id)
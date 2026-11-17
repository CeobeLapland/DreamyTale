from __future__ import annotations

import io
import json
import re
import shutil
from pathlib import Path

import pypdfium2 as pdfium
from pypdf import PdfReader

from backend.app.archive import ArchiveIndex
from backend.app.models import BookPackage, Page
from backend.app.script_parser import parse_script
from backend.app.validation import SCHEMA_VERSION, ContractError, validate_book_package


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
    steps = parse_script(script_text)

    audio_entries = archive.audio_entries(audio_directory)
    audio_by_number: dict[int, tuple[str, object]] = {}
    for number, name, info in audio_entries:
        previous = audio_by_number.get(number)
        if previous is not None:
            raise ValueError(f"Duplicate audio index {number}: {previous[0]} and {name}")
        audio_by_number[number] = (name, info)

    missing_audio = [step.number for step in steps if step.number not in audio_by_number]
    if missing_audio:
        raise ValueError(f"Missing audio for steps: {missing_audio}")

    for step in steps:
        audio_name, _ = audio_by_number[step.number]
        audio_path = f"audio/{step.number:03d}.wav"
        _write_bytes(package_root / audio_path, archive.read(audio_name))
        step.audio_path = audio_path

    _write_bytes(package_root / "source/book.pdf", pdf_bytes)
    _write_bytes(package_root / "source/script.txt", script_bytes)
    _write_bytes(package_root / "source/original-audio.mapping.json", json.dumps(
        {
            str(number): name
            for number, (name, _) in sorted(audio_by_number.items())
        },
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8"))

    reader = PdfReader(io.BytesIO(pdf_bytes))
    document = pdfium.PdfDocument(pdf_bytes)
    pages: list[Page] = []
    try:
        for index, source_page in enumerate(reader.pages, start=1):
            page_text = (source_page.extract_text() or "").strip()
            image_path = f"pages/{index:03d}.png"
            rendered = document[index - 1].render(scale=render_scale)
            image = rendered.to_pil()
            image_file = package_root / image_path
            image_file.parent.mkdir(parents=True, exist_ok=True)
            image.save(image_file, format="PNG", optimize=True)
            pages.append(
                Page(
                    index=index,
                    image_path=image_path,
                    text=page_text,
                    text_source="embedded_pdf",
                    width_pt=float(source_page.mediabox.width),
                    height_pt=float(source_page.mediabox.height),
                    width_px=image.width,
                    height_px=image.height,
                )
            )
    finally:
        document.close()

    click_targets = sorted(
        {
            action.target
            for step in steps
            for action in step.actions
            if action.type == "click" and action.target
        }
    )
    package = BookPackage(
        schema_version=SCHEMA_VERSION,
        book_id=package_id,
        source_name=book_key,
        title=book_key,
        language=_language(book_key),
        pdf_path="source/book.pdf",
        script_path="source/script.txt",
        page_count=len(pages),
        pages=pages,
        steps=steps,
        click_targets=click_targets,
    )
    (package_root / "derived").mkdir(parents=True, exist_ok=True)
    errors = validate_book_package(package.to_dict(), package_root=package_root)
    if errors:
        raise ContractError(errors)
    manifest_path = package_root / "book.json"
    manifest_path.write_text(
        json.dumps(package.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return package_root


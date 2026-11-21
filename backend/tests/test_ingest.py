"""端到端验证 ingest：压缩包 -> v2 book.json + 独立 QuerySet。"""

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from backend.app.ingest import book_id_from_key, ingest_book
from backend.app.models import QuerySet
from backend.app.validation import book_package_from_dict

BOOK_KEY = "中文绘本01"


def _minimal_pdf(text: str = "Hello DreamyTale") -> bytes:
    """生成一页带文字层的最小 PDF，避免测试依赖仓库外的授权素材。"""
    stream = f"BT /F1 18 Tf 20 120 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref_offset = len(output)
    output += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    output += b"0000000000 65535 f \n"
    for offset in offsets:
        output += f"{offset:010d} 00000 n \n".encode("ascii")
    output += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    return bytes(output)


def _write_archive(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{BOOK_KEY}.pdf", _minimal_pdf())
        archive.writestr(f"{BOOK_KEY}.txt", "01. 播放 （必选）\n02. 找到积木城堡的画面\n")
        archive.writestr(f"{BOOK_KEY}/01.wav", b"wav")
        archive.writestr(f"{BOOK_KEY}/02.wav", b"wav")


class IngestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.archive = self.root / "materials.zip"
        _write_archive(self.archive)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_book_id_is_derived_from_book_key(self) -> None:
        self.assertEqual("zh-01", book_id_from_key(BOOK_KEY))

    def test_ingest_writes_v2_book_and_separate_query_set(self) -> None:
        package_root = ingest_book(
            self.archive,
            BOOK_KEY,
            self.root / "books",
            render_scale=2.0,
            force=True,
        )

        book = json.loads((package_root / "book.json").read_text(encoding="utf-8"))
        self.assertEqual("2.0.0", book["schema_version"])
        self.assertEqual("zh-01", book["book_id"])
        self.assertEqual("source/book.pdf", book["source_path"])
        self.assertEqual("pdf", book["source_type"])
        self.assertEqual("narrative", book["content_type"])
        self.assertEqual("ingested", book["status"])
        self.assertEqual(["zh-01-script-v1"], book["query_set_ids"])

        self.assertNotIn("steps", book)
        self.assertNotIn("script_path", book)
        self.assertNotIn("click_targets", book)

        query_set_path = package_root / "query_sets" / "zh-01-script-v1.json"
        self.assertTrue(query_set_path.is_file())
        query_set = QuerySet.model_validate(
            json.loads(query_set_path.read_text(encoding="utf-8"))
        )
        self.assertEqual(2, len(query_set.items))
        self.assertEqual("audio/01.wav", query_set.items[0].audio_path)

    def test_pages_carry_render_and_sha256(self) -> None:
        package_root = ingest_book(
            self.archive,
            BOOK_KEY,
            self.root / "books",
            render_scale=2.0,
            force=True,
        )
        book = json.loads((package_root / "book.json").read_text(encoding="utf-8"))
        page = book["pages"][0]

        self.assertEqual(1, page["index"])
        self.assertEqual("pages/001.png", page["image_path"])
        self.assertEqual(64, len(page["sha256"]))
        self.assertEqual(144, page["render"]["dpi"])
        self.assertEqual("pypdfium2", page["render"]["renderer"])
        self.assertEqual("embedded_pdf", page["text_source"])
        self.assertIn("Hello", page["text"])
        self.assertIn("DreamyTale", page["text"])
        self.assertTrue(page["blocks"])
        self.assertTrue(page["text_spans"])
        self.assertEqual(16, len(page["text_spans"][0]["hash"]))

    def test_ingested_package_passes_contract_validation(self) -> None:
        package_root = ingest_book(
            self.archive,
            BOOK_KEY,
            self.root / "books",
            render_scale=2.0,
            force=True,
        )
        package = book_package_from_dict(
            json.loads((package_root / "book.json").read_text(encoding="utf-8")),
            package_root=package_root,
        )

        self.assertEqual("zh-01", package.book_id)
        self.assertEqual(1, package.page_count)
        self.assertEqual("zh-01-script-v1", package.query_set_ids[0])

    def test_reingest_requires_force(self) -> None:
        ingest_book(
            self.archive,
            BOOK_KEY,
            self.root / "books",
            render_scale=2.0,
            force=True,
        )
        with self.assertRaises(FileExistsError):
            ingest_book(
                self.archive,
                BOOK_KEY,
                self.root / "books",
                render_scale=2.0,
            )


if __name__ == "__main__":
    unittest.main()

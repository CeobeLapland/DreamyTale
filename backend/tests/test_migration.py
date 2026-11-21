"""v1 -> v2 迁移：旧 book.json 能被读进来并升级成 v2 产物。"""

import json
import tempfile
import unittest
from pathlib import Path

from backend.app.store import BookStore
from backend.tests.fixtures import legacy_package


class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.package_root = self.root / "books" / "zh-99"
        (self.package_root / "pages").mkdir(parents=True)
        (self.package_root / "source").mkdir(parents=True)
        (self.package_root / "audio").mkdir(parents=True)
        (self.package_root / "pages" / "001.png").write_bytes(b"png")
        (self.package_root / "source" / "book.pdf").write_bytes(b"pdf")
        (self.package_root / "source" / "script.txt").write_text(
            "01. 播放",
            encoding="utf-8",
        )
        (self.package_root / "audio" / "01.wav").write_bytes(b"wav")
        (self.package_root / "book.json").write_text(
            json.dumps(legacy_package(), ensure_ascii=False),
            encoding="utf-8",
        )
        self.store = BookStore(self.root / "books")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_migrate_rewrites_book_and_splits_query_set(self) -> None:
        self.assertTrue(self.store.migrate("zh-99"))

        payload = json.loads(
            (self.package_root / "book.json").read_text(encoding="utf-8")
        )
        self.assertEqual("2.0.0", payload["schema_version"])
        self.assertEqual("source/book.pdf", payload["source_path"])
        self.assertNotIn("pdf_path", payload)
        self.assertNotIn("script_path", payload)
        self.assertNotIn("steps", payload)
        self.assertNotIn("click_targets", payload)
        self.assertEqual(["zh-99-script-v1"], payload["query_set_ids"])

        query_set_path = self.package_root / "query_sets" / "zh-99-script-v1.json"
        self.assertTrue(query_set_path.is_file())
        query_set = json.loads(query_set_path.read_text(encoding="utf-8"))
        self.assertEqual("2.0.0", query_set["schema_version"])
        self.assertEqual("control", query_set["items"][0]["actions"][0]["kind"])

    def test_migrated_package_can_be_loaded(self) -> None:
        self.store.migrate("zh-99")
        package = self.store.load("zh-99")

        self.assertEqual("zh-99", package.book_id)
        self.assertEqual(1, package.page_count)
        self.assertEqual("embedded_pdf", package.pages[0].text_source.value)

    def test_migrate_is_idempotent(self) -> None:
        self.assertTrue(self.store.migrate("zh-99"))
        self.assertFalse(self.store.migrate("zh-99"))

    def test_validate_reports_no_errors_after_migration(self) -> None:
        self.store.migrate("zh-99")
        self.assertEqual([], self.store.validate("zh-99"))


if __name__ == "__main__":
    unittest.main()

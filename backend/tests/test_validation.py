import unittest

from backend.app.validation import (
    ContractError,
    book_package_from_dict,
    normalize_book_package,
    query_set_from_dict,
    validate_book_package,
)
from backend.tests.fixtures import legacy_package, query_set, valid_package


class BookContractTests(unittest.TestCase):
    def test_accepts_valid_package(self) -> None:
        self.assertEqual([], validate_book_package(valid_package()))

    def test_rejects_page_count_mismatch(self) -> None:
        package = valid_package()
        package["page_count"] = 2
        errors = validate_book_package(package)
        self.assertTrue(any("page_count" in error for error in errors))

    def test_rejects_hotspot_outside_page(self) -> None:
        package = valid_package()
        package["pages"][0]["hotspots"][0]["bbox_px"] = [10, 10, 300, 100]
        errors = validate_book_package(package)
        self.assertTrue(any("hotspot" in error for error in errors))

    def test_rejects_invalid_span_hash(self) -> None:
        package = valid_package()
        package["pages"][0]["text_spans"][0]["hash"] = "not-a-hash"
        errors = validate_book_package(package)
        self.assertTrue(any("hash" in error for error in errors))

    def test_book_package_model_rejects_legacy_fields(self) -> None:
        from pydantic import ValidationError

        from backend.app.models import BookPackage

        package = valid_package()
        package["steps"] = []
        with self.assertRaises(ValidationError):
            BookPackage.model_validate(package)

    def test_converts_to_typed_package(self) -> None:
        package = book_package_from_dict(valid_package())
        self.assertEqual("2.0.0", package.schema_version)
        self.assertEqual("zh-99", package.book_id)
        self.assertEqual("span-zh-99-001-001", package.pages[0].text_spans[0].span_id)
        self.assertEqual(1, package.page_count)

    def test_typed_conversion_raises_contract_error(self) -> None:
        package = valid_package()
        package["pages"][0]["image_path"] = "../outside.png"
        with self.assertRaises(ContractError):
            book_package_from_dict(package)

    def test_reports_missing_assets(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            errors = validate_book_package(valid_package(), package_root=root)
            self.assertTrue(any("image does not exist" in error for error in errors))
            self.assertTrue(any("source_path does not exist" in error for error in errors))


class LegacyNormalizationTests(unittest.TestCase):
    def test_upgrades_v1_package_to_v2(self) -> None:
        normalized = normalize_book_package(legacy_package())

        self.assertEqual("2.0.0", normalized["schema_version"])
        self.assertEqual("source/book.pdf", normalized["source_path"])
        self.assertEqual("pdf", normalized["source_type"])
        self.assertEqual("narrative", normalized["content_type"])
        self.assertEqual("ingested", normalized["status"])
        self.assertTrue(normalized["created_at"])
        self.assertTrue(normalized["updated_at"])

    def test_moves_script_out_of_book_package(self) -> None:
        normalized = normalize_book_package(legacy_package())

        self.assertNotIn("script_path", normalized)
        self.assertNotIn("steps", normalized)
        self.assertNotIn("click_targets", normalized)
        self.assertNotIn("pdf_path", normalized)

    def test_completes_legacy_spans_and_hotspots(self) -> None:
        normalized = normalize_book_package(legacy_package())
        span = normalized["pages"][0]["text_spans"][0]
        hotspot = normalized["pages"][0]["hotspots"][0]

        self.assertEqual(1, span["version"])
        self.assertEqual("active", span["status"])
        self.assertEqual(16, len(span["hash"]))
        self.assertGreater(span["confidence"], 0)
        self.assertEqual(16, len(hotspot["hash"]))
        self.assertEqual("active", hotspot["status"])

    def test_legacy_page_without_text_becomes_none_source(self) -> None:
        legacy = legacy_package()
        legacy["pages"][0]["text"] = ""
        normalized = normalize_book_package(legacy)

        self.assertEqual("none", normalized["pages"][0]["text_source"])
        self.assertIsNone(normalized["pages"][0]["text_confidence"])

    def test_normalized_legacy_package_validates(self) -> None:
        normalized = normalize_book_package(legacy_package())
        self.assertEqual([], validate_book_package(normalized))

    def test_legacy_package_can_be_typed(self) -> None:
        package = book_package_from_dict(legacy_package())
        self.assertEqual("zh-99", package.book_id)


class QuerySetContractTests(unittest.TestCase):
    def test_accepts_valid_query_set(self) -> None:
        parsed = query_set_from_dict(query_set())
        self.assertEqual("zh-99-script-v1", parsed.query_set_id)
        self.assertEqual(1, len(parsed.items))

    def test_rejects_query_action_without_required_field(self) -> None:
        payload = query_set()
        payload["items"][0]["actions"][0]["control_action"] = None
        with self.assertRaises(ContractError):
            query_set_from_dict(payload)


if __name__ == "__main__":
    unittest.main()

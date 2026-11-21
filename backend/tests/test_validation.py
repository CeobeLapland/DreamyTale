import unittest

from backend.app.validation import (
    ContractError,
    book_package_from_dict,
    normalize_book_package,
    validate_book_package,
)


def _valid_package() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "book_id": "zh-99",
        "source_name": "中文绘本99",
        "title": "测试绘本",
        "language": "zh-CN",
        "pdf_path": "source/book.pdf",
        "script_path": "source/script.txt",
        "page_count": 1,
        "pages": [
            {
                "index": 1,
                "image_path": "pages/001.png",
                "text": "测试文字",
                "text_source": "embedded_pdf",
                "width_pt": 100.0,
                "height_pt": 100.0,
                "width_px": 200,
                "height_px": 200,
                "text_spans": [
                    {
                        "span_id": "page-001-span-001",
                        "page_index": 1,
                        "text": "测试",
                        "bbox_px": [10, 10, 50, 30],
                        "source": "embedded_pdf",
                    }
                ],
                "hotspots": [
                    {
                        "hotspot_id": "page-001-hotspot-001",
                        "page_index": 1,
                        "label": "城堡",
                        "bbox_px": [20, 20, 100, 100],
                        "description": "测试城堡",
                        "source": "manual",
                    }
                ],
            }
        ],
        "steps": [
            {
                "number": 1,
                "instruction": "播放",
                "mandatory": True,
                "audio_path": "audio/001.wav",
                "actions": [
                    {
                        "action_id": "step-001-a01",
                        "type": "control",
                        "text": "播放",
                        "mandatory": True,
                        "target": None,
                    }
                ],
            }
        ],
        "click_targets": [],
    }


class BookContractTests(unittest.TestCase):
    def test_accepts_valid_package(self) -> None:
        self.assertEqual([], validate_book_package(_valid_package()))

    def test_normalizes_legacy_package(self) -> None:
        legacy = _valid_package()
        legacy.pop("schema_version")
        legacy.pop("title")
        page = legacy["pages"][0]
        page.pop("text_source")
        page.pop("text_spans")
        page.pop("hotspots")
        action = legacy["steps"][0]["actions"][0]
        action.pop("action_id")

        normalized = normalize_book_package(legacy)

        self.assertEqual("1.0.0", normalized["schema_version"])
        self.assertEqual("中文绘本99", normalized["title"])
        self.assertEqual("embedded_pdf", normalized["pages"][0]["text_source"])
        self.assertEqual(
            "step-001-a01",
            normalized["steps"][0]["actions"][0]["action_id"],
        )
        self.assertEqual([], validate_book_package(normalized))

    def test_rejects_page_count_mismatch(self) -> None:
        package = _valid_package()
        package["page_count"] = 2
        errors = validate_book_package(package)
        self.assertIn("page_count must equal len(pages)", errors)

    def test_rejects_hotspot_outside_page(self) -> None:
        package = _valid_package()
        package["pages"][0]["hotspots"][0]["bbox_px"] = [10, 10, 300, 100]
        errors = validate_book_package(package)
        self.assertTrue(any("outside the page image bounds" in error for error in errors))

    def test_converts_to_typed_package(self) -> None:
        package = book_package_from_dict(_valid_package())
        self.assertEqual("zh-99", package.book_id)
        self.assertEqual("page-001-span-001", package.pages[0].text_spans[0].span_id)
        self.assertEqual("step-001-a01", package.steps[0].actions[0].action_id)

    def test_typed_conversion_raises_contract_error(self) -> None:
        package = _valid_package()
        package["pages"][0]["image_path"] = "../outside.png"
        with self.assertRaises(ContractError):
            book_package_from_dict(package)

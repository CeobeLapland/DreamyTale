import tempfile
import unittest
from pathlib import Path

from backend.app.capability import build_capability_report, write_capability_report
from backend.app.validation import book_package_from_dict
from backend.tests.fixtures import valid_package


class CapabilityReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.package = book_package_from_dict(valid_package())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_counts_package_content(self) -> None:
        report = build_capability_report(self.package, self.root)

        self.assertEqual("zh-99", report.book_id)
        self.assertEqual("2.0.0", report.schema_version)
        self.assertEqual(1, report.pages_total)
        self.assertEqual(1, report.pages_with_text)
        self.assertEqual(0, report.ocr_pages)
        self.assertEqual(1, report.hotspots)
        self.assertEqual(0, report.scenes)
        self.assertEqual(0, report.videos)
        self.assertEqual(0, report.qa_cards)
        self.assertEqual("draft", report.status)

    def test_reports_honest_limitations(self) -> None:
        report = build_capability_report(self.package, self.root)

        joined = " ".join(report.limitations)
        self.assertIn("场景时间轴", joined)
        self.assertIn("问答卡", joined)
        self.assertIn("语音识别", joined)

    def test_marks_low_confidence_items_for_review(self) -> None:
        package = valid_package()
        package["pages"][0]["hotspots"][0]["confidence"] = 0.2
        report = build_capability_report(book_package_from_dict(package), self.root)

        self.assertEqual(1, len(report.needs_review))
        self.assertEqual("hotspot", report.needs_review[0].target_type.value)
        self.assertEqual("hotspot-zh-99-001-001", report.needs_review[0].target_id)

    def test_writes_report_artifact(self) -> None:
        report = build_capability_report(self.package, self.root)
        path = write_capability_report(report, self.root)

        self.assertTrue(path.is_file())
        self.assertEqual("derived/capability.json", path.relative_to(self.root).as_posix())


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.app import generation_runner
from pipeline.config import BookSpec


class PipelineGenerationRunnerTests(unittest.TestCase):
    def test_delegates_to_the_agent_dag(self) -> None:
        spec = BookSpec(
            "zh-99",
            "",
            "",
            "",
            "zh-CN",
            "narrative",
            "测试绘本",
        )
        progress = lambda stage, value: None  # noqa: E731

        with (
            mock.patch.object(generation_runner, "find_book", return_value=spec),
            mock.patch.object(generation_runner, "run_book") as run_book,
        ):
            generation_runner.PipelineGenerationRunner().run("zh-99", progress)

        run_book.assert_called_once()
        args, kwargs = run_book.call_args
        self.assertEqual(spec, args[0])
        self.assertIs(progress, kwargs["progress"])

    def test_resolves_dynamic_uploaded_book(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            book_root = root / "book-test"
            book_root.mkdir()
            (book_root / "book.json").write_text(
                json.dumps(
                    {
                        "book_id": "book-test",
                        "title": "上传绘本",
                        "language": "en",
                        "content_type": "narrative",
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.object(
                    generation_runner,
                    "find_book",
                    side_effect=KeyError("unknown"),
                ),
                mock.patch.object(generation_runner, "DATA", root),
            ):
                spec = generation_runner.resolve_book_spec("book-test")

        self.assertEqual("book-test", spec.book_id)
        self.assertEqual("en", spec.language)
        self.assertEqual("上传绘本", spec.source_name)


if __name__ == "__main__":
    unittest.main()
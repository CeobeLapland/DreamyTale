import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.app import generation_runner
from pipeline.config import BookSpec


class PipelineGenerationRunnerTests(unittest.TestCase):
    def test_runs_all_pipeline_stages(self) -> None:
        spec = BookSpec(
            "zh-99",
            "",
            "",
            "",
            "zh-CN",
            "narrative",
            "测试绘本",
        )
        progress: list[tuple[str, float]] = []

        with (
            mock.patch.object(generation_runner, "find_book", return_value=spec),
            mock.patch.object(generation_runner, "build_ocr", return_value=object()),
            mock.patch.object(generation_runner, "build_vlm", return_value=object()),
            mock.patch.object(generation_runner, "build_llm", return_value=object()),
            mock.patch.object(generation_runner, "run_ocr_all") as run_ocr,
            mock.patch.object(generation_runner, "run_vlm_all") as run_vlm,
            mock.patch.object(generation_runner, "run_story") as run_story,
            mock.patch.object(generation_runner, "run_scene") as run_scene,
            mock.patch.object(generation_runner, "run_tts") as run_tts,
            mock.patch.object(generation_runner, "retime_book") as retime,
            mock.patch.object(generation_runner, "build_index") as build_index,
            mock.patch.object(
                generation_runner,
                "run_video",
                return_value={"book_video": "book.mp4"},
            ),
            mock.patch.object(
                generation_runner,
                "render_final",
                return_value={"final_video": __file__},
            ),
        ):
            generation_runner.PipelineGenerationRunner().run(
                "zh-99",
                lambda stage, value: progress.append((stage, value)),
            )

        run_ocr.assert_called_once()
        run_vlm.assert_called_once()
        run_story.assert_called_once()
        run_scene.assert_called_once()
        run_tts.assert_called_once()
        retime.assert_called_once()
        build_index.assert_called_once()
        self.assertEqual("ocr", progress[0][0])
        self.assertEqual(("compose", 0.99), progress[-1])

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
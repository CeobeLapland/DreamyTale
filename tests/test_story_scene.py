"""Story and scene stage tests. Run: python -m pytest tests/test_story_scene.py -v"""

from __future__ import annotations

import unittest

from contracts.models import (
    Beat,
    BookPackage,
    Character,
    PageStory,
    StoryPlan,
    StyleBible,
)
from pipeline.models.base import VLMResult
from pipeline.scene import build_scene_plan, build_timeline
from pipeline.story import _clean_beats, _clean_characters, _clean_style, _fallback_beats

BOOK = BookPackage.model_validate(
    {
        "schema_version": "2.0.0",
        "book_id": "zh-01",
        "source_name": "中文绘本01",
        "title": "一起搭积木吧",
        "authors": [],
        "language": "zh-CN",
        "languages": ["zh-CN"],
        "content_type": "narrative",
        "source_type": "pdf",
        "source_path": "source/book.pdf",
        "page_count": 2,
        "pages": [
            {
                "index": 1,
                "image_path": "pages/001.png",
                "width_px": 1000,
                "height_px": 600,
                "width_pt": 500.0,
                "height_pt": 300.0,
                "text": "下雨了，小满和花花只好在家里玩。",
                "text_source": "embedded_pdf",
                "text_confidence": 0.99,
                "language": "zh-CN",
                "blocks": [],
                "text_spans": [],
                "hotspots": [],
                "sha256": "a" * 64,
                "render": None,
            },
            {
                "index": 2,
                "image_path": "pages/002.png",
                "width_px": 1000,
                "height_px": 600,
                "width_pt": 500.0,
                "height_pt": 300.0,
                "text": "三块、四块、五块，积木城堡没有倒。",
                "text_source": "embedded_pdf",
                "text_confidence": 0.99,
                "language": "zh-CN",
                "blocks": [],
                "text_spans": [],
                "hotspots": [],
                "sha256": "b" * 64,
                "render": None,
            },
        ],
        "style": None,
        "rights": None,
        "status": "ingested",
        "query_set_ids": [],
        "capabilities_path": None,
        "created_at": "2026-11-21T00:00:00Z",
        "updated_at": "2026-11-21T00:00:00Z",
    }
)


def make_story() -> StoryPlan:
    return StoryPlan(
        book_id="zh-01",
        language="zh-CN",
        title="一起搭积木吧",
        logline="两个孩子搭积木，吵架后又和好。",
        characters=[
            Character(character_id="char-zh-01-001", name="小满", role="protagonist"),
            Character(character_id="char-zh-01-002", name="花花", role="protagonist"),
        ],
        style_bible=StyleBible(
            palette=["#F4E7C5"],
            line="手绘水彩绘本风格",
            texture="纸张纹理",
            negative_prompts=["照片写实"],
        ),
        pages=[
            PageStory(
                page_index=1,
                beats=[
                    Beat(
                        beat_id="beat-zh-01-001-01",
                        description="下雨了，两个孩子在屋里搭积木。",
                        narration="下雨了，小满和花花只好在家里玩。",
                        dialogues=[],
                        entities=["小满", "花花", "积木"],
                        duration_ms=6000,
                    )
                ],
                state_before=None,
                state_after="两个孩子开始搭积木",
            ),
            PageStory(
                page_index=2,
                beats=[
                    Beat(
                        beat_id="beat-zh-01-002-01",
                        description="城堡搭到五块，没有倒。",
                        narration="三块、四块、五块，积木城堡没有倒。",
                        dialogues=[],
                        entities=["积木城堡"],
                        duration_ms=4000,
                    )
                ],
                state_before="两个孩子开始搭积木",
                state_after="城堡搭到五块",
            ),
        ],
        model="local-llm",
        prompt_version="story-v1",
        source_hash="c" * 16,
        created_at="2026-11-21T00:00:00Z",
    )


class CleanTests(unittest.TestCase):
    def test_characters_need_a_name(self) -> None:
        characters = _clean_characters(
            [{"name": "小满", "appearance": "扎马尾"}, {"appearance": "无名氏"}],
            "zh-01",
        )
        self.assertEqual(len(characters), 1)
        self.assertEqual(characters[0].character_id, "char-zh-01-001")

    def test_style_has_defaults(self) -> None:
        style = _clean_style(None)
        self.assertTrue(style.line)
        self.assertTrue(style.negative_prompts)

    def test_beats_fall_back_when_model_returns_nothing(self) -> None:
        fallback = _fallback_beats("zh-01", 1, "原文文字", "画面文字", ["小满"])
        beats = _clean_beats("zh-01", 1, None, fallback)
        self.assertEqual(beats, fallback)

    def test_beats_are_cleaned(self) -> None:
        fallback = _fallback_beats("zh-01", 1, "原文", "", [])
        beats = _clean_beats(
            "zh-01",
            1,
            {
                "beats": [
                    {
                        "description": "两个孩子搭积木",
                        "narration": "我们一起搭城堡",
                        "dialogues": [{"speaker": "小满", "text": "搭高高"}],
                        "entities": ["小满", "小满", ""],
                        "duration_ms": 999999,
                    }
                ]
            },
            fallback,
        )
        self.assertEqual(len(beats), 1)
        self.assertEqual(beats[0].entities, ["小满"])
        self.assertEqual(beats[0].duration_ms, 15000)
        self.assertEqual(beats[0].dialogues[0].speaker, "小满")

    def test_model_result_data_is_used(self) -> None:
        result = VLMResult(text="{}", data={"beats": []})
        self.assertEqual(result.data, {"beats": []})


class ScenePlanTests(unittest.TestCase):
    def test_scene_times_are_relative_to_the_page(self) -> None:
        plan = build_scene_plan(BOOK, make_story())
        self.assertEqual(len(plan.scenes), 2)
        self.assertEqual(plan.scenes[0].start_ms, 0)
        self.assertEqual(plan.scenes[0].end_ms, 6000)
        self.assertEqual(plan.scenes[1].start_ms, 0)
        self.assertEqual(plan.scenes[1].end_ms, 4000)

    def test_scene_has_what_the_player_needs(self) -> None:
        plan = build_scene_plan(BOOK, make_story())
        scene = plan.scenes[0]
        self.assertTrue(scene.aliases)
        self.assertTrue(scene.subtitles)
        self.assertEqual(scene.subtitles[0].text, "下雨了，小满和花花只好在家里玩。")
        self.assertTrue(scene.video_path.endswith(".mp4"))
        self.assertTrue(scene.keyframe_path.endswith(".png"))
        self.assertIn("小满", scene.prompt)

    def test_timeline_is_absolute(self) -> None:
        plan = build_scene_plan(BOOK, make_story())
        timeline = build_timeline(BOOK, plan)
        self.assertEqual(timeline["total_ms"], 10000)
        self.assertEqual(timeline["pages"][0]["start_ms"], 0)
        self.assertEqual(timeline["pages"][1]["start_ms"], 6000)
        self.assertEqual(timeline["pages"][1]["end_ms"], 10000)

    def test_scene_plan_is_contract_valid(self) -> None:
        plan = build_scene_plan(BOOK, make_story())
        again = type(plan).model_validate_json(plan.model_dump_json())
        self.assertEqual(again.scenes[0].scene_id, plan.scenes[0].scene_id)


if __name__ == "__main__":
    unittest.main()

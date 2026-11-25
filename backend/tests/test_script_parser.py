import tempfile
import unittest
from pathlib import Path

from backend.app.models import ControlAction, QueryKind
from backend.app.script_parser import (
    control_action_for,
    parse_script,
    query_set_from_legacy_steps,
    write_query_set,
)


SAMPLE_SCRIPT = """
01. 播放 （必选）
02. 暂停 （必选）
03. 找到搭了九块积木的画面 （必选）
04. 他们在搭什么？ （必选）
05. 找到小满画卡片的画面
    [点击] 点击生日卡片 | 暂停并展示卡片信息 （必选）
06. Who made the card?
07. 查找"生日快乐"几个字 （必选）
08. 高亮"生日快乐"
09. 结束播放 （必选）
"""


class ScriptParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.query_set = parse_script(SAMPLE_SCRIPT, book_id="zh-99")

    def test_parses_all_items(self) -> None:
        self.assertEqual(9, len(self.query_set.items))

    def test_query_set_has_contract_identity(self) -> None:
        self.assertEqual("zh-99-script-v1", self.query_set.query_set_id)
        self.assertEqual("zh-99", self.query_set.book_id)
        self.assertEqual("2.0.0", self.query_set.schema_version)
        self.assertEqual("official_script", self.query_set.source.value)

    def test_marks_mandatory_items(self) -> None:
        mandatory = [item.number for item in self.query_set.items if item.mandatory]
        self.assertEqual([1, 2, 3, 4, 5, 7, 9], mandatory)

    def test_maps_control_kind(self) -> None:
        self.assertEqual(QueryKind.control, self.query_set.items[0].actions[0].kind)
        self.assertEqual("play", self.query_set.items[0].actions[0].control_action.value)
        self.assertEqual("pause", self.query_set.items[1].actions[0].control_action.value)
        self.assertEqual("stop", self.query_set.items[8].actions[0].control_action.value)

    def test_maps_seek_kind(self) -> None:
        action = self.query_set.items[2].actions[0]
        self.assertEqual(QueryKind.seek, action.kind)
        self.assertEqual("找到搭了九块积木的画面", action.seek_query)

    def test_maps_question_to_qa_kind(self) -> None:
        self.assertEqual(QueryKind.qa, self.query_set.items[3].actions[0].kind)
        self.assertEqual(QueryKind.qa, self.query_set.items[5].actions[0].kind)

    def test_attaches_click_target(self) -> None:
        click = self.query_set.items[4].actions[1]
        self.assertEqual("zh-99-q005-a02", click.action_id)
        self.assertEqual(QueryKind.click, click.kind)
        self.assertEqual("生日卡片", click.target)
        self.assertTrue(click.mandatory)

    def test_maps_search_and_highlight_kinds(self) -> None:
        search = self.query_set.items[6].actions[0]
        highlight = self.query_set.items[7].actions[0]
        self.assertEqual(QueryKind.search, search.kind)
        self.assertEqual("生日快乐", search.search_text)
        self.assertEqual(QueryKind.highlight, highlight.kind)
        self.assertEqual("生日快乐", highlight.highlight_text)

    def test_assigns_unique_action_ids(self) -> None:
        action_ids = [
            action.action_id
            for item in self.query_set.items
            for action in item.actions
        ]
        self.assertEqual(len(action_ids), len(set(action_ids)))
        self.assertEqual("zh-99-q001-a01", action_ids[0])
        self.assertEqual("zh-99-q005-a01", self.query_set.items[4].actions[0].action_id)

    def test_rejects_duplicate_step_numbers(self) -> None:
        with self.assertRaises(ValueError):
            parse_script("01. Play\n01. Pause\n", book_id="zh-99")

    def test_writes_query_set_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = write_query_set(self.query_set, root)
            self.assertTrue(path.is_file())
            self.assertEqual("query_sets/zh-99-script-v1.json", path.as_posix().split(root.as_posix() + "/")[-1])


class LegacyScriptTests(unittest.TestCase):
    def test_upgrades_legacy_steps_to_query_set(self) -> None:
        steps = [
            {
                "number": 1,
                "instruction": "播放",
                "mandatory": True,
                "audio_path": "audio/01.wav",
                "actions": [
                    {
                        "action_id": "step-001-a01",
                        "type": "control",
                        "text": "播放",
                        "mandatory": True,
                    }
                ],
            },
            {
                "number": 2,
                "instruction": "找到积木城堡",
                "mandatory": False,
                "actions": [
                    {
                        "action_id": "step-002-a01",
                        "type": "find_scene",
                        "text": "找到积木城堡",
                        "mandatory": False,
                    }
                ],
            },
        ]
        query_set = query_set_from_legacy_steps(steps, book_id="zh-99")

        self.assertEqual("zh-99-script-v1", query_set.query_set_id)
        self.assertEqual(2, len(query_set.items))
        self.assertEqual(QueryKind.control, query_set.items[0].actions[0].kind)
        self.assertEqual("play", query_set.items[0].actions[0].control_action.value)
        self.assertEqual(QueryKind.seek, query_set.items[1].actions[0].kind)
        self.assertEqual("找到积木城堡", query_set.items[1].actions[0].seek_query)
        self.assertEqual("audio/01.wav", query_set.items[0].audio_path)


class ControlRoutingTests(unittest.TestCase):
    def test_first_control_word_wins(self) -> None:
        # ASR 偶尔会在短句后面重复词；先说哪个就听哪个。
        self.assertEqual(ControlAction.play, control_action_for("播放 继续"))
        self.assertEqual(ControlAction.resume, control_action_for("继续播放"))
        self.assertEqual(ControlAction.stop, control_action_for("结束播放"))

    def test_exact_english_play(self) -> None:
        self.assertEqual(ControlAction.play, control_action_for("Play"))


if __name__ == "__main__":
    unittest.main()

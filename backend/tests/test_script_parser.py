import unittest

from backend.app.script_parser import parse_script


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
    def test_parses_all_steps(self) -> None:
        steps = parse_script(SAMPLE_SCRIPT)
        self.assertEqual(9, len(steps))

    def test_marks_mandatory_steps(self) -> None:
        steps = parse_script(SAMPLE_SCRIPT)
        mandatory = [step.number for step in steps if step.mandatory]
        self.assertEqual([1, 2, 3, 4, 5, 7, 9], mandatory)

    def test_attaches_click_target(self) -> None:
        steps = parse_script(SAMPLE_SCRIPT)
        click = steps[4].actions[1]
        self.assertEqual("step-005-a02", click.action_id)
        self.assertEqual("click", click.type)
        self.assertEqual("生日卡片", click.target)
        self.assertTrue(click.mandatory)

    def test_classifies_question(self) -> None:
        steps = parse_script(SAMPLE_SCRIPT)
        self.assertEqual("question", steps[3].actions[0].type)
        self.assertEqual("question", steps[5].actions[0].type)

    def test_assigns_unique_action_ids(self) -> None:
        steps = parse_script(SAMPLE_SCRIPT)
        action_ids = [
            action.action_id
            for step in steps
            for action in step.actions
        ]
        self.assertEqual(len(action_ids), len(set(action_ids)))
        self.assertEqual("step-001-a01", action_ids[0])
        self.assertEqual("step-005-a01", steps[4].actions[0].action_id)

    def test_rejects_duplicate_step_numbers(self) -> None:
        with self.assertRaises(ValueError):
            parse_script("01. Play\n01. Pause\n")


if __name__ == "__main__":
    unittest.main()


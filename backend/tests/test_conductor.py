import tempfile
import unittest
from pathlib import Path

from backend.app.conductor import describe_tools, plan_intents, run_interaction
from backend.app.models import InteractionKind, InteractionRequest
from backend.app.session_log import read_traces, read_turns
from backend.app.validation import book_package_from_dict
from backend.tests.fixtures import valid_package


def _request(**overrides) -> InteractionRequest:
    payload = {
        "book_id": "zh-99",
        "session_id": "sess-conductor",
        "kind": "auto",
        "input": {"text": "先找到测试，然后告诉我为什么？"},
    }
    payload.update(overrides)
    return InteractionRequest.model_validate(payload)


class ConductorPlanTests(unittest.TestCase):
    def test_plan_splits_seek_then_qa(self) -> None:
        intents = plan_intents(_request())

        self.assertEqual(
            [InteractionKind.seek, InteractionKind.qa],
            [kind for kind, _ in intents],
        )
        self.assertIn("找到测试", intents[0][1])
        self.assertIn("为什么", intents[1][1])

    def test_plan_keeps_a_single_question(self) -> None:
        text = "花花为什么生气？"
        intents = plan_intents(_request(input={"text": text}))

        self.assertEqual([(InteractionKind.qa, text)], intents)

    def test_plan_keeps_explicit_kind(self) -> None:
        request = _request(kind=InteractionKind.control, input={"text": "先找到测试，然后播放"})

        intents = plan_intents(request)

        self.assertEqual([InteractionKind.control], [kind for kind, _ in intents])
        self.assertEqual("先找到测试，然后播放", intents[0][1])

    def test_plan_does_not_split_on_bare_zai(self) -> None:
        """'再也不想理她' 里的 '再' 不是指令分隔符。"""
        text = "小满再也不想理花花了，为什么？"
        intents = plan_intents(_request(input={"text": text}))

        self.assertEqual([InteractionKind.qa], [kind for kind, _ in intents])


class ConductorRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.package = book_package_from_dict(valid_package())
        self.temporary = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_control_turn_and_trace_are_persisted(self) -> None:
        response = run_interaction(
            _request(
                request_id="req-conductor-1",
                kind=InteractionKind.control,
                input={"text": "播放"},
            ),
            self.package,
            data_root=self.data_root,
        )

        self.assertEqual("ok", response.status)
        self.assertEqual("play", response.action.type.value)

        turns = read_turns("zh-99", data_root=self.data_root)
        self.assertEqual(1, len(turns))
        self.assertEqual("req-conductor-1", turns[0]["turn_id"])
        self.assertEqual("control", turns[0]["kind"])
        self.assertEqual("播放", turns[0]["input_text"])

        traces = read_traces("zh-99", data_root=self.data_root)
        self.assertEqual(1, len(traces))
        self.assertEqual("interaction", traces[0]["kind"])
        self.assertEqual(
            ["route", "player"], [stage["name"] for stage in traces[0]["stages"]]
        )

    def test_multi_intent_runs_both_tools(self) -> None:
        response = run_interaction(
            _request(request_id="req-conductor-2"),
            self.package,
            data_root=self.data_root,
        )

        self.assertEqual("ok", response.status)
        self.assertEqual("qa", response.kind.value)
        self.assertIn("测试", response.answer.text)
        self.assertIn("没有找到", response.answer.text)

        traces = read_traces("zh-99", data_root=self.data_root)
        self.assertEqual(
            ["route", "seek", "qa.guide"],
            [stage["name"] for stage in traces[0]["stages"]],
        )
        self.assertEqual(
            ["seek", "qa"],
            [intent["kind"] for intent in traces[0]["input"]["intents"]],
        )

    def test_asr_latency_is_added_back(self) -> None:
        response = run_interaction(
            _request(request_id="req-conductor-3", input={"text": "播放"}),
            self.package,
            data_root=self.data_root,
            input_text="播放",
            input_audio="upload://current-audio",
            asr_ms=215,
        )

        self.assertEqual(215, response.latency.asr)
        self.assertGreaterEqual(response.latency.total, 215)
        trace = read_traces("zh-99", data_root=self.data_root)[0]
        self.assertEqual("asr", trace["stages"][0]["name"])
        turn = read_turns("zh-99", data_root=self.data_root)[0]
        self.assertEqual("upload://current-audio", turn["input_audio"])

    def test_tool_registry_covers_all_six_kinds(self) -> None:
        names = {tool["name"] for tool in describe_tools()}

        self.assertEqual(
            {"router", "player", "seek", "retrieve", "highlight", "click", "qa"},
            names,
        )


if __name__ == "__main__":
    unittest.main()

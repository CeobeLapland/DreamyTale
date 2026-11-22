import unittest

from backend.app.interaction import handle_interaction
from backend.app.models import (
    AnswerTier,
    InteractionKind,
    InteractionRequest,
)
from backend.app.validation import book_package_from_dict
from backend.tests.fixtures import valid_package


def _request(**overrides) -> InteractionRequest:
    payload = {
        "book_id": "zh-99",
        "session_id": "sess-1",
        "kind": "qa",
        "input": {"text": "他们在搭什么？"},
    }
    payload.update(overrides)
    return InteractionRequest.model_validate(payload)


class InteractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.package = book_package_from_dict(valid_package())

    def test_control_action_is_resolved_without_models(self) -> None:
        response = handle_interaction(
            _request(kind=InteractionKind.control, input={"text": "暂停"}),
            self.package,
        )

        self.assertEqual("ok", response.status)
        self.assertEqual("pause", response.action.type.value)
        self.assertIsNone(response.answer)
        self.assertIsNone(response.error)

    def test_qa_falls_back_instead_of_faking_an_answer(self) -> None:
        response = handle_interaction(_request(), self.package)

        self.assertEqual("fallback", response.status)
        self.assertEqual(AnswerTier.guide, response.answer.tier)
        self.assertIn("问答卡", response.answer.text)
        self.assertEqual("qa_runtime_not_configured", response.error.code)
        self.assertFalse(response.error.retryable)

    def test_seek_falls_back_without_scene_plan(self) -> None:
        response = handle_interaction(
            _request(kind=InteractionKind.seek, input={"text": "找到积木城堡的画面"}),
            self.package,
        )

        self.assertEqual("fallback", response.status)
        self.assertEqual("scene_plan_not_generated", response.error.code)
        self.assertEqual("none", response.action.type.value)

    def test_search_finds_text_in_the_text_layer(self) -> None:
        response = handle_interaction(
            _request(kind=InteractionKind.search, input={"text": "测试"}),
            self.package,
        )

        self.assertEqual("ok", response.status)
        self.assertEqual("highlight", response.action.type.value)
        self.assertEqual(["span-zh-99-001-001"], response.action.span_ids)
        self.assertEqual(AnswerTier.quote, response.answer.tier)
        self.assertEqual(1, response.answer.evidence[0].page_index)

    def test_search_without_match_falls_back(self) -> None:
        response = handle_interaction(
            _request(kind=InteractionKind.search, input={"text": "不存在的文字"}),
            self.package,
        )

        self.assertEqual("fallback", response.status)
        self.assertEqual("text_not_found", response.error.code)

    def test_click_resolves_hotspot(self) -> None:
        response = handle_interaction(
            _request(
                kind=InteractionKind.click,
                input={"text": "点一下", "page_index": 1, "click": {"x_px": 30, "y_px": 30}},
            ),
            self.package,
        )

        self.assertEqual("ok", response.status)
        self.assertEqual("hotspot-zh-99-001-001", response.action.hotspot_id)

    def test_click_without_hotspot_falls_back(self) -> None:
        response = handle_interaction(
            _request(
                kind=InteractionKind.click,
                input={"text": "点一下", "page_index": 1, "click": {"x_px": 190, "y_px": 190}},
            ),
            self.package,
        )

        self.assertEqual("fallback", response.status)
        self.assertEqual("hotspot_not_resolved", response.error.code)

    def test_auto_kind_routes_by_text(self) -> None:
        response = handle_interaction(
            _request(kind=InteractionKind.auto, input={"text": "播放"}),
            self.package,
        )

        self.assertEqual("control", response.kind.value)
        self.assertEqual("play", response.action.type.value)

    def test_auto_kind_without_text_falls_back(self) -> None:
        response = handle_interaction(
            _request(kind=InteractionKind.auto, input={"audio_path": "audio/01.wav"}),
            self.package,
        )

        self.assertEqual("fallback", response.status)
        self.assertEqual("qa_runtime_not_configured", response.error.code)

    def test_response_carries_request_id(self) -> None:
        response = handle_interaction(
            _request(request_id="req-000001"),
            self.package,
        )

        self.assertEqual("req-000001", response.request_id)


if __name__ == "__main__":
    unittest.main()

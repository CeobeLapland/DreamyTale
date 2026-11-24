import unittest

from contracts.models import content_hash
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

    def test_qa_without_card_guides_instead_of_shrugging(self) -> None:
        """契约 §6.2：没有答案卡时给引导，不是"没找到"的死胡同。"""
        response = handle_interaction(_request(), self.package)

        self.assertEqual("ok", response.status)
        self.assertEqual(AnswerTier.guide, response.answer.tier)
        self.assertEqual("seek", response.action.type.value)
        # 引导必须三件事齐全：承认、翻页、反问。
        self.assertIn("没有找到", response.answer.text)
        self.assertIn("第 1 页", response.answer.text)
        self.assertIn("？", response.answer.text)
        self.assertNotIn("抱歉", response.answer.text)
        self.assertNotIn("无法回答", response.answer.text)

    def test_qa_without_a_book_falls_back(self) -> None:
        """连书都没有时才真的降级。"""
        response = handle_interaction(_request(), None)

        self.assertEqual("fallback", response.status)
        self.assertEqual(AnswerTier.guide, response.answer.tier)
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

    def test_highlight_this_sentence_uses_the_previous_search(self) -> None:
        """语音说"高亮这句话"时，要接上一轮真正查找的目标。"""
        session = "sess-coreference"
        first = handle_interaction(
            _request(
                session_id=session,
                kind=InteractionKind.search,
                input={"text": "查找“测试”"},
            ),
            self.package,
        )
        self.assertEqual("ok", first.status)

        second = handle_interaction(
            _request(
                session_id=session,
                kind=InteractionKind.highlight,
                input={"text": "高亮这句话"},
            ),
            self.package,
        )

        self.assertEqual("ok", second.status)
        self.assertEqual("highlight", second.action.type.value)
        self.assertEqual(["span-zh-99-001-001"], second.action.span_ids)

    def test_seek_falls_back_to_the_page_text(self) -> None:
        """"找到 X"没有场景命中，但 X 在页上：翻到那一页并引用它。"""
        response = handle_interaction(
            _request(kind=InteractionKind.seek, input={"text": "找到测试"}),
            self.package,
        )

        self.assertEqual("ok", response.status)
        self.assertEqual("seek", response.action.type.value)
        self.assertIn("测试", response.answer.text)
        self.assertTrue(response.answer.evidence)
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

    def test_click_prefers_the_smallest_overlapping_hotspot(self) -> None:
        """Visual hotspots overlap: the car inside the movie poster wins."""
        payload = valid_package()
        small = {
            "hotspot_id": "hotspot-small",
            "page_index": 1,
            "label": "汽车",
            "bbox_px": [30, 30, 60, 60],
            "description": "海报里的小汽车",
            "source": "vlm",
            "confidence": 0.6,
            "version": 1,
            "status": "active",
        }
        small["hash"] = content_hash(small)
        payload["pages"][0]["hotspots"].append(small)
        package = book_package_from_dict(payload)

        response = handle_interaction(
            _request(
                kind=InteractionKind.click,
                input={"text": "点一下", "page_index": 1, "click": {"x_px": 40, "y_px": 40}},
            ),
            package,
        )

        self.assertEqual("ok", response.status)
        self.assertEqual("hotspot-small", response.action.hotspot_id)

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

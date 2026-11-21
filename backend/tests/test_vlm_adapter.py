import unittest
from pathlib import Path

from backend.app.adapters import (
    VLMAdapter,
    VLMObject,
    VLMPageResult,
)


class FakeVLMAdapter:
    def provider_name(self) -> str:
        return "fake-vlm"

    def health(self) -> None:
        return None

    def understand(
        self,
        image_path: Path,
        *,
        page_index: int,
        text: str,
        language: str,
    ) -> VLMPageResult:
        return VLMPageResult(
            page_index=page_index,
            summary="两个人物在室内搭积木",
            scene="室内，白天，气氛愉快",
            characters=("小满", "花花"),
            objects=(
                VLMObject(
                    label="积木城堡",
                    category="object",
                    description="用多块积木搭成的城堡",
                    confidence=0.92,
                    bbox_px=(20, 30, 150, 180),
                ),
            ),
        )


class VLMAdapterContractTests(unittest.TestCase):
    def test_accepts_structured_page_understanding(self) -> None:
        adapter: VLMAdapter = FakeVLMAdapter()
        result = adapter.understand(
            Path("page.png"),
            page_index=1,
            text="我们一起搭城堡",
            language="zh-CN",
        )

        self.assertEqual("fake-vlm", adapter.provider_name())
        self.assertEqual(1, result.page_index)
        self.assertEqual(("小满", "花花"), result.characters)
        self.assertEqual(1, len(result.objects))
        self.assertEqual("积木城堡", result.objects[0].label)

    def test_allows_object_without_bbox(self) -> None:
        item = VLMObject(
            label="积木",
            category="object",
            description="一块积木",
            confidence=0.8,
        )
        self.assertIsNone(item.bbox_px)

    def test_rejects_invalid_object_category(self) -> None:
        with self.assertRaises(ValueError):
            VLMObject(
                label="积木",
                category="unknown",
                description="一块积木",
                confidence=0.8,
            )

    def test_rejects_invalid_confidence(self) -> None:
        with self.assertRaises(ValueError):
            VLMObject(
                label="积木",
                category="object",
                description="一块积木",
                confidence=1.2,
            )


if __name__ == "__main__":
    unittest.main()
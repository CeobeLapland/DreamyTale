import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline.models.i2v import I2VRequest
from pipeline.models.volcengine_i2v import VolcengineI2VProvider


class VolcengineI2VTests(unittest.TestCase):
    def test_available_requires_key_and_model(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"ARK_API_KEY": "", "ARK_MODEL_ID": ""},
            clear=False,
        ):
            provider = VolcengineI2VProvider(
                api_key_env="ARK_API_KEY",
                model_env="ARK_MODEL_ID",
            )
            self.assertFalse(provider.available())

    def test_builds_image_and_text_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "page.png"
            image.write_bytes(b"fake-png")
            with mock.patch.dict(
                os.environ,
                {
                    "ARK_API_KEY": "test-key",
                    "ARK_MODEL_ID": "test-model",
                },
                clear=False,
            ):
                provider = VolcengineI2VProvider(
                    api_key_env="ARK_API_KEY",
                    model_env="ARK_MODEL_ID",
                    image_mode="data_url",
                    extra={"watermark": False},
                )
                payload = provider._build_payload(
                    I2VRequest(
                        image_path=image,
                        prompt="人物挥手",
                        negative_prompt="角色变形",
                        duration_ms=5000,
                        seed=7,
                    )
                )

        self.assertEqual("test-model", payload["model"])
        self.assertEqual(5, payload["duration"])
        self.assertEqual(7, payload["seed"])
        self.assertEqual(False, payload["watermark"])
        self.assertTrue(
            payload["content"][1]["image_url"]["url"].startswith(
                "data:image/png;base64,"
            )
        )
        self.assertIn("人物挥手", payload["content"][0]["text"])
        self.assertIn("角色变形", payload["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
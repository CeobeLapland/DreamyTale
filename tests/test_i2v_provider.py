import tempfile
import unittest
from pathlib import Path

from pipeline.models import build_i2v
from pipeline.models.i2v import I2VRequest, NullI2V


class I2VProviderTests(unittest.TestCase):
    def test_null_provider_is_fallback(self) -> None:
        provider = build_i2v({"i2v": {"provider": "null"}})
        self.assertIsInstance(provider, NullI2V)
        self.assertFalse(provider.available())

    def test_null_generate_fails_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(RuntimeError):
                NullI2V().generate(
                    I2VRequest(
                        image_path=root / "page.png",
                        prompt="人物挥手",
                        negative_prompt="变形",
                        duration_ms=3000,
                        seed=1,
                    ),
                    root / "scene.mp4",
                )


if __name__ == "__main__":
    unittest.main()
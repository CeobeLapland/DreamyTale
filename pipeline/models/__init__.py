"""Model providers: OCR, VLM, and (later) LLM / TTS / ASR / I2V."""

from .base import OCRItem, OCRProvider, VLMProvider, VLMResult
from .null import NullOCR, NullVLM
from .openai_compat import OpenAICompatibleVLM
from .rapidocr_provider import RapidOCRProvider
from .registry import ProviderStatus, build_ocr, build_vlm, config_path, load_config, status

__all__ = [
    "OCRItem",
    "OCRProvider",
    "VLMProvider",
    "VLMResult",
    "NullOCR",
    "NullVLM",
    "OpenAICompatibleVLM",
    "RapidOCRProvider",
    "ProviderStatus",
    "build_ocr",
    "build_vlm",
    "config_path",
    "load_config",
    "status",
]

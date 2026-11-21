"""Model providers: OCR, VLM, LLM, and (later) TTS / ASR / I2V."""

from .base import OCRItem, OCRProvider, VLMProvider, VLMResult
from .llm import ChatLLM
from .null import NullOCR, NullVLM
from .ollama_provider import OllamaProvider
from .openai_compat import OpenAICompatibleVLM, extract_json
from .rapidocr_provider import RapidOCRProvider
from .registry import (
    ProviderStatus,
    build_llm,
    build_ocr,
    build_vlm,
    config_path,
    load_config,
    status,
)

__all__ = [
    "OCRItem",
    "OCRProvider",
    "VLMProvider",
    "VLMResult",
    "ChatLLM",
    "NullOCR",
    "NullVLM",
    "OllamaProvider",
    "OpenAICompatibleVLM",
    "RapidOCRProvider",
    "ProviderStatus",
    "build_llm",
    "build_ocr",
    "build_vlm",
    "config_path",
    "extract_json",
    "load_config",
    "status",
]

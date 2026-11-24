"""Model providers: OCR, VLM, LLM, ASR, and (later) TTS / I2V."""

from .asr import FasterWhisperASR, NullASR, decode_audio
from .base import ASRProvider, ASRResult, OCRItem, OCRProvider, VLMProvider, VLMResult
from .llm import ChatLLM
from .i2v import I2VProvider, I2VRequest, NullI2V
from .null import NullOCR, NullVLM
from .ollama_provider import OllamaProvider
from .openai_compat import OpenAICompatibleVLM, extract_json
from .rapidocr_provider import RapidOCRProvider
from .registry import (
    ProviderStatus,
    build_asr,
    build_i2v,
    build_llm,
    build_ocr,
    build_vlm,
    config_path,
    load_config,
    status,
)
from .volcengine_i2v import VolcengineI2VProvider

__all__ = [
    "ASRProvider",
    "ASRResult",
    "OCRItem",
    "OCRProvider",
    "VLMProvider",
    "VLMResult",
    "ChatLLM",
    "FasterWhisperASR",
    "NullASR",
    "NullOCR",
    "NullVLM",
    "OllamaProvider",
    "OpenAICompatibleVLM",
    "RapidOCRProvider",
    "ProviderStatus",
    "build_asr",
    "build_i2v",
    "build_llm",
    "build_ocr",
    "build_vlm",
    "config_path",
    "decode_audio",
    "extract_json",
    "load_config",
    "status",
    "I2VProvider",
    "I2VRequest",
    "NullI2V",
    "VolcengineI2VProvider",
]

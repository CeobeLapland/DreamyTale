"""Provider registry.

`config/models.yaml` decides which provider is used; pipeline code only sees the
OCRProvider / VLMProvider protocols. Swap providers by editing the config.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .base import OCRProvider, VLMProvider
from .llm import ChatLLM
from .null import NullOCR, NullVLM
from .ollama_provider import OllamaProvider
from .openai_compat import OpenAICompatibleVLM
from .rapidocr_provider import RapidOCRProvider

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "models.yaml"


@dataclass(frozen=True)
class ProviderStatus:
    kind: str
    provider: str
    available: bool
    detail: str


def config_path(path: str | Path | None = None) -> Path:
    if path:
        return Path(path)
    return Path(os.environ.get("MODELS_CONFIG") or DEFAULT_CONFIG)


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    target = config_path(path)
    if not target.exists():
        return {}
    data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{target}: top-level config must be a mapping")
    return data


def _provider_names(section: dict[str, Any]) -> list[str]:
    names: list[str] = []
    primary = section.get("provider")
    if primary:
        names.append(str(primary))
    for name in section.get("fallback", []) or []:
        if name and str(name) not in names:
            names.append(str(name))
    return names


def _make_ocr(name: str, section: dict[str, Any]) -> OCRProvider:
    if name == "rapidocr":
        opts = section.get("rapidocr", {}) or {}
        return RapidOCRProvider(**opts)
    return NullOCR()


def _make_vlm(name: str, section: dict[str, Any]) -> VLMProvider:
    if name == "ollama":
        opts = section.get("ollama", {}) or {}
        return OllamaProvider(**opts)
    if name == "openai_compatible":
        opts = section.get("openai_compatible", {}) or {}
        return OpenAICompatibleVLM(**opts)
    return NullVLM()


def _make_llm(name: str, section: dict[str, Any]) -> ChatLLM:
    if name == "openai_compatible":
        opts = section.get("openai_compatible", {}) or {}
        return ChatLLM(**opts)
    return ChatLLM(base_url="", model="")


def build_ocr(config: dict[str, Any] | None = None) -> OCRProvider:
    cfg = config if config is not None else load_config()
    section = cfg.get("ocr", {}) or {}
    for name in _provider_names(section):
        provider = _make_ocr(name, section)
        if provider.available():
            return provider
    return NullOCR()


def build_vlm(config: dict[str, Any] | None = None) -> VLMProvider:
    cfg = config if config is not None else load_config()
    section = cfg.get("vlm", {}) or {}
    for name in _provider_names(section):
        provider = _make_vlm(name, section)
        if provider.available():
            return provider
    return NullVLM()


def build_llm(config: dict[str, Any] | None = None) -> ChatLLM:
    cfg = config if config is not None else load_config()
    section = cfg.get("llm", {}) or {}
    for name in _provider_names(section):
        provider = _make_llm(name, section)
        if provider.available():
            return provider
    return ChatLLM(base_url="", model="")


def _probe_status(
    kind: str,
    section: dict[str, Any],
    factory: Any,
) -> ProviderStatus:
    """Report the configured provider, not the null fallback, with the reason."""
    names = _provider_names(section)
    detail = ""
    for name in names:
        provider = factory(name, section)
        if provider.available():
            return ProviderStatus(kind, provider.name, True, "")
        if not detail:
            # The primary provider's reason is the one worth reading.
            detail = getattr(provider, "detail", "") or f"{name} unavailable"
    return ProviderStatus(kind, names[0] if names else "null", False, detail)


def status(config: dict[str, Any] | None = None) -> list[ProviderStatus]:
    cfg = config if config is not None else load_config()
    return [
        _probe_status("ocr", cfg.get("ocr", {}) or {}, _make_ocr),
        _probe_status("vlm", cfg.get("vlm", {}) or {}, _make_vlm),
        _probe_status("llm", cfg.get("llm", {}) or {}, _make_llm),
    ]

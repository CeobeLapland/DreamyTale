"""Local Ollama VLM provider (native API).

Why a dedicated provider instead of the OpenAI-compatible one: Ollama's native
`/api/chat` accepts images and a JSON response format without an API key, and it
tells us exactly which models are pulled. Everything stays on localhost, so the
competition material never leaves the machine.

If Ollama is not running or the model is not pulled, `available()` is False and
the pipeline falls back to manual (human-written) narratives.
"""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any

import requests

from .base import VLMResult


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5vl:7b",
        timeout: float = 120.0,
        temperature: float = 0.1,
        keep_alive: str = "10m",
        **kwargs: Any,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.keep_alive = keep_alive
        self.extra = kwargs
        self._probed: bool | None = None
        self._models: list[str] | None = None
        self._error: str | None = None

    # -- availability -----------------------------------------------------

    def _pull_models(self) -> list[str]:
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=3.0)
            response.raise_for_status()
        except requests.RequestException as exc:
            self._error = f"ollama unreachable: {exc}"
            return []
        payload = response.json()
        names = [
            str(item.get("name") or item.get("model") or "")
            for item in payload.get("models", [])
            if isinstance(item, dict)
        ]
        self._models = [name for name in names if name]
        return self._models

    def available(self) -> bool:
        if self._probed is None:
            models = self._pull_models()
            self._probed = bool(models) and self._model_present(models)
        return bool(self._probed)

    def _model_present(self, models: list[str]) -> bool:
        if not self.model:
            return False
        wanted = self.model.split(":")[0]
        for name in models:
            if name == self.model or name.split(":")[0] == wanted:
                return True
        self._error = f"model {self.model} not pulled (have: {', '.join(models) or 'none'})"
        return False

    @property
    def detail(self) -> str:
        return self._error or ""

    # -- inference --------------------------------------------------------

    def describe(
        self,
        image_path: Path,
        prompt: str,
        json_schema: dict[str, Any] | None = None,
    ) -> VLMResult:
        mime = mimetypes.guess_type(str(image_path))[0] or "image/png"
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [encoded],
                }
            ],
            "stream": False,
            "format": "json" if json_schema else None,
            "keep_alive": self.keep_alive,
            "options": {"temperature": self.temperature},
        }
        if payload["format"] is None:
            payload.pop("format")

        response = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        body = response.json()
        message = body.get("message") or {}
        text = str(message.get("content") or "").strip()

        data = None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        return VLMResult(text=text, data=data)

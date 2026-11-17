"""OpenAI-compatible VLM provider.

Works with Ollama (`http://127.0.0.1:11434/v1`), LM Studio
(`http://127.0.0.1:1234/v1`), vLLM, and any hosted OpenAI-compatible endpoint.
No vendor SDK; one HTTP shape.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .base import VLMResult


class OpenAICompatibleVLM:
    name = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key_env: str = "VLM_API_KEY",
        timeout: float = 120.0,
        max_tokens: int = 1024,
        temperature: float = 0.1,
        **kwargs: Any,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_env = api_key_env
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.extra = kwargs
        self._probed: bool | None = None

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) or None

    def available(self) -> bool:
        if not self.base_url or not self.model:
            return False
        if self.api_key:
            return True
        host = (urlparse(self.base_url).hostname or "").lower()
        local = host in {"127.0.0.1", "localhost", "::1"} or "ollama" in host or "lmstudio" in host
        if not local:
            return False
        if self._probed is None:
            try:
                response = requests.get(f"{self.base_url}/models", timeout=2.0)
                self._probed = response.ok
            except requests.RequestException:
                self._probed = False
        return bool(self._probed)

    def describe(
        self,
        image_path: Path,
        prompt: str,
        json_schema: dict[str, Any] | None = None,
    ) -> VLMResult:
        mime = mimetypes.guess_type(str(image_path))[0] or "image/png"
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        messages = [
            {
                "role": "system",
                "content": "You are a careful picture-book vision analyst. Answer only from the image; say when unsure.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                ],
            },
        ]
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        text = str(content).strip()

        data = None
        if json_schema:
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = None
        return VLMResult(text=text, data=data)

"""Text-only chat model provider.

Same OpenAI-compatible endpoint as the VLM, but without images: the story and
scene stages only need text. Keeping it in one provider means the model choice
lives in `config/models.yaml` and the pipeline code never imports a vendor SDK.

Dumb local models need two things to be usable:
  * `reasoning_effort: none`, otherwise the token budget goes into thinking and
    the answer comes back empty;
  * a JSON schema, so the answer is parseable by construction.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .base import VLMResult
from .openai_compat import extract_json

DEFAULT_SYSTEM = (
    "You are a careful children's book editor. Work only from the material you "
    "are given, keep it simple, and answer with the requested JSON only."
)


class ChatLLM:
    name = "chat_llm"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key_env: str = "LLM_API_KEY",
        timeout: float = 240.0,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        reasoning_effort: str = "none",
        structured_output: bool = True,
        **kwargs: Any,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_env = api_key_env
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort
        self.structured_output = structured_output
        self.extra = kwargs
        self._probed: bool | None = None
        self._error: str | None = None

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) or None

    @property
    def detail(self) -> str:
        return self._error or ""

    def available(self) -> bool:
        if not self.base_url or not self.model:
            return False
        host = (urlparse(self.base_url).hostname or "").lower()
        if self.api_key or host in {"127.0.0.1", "localhost", "::1"}:
            if self._probed is None:
                try:
                    response = requests.get(f"{self.base_url}/models", timeout=3.0)
                    self._probed = response.ok
                    if not response.ok:
                        self._error = f"model endpoint returned {response.status_code}"
                except requests.RequestException as exc:
                    self._probed = False
                    self._error = f"llm endpoint unreachable: {exc}"
            return bool(self._probed)
        return False

    def chat(
        self,
        prompt: str,
        json_schema: dict[str, Any] | None = None,
        system: str | None = None,
    ) -> VLMResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system or DEFAULT_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        if json_schema and self.structured_output:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": json_schema,
                },
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
        if response.status_code == 400 and "response_format" in payload:
            payload.pop("response_format")
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]
        text = str(message.get("content") or "").strip()
        if not text:
            text = str(message.get("reasoning_content") or "").strip()

        data = extract_json(text) if json_schema else None
        return VLMResult(text=text, data=data)

"""OpenAI-compatible VLM provider.

Works with Ollama (`http://127.0.0.1:11434/v1`), LM Studio
(`http://127.0.0.1:1234/v1`), vLLM, and any hosted OpenAI-compatible endpoint.
No vendor SDK; one HTTP shape.
"""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .base import VLMResult


def _repair_quotes(text: str) -> str:
    """Undo the most common local-model JSON mistake: a Chinese curly quote
    used as a JSON delimiter.

    Only quotes in a structural position are touched, so Chinese quotes inside
    the content itself stay intact.
    """
    chars = list(text)
    for index, char in enumerate(chars):
        if char not in "\u201c\u201d":
            continue
        previous = ""
        for back in range(index - 1, -1, -1):
            if not chars[back].isspace():
                previous = chars[back]
                break
        following = ""
        for ahead in range(index + 1, len(chars)):
            if not chars[ahead].isspace():
                following = chars[ahead]
                break
        if char == "\u201d" and following in ",}]:":
            chars[index] = '"'
        elif char == "\u201c" and previous in "{[,":
            chars[index] = '"'
    return "".join(chars)


def extract_json(text: str) -> Any | None:
    """Pull a JSON object out of a model answer.

    Local models wrap JSON in markdown fences, add a sentence after it, or
    swap a closing quote for a Chinese one, so a plain json.loads is not
    enough.
    """
    stripped = text.strip()
    if not stripped:
        return None
    candidates = [stripped]
    if stripped.startswith("```"):
        parts = stripped.split("```")
        if len(parts) >= 2:
            candidate = parts[1].strip()
            if candidate.lower().startswith("json"):
                candidate = candidate[4:].strip()
            candidates.append(candidate)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        candidates.append(stripped[start : end + 1])

    for candidate in candidates:
        for attempt in (candidate, _repair_quotes(candidate)):
            try:
                parsed = json.loads(attempt)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


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
        max_side: int = 1280,
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
        self.max_side = max_side
        self.reasoning_effort = reasoning_effort
        self.structured_output = structured_output
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

    def _encode_image(self, image_path: Path) -> tuple[str, str]:
        """Downscale before sending: a page PNG is ~2600px wide, which costs a
        lot of vision tokens and VRAM on a laptop GPU. Smaller is both faster
        and kinder to a 16GB machine."""
        mime = mimetypes.guess_type(str(image_path))[0] or "image/png"
        if not self.max_side:
            return mime, base64.b64encode(image_path.read_bytes()).decode("ascii")
        try:
            from PIL import Image

            with Image.open(image_path) as image:
                image = image.convert("RGB")
                longest = max(image.size)
                if longest > self.max_side:
                    scale = self.max_side / longest
                    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
                    image = image.resize(size, Image.LANCZOS)
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=88)
            return "image/jpeg", base64.b64encode(buffer.getvalue()).decode("ascii")
        except Exception:  # noqa: BLE001 - fall back to the original bytes
            return mime, base64.b64encode(image_path.read_bytes()).decode("ascii")

    def describe(
        self,
        image_path: Path,
        prompt: str,
        json_schema: dict[str, Any] | None = None,
    ) -> VLMResult:
        mime, encoded = self._encode_image(image_path)
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
        if self.reasoning_effort:
            # Reasoning models burn the whole token budget on thinking and can
            # return an empty answer. We want direct structured output.
            payload["reasoning_effort"] = self.reasoning_effort
        if json_schema and self.structured_output:
            # Grammar constrained decoding: the model cannot emit a Chinese
            # quote where a JSON delimiter belongs, so the answer always parses.
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
            # The server does not support structured output; ask again plainly.
            payload.pop("response_format")
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
        response.raise_for_status()
        body = response.json()
        message = body["choices"][0]["message"]
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        text = str(content).strip()
        if not text:
            # Some builds only fill reasoning_content when the answer is cut off.
            text = str(message.get("reasoning_content") or "").strip()

        data = None
        if json_schema:
            data = extract_json(text)
        return VLMResult(text=text, data=data)

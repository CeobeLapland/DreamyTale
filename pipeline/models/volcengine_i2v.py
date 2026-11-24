from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from .i2v import I2VRequest


class VolcengineI2VProvider:
    name = "volcengine_ark"

    def __init__(
        self,
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
        api_key_env: str = "ARK_API_KEY",
        model: str = "",
        model_env: str = "ARK_MODEL_ID",
        create_path: str = "/contents/generations/tasks",
        query_path: str = "/contents/generations/tasks/{task_id}",
        image_mode: str = "data_url",
        image_first: bool = False,
        ratio: str = "adaptive",
        timeout: float = 900.0,
        poll_interval: float = 5.0,
        extra: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.model = model
        self.model_env = model_env
        self.create_path = create_path
        self.query_path = query_path
        self.image_mode = image_mode
        self.image_first = image_first
        self.ratio = ratio
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.extra = extra or {}
        self.kwargs = kwargs
        self.detail = ""

    def available(self) -> bool:
        if not self.api_key:
            self.detail = f"API key missing: {self.api_key_env}"
            return False
        if not self.model_id:
            self.detail = f"model ID missing: {self.model_env}"
            return False
        self.detail = ""
        return True

    @property
    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "").strip()

    @property
    def model_id(self) -> str:
        return (
            os.environ.get(self.model_env, "").strip()
            or self.model.strip()
        )

    def generate(self, request: I2VRequest, out_path: Path) -> Path:
        if not self.available():
            raise RuntimeError(self.detail or "Volcengine I2V unavailable")

        payload = self._build_payload(request)
        task_id = self._create_task(payload)
        task = self._wait_for_task(task_id)
        video_url = self._find_video_url(task)
        if not video_url:
            raise RuntimeError(
                f"video URL missing from task response: {json.dumps(task, ensure_ascii=False)[:2000]}"
            )
        self._download(video_url, out_path)
        return out_path

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, request: I2VRequest) -> dict[str, Any]:
        image_value = self._image_value(request)
        text = request.prompt.strip()
        if request.negative_prompt.strip():
            text += "\n避免出现：" + request.negative_prompt.strip()

        text_item = {
            "type": "text",
            "text": text,
        }
        image_item = {
            "type": "image_url",
            "image_url": {
                "url": image_value,
            },
        }
        content = (
            [image_item, text_item]
            if self.image_first
            else [text_item, image_item]
        )

        payload: dict[str, Any] = {
            "model": self.model_id,
            "content": content,
            "duration": max(
                1,
                round(request.duration_ms / 1000),
            ),
        }
        if self.ratio:
            payload["ratio"] = self.ratio
        if request.seed is not None:
            payload["seed"] = int(request.seed)
        payload.update(self.extra)
        return payload

    def _image_value(self, request: I2VRequest) -> str:
        if request.image_url:
            return request.image_url

        if self.image_mode != "data_url":
            raise ValueError(
                "image_url is required when image_mode is not data_url"
            )

        mime = mimetypes.guess_type(str(request.image_path))[0] or "image/png"
        encoded = base64.b64encode(
            request.image_path.read_bytes()
        ).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def _create_task(self, payload: dict[str, Any]) -> str:
        response = requests.post(
            f"{self.base_url}{self.create_path}",
            headers=self._headers(),
            json=payload,
            timeout=120,
        )
        self._raise_for_status(response)
        body = response.json()
        task_id = self._find_first(
            body,
            ("task_id", "id"),
        )
        if not task_id:
            raise RuntimeError(
                f"task ID missing from response: {json.dumps(body, ensure_ascii=False)[:2000]}"
            )
        return str(task_id)

    def _wait_for_task(self, task_id: str) -> dict[str, Any]:
        task_path = self.query_path.format(
            task_id=quote(str(task_id), safe=""),
        )
        deadline = time.monotonic() + self.timeout
        last_body: dict[str, Any] = {}

        while time.monotonic() < deadline:
            response = requests.get(
                f"{self.base_url}{task_path}",
                headers=self._headers(),
                timeout=60,
            )
            self._raise_for_status(response)
            body = response.json()
            last_body = body if isinstance(body, dict) else {"data": body}
            status = str(
                self._find_first(body, ("status", "state")) or ""
            ).lower()

            if status in {
                "succeeded",
                "success",
                "completed",
                "done",
            }:
                return last_body
            if status in {
                "failed",
                "error",
                "cancelled",
                "canceled",
            }:
                reason = self._find_first(
                    body,
                    ("error", "fail_reason", "message"),
                )
                raise RuntimeError(
                    f"video task {task_id} {status}: {reason or body}"
                )
            time.sleep(self.poll_interval)

        raise TimeoutError(
            f"video task timed out: {task_id}; last={last_body}"
        )

    def _download(self, video_url: str, out_path: Path) -> None:
        response = requests.get(
            video_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            stream=True,
            timeout=300,
        )
        self._raise_for_status(response)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = out_path.with_suffix(out_path.suffix + ".part")
        try:
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
            temporary.replace(out_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _find_video_url(self, body: Any) -> str | None:
        if isinstance(body, dict):
            preferred = (
                "video_url",
                "output_url",
                "file_url",
                "download_url",
            )
            for key in preferred:
                value = body.get(key)
                if isinstance(value, str) and value.startswith("http"):
                    return value
            for key, value in body.items():
                if isinstance(value, str) and value.startswith("http"):
                    lowered = key.lower()
                    if "video" in lowered or value.lower().endswith(".mp4"):
                        return value
                found = self._find_video_url(value)
                if found:
                    return found
        elif isinstance(body, list):
            for item in body:
                found = self._find_video_url(item)
                if found:
                    return found
        return None

    def _find_first(
        self,
        body: Any,
        keys: tuple[str, ...],
    ) -> Any:
        if isinstance(body, dict):
            for key in keys:
                value = body.get(key)
                if value is not None:
                    return value
            for value in body.values():
                found = self._find_first(value, keys)
                if found is not None:
                    return found
        elif isinstance(body, list):
            for item in body:
                found = self._find_first(item, keys)
                if found is not None:
                    return found
        return None

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        if response.ok:
            return
        try:
            detail = response.json()
        except ValueError:
            detail = response.text[-2000:]
        raise RuntimeError(
            f"Volcengine HTTP {response.status_code}: {detail}"
        )
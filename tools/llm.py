#!/usr/bin/env python3
"""模型接入层。所有对外部模型的调用都必须走这里。

为什么要有这一层：
key、重试、超时、流式、缓存、计量，这六件事只要有一样散落在业务代码里，
换个供应商就要改十个文件。集中在这里，业务侧永远只写一句话。

协议用 OpenAI 兼容格式——通义、智谱、Kimi、DeepSeek、OpenAI、vLLM、Ollama
都支持这套，所以不需要为每家写适配器。

配置走环境变量，不写进代码：
    LLM_BASE_URL     例 https://api.deepseek.com/v1
    LLM_API_KEY
    LLM_MODEL        例 deepseek-chat
    LLM_VL_MODEL     视觉模型，例 qwen-vl-max
    LLM_EMBED_MODEL  向量模型，例 text-embedding-3-small

零依赖：只用标准库 urllib，不装 httpx 也能跑。
"""

import base64
import hashlib
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "llm"
TRACE = ROOT / "data" / "traces" / "llm"


class MissingConfig(RuntimeError):
    pass


_DETECTED = {}


def _list_models(base_url: str, api_key: str, timeout: float = 4.0) -> list:
    """问服务要模型列表。失败就返回空——探测是锦上添花，不能让主流程挂掉。"""
    try:
        req = urllib.request.Request(base_url + "/models",
                                     headers={"Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m.get("id") for m in data.get("data") or [] if m.get("id")]
    except Exception:                                        # noqa: BLE001
        return []


def _guess(models: list) -> dict:
    """从模型名猜用途。猜错也没关系，环境变量永远优先。"""
    def find(*keys):
        for m in models:
            low = m.lower()
            if any(k in low for k in keys):
                return m
        return ""

    embed = find("embed", "bge", "gte-", "nomic", "e5-", "text-embedding")
    vision = find("vl", "vision", "llava", "minicpm-v", "janus", "-v-", "moondream")
    chat = next((m for m in models if m not in (embed, vision)), "")
    return {"embed": embed, "vision": vision, "chat": chat or (models[0] if models else "")}


def _load_dotenv():
    """读仓库根的 .env.local 当默认值。环境变量永远优先，所以不会盖掉 CI 配置。"""
    if os.getenv("LLM_NO_DOTENV"):
        return          # 测试和 CI 用这个开关，避免本地配置污染断言
    p = ROOT / ".env.local"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and not os.getenv(k):
            os.environ[k] = v


def config() -> dict:
    _load_dotenv()
    c = _config_raw()
    if not (c["base_url"] and c["api_key"]):
        return c
    if not (c["model"] or c["embed_model"] or c["vl_model"]):
        key = c["base_url"]
        if key not in _DETECTED:
            models = _list_models(c["base_url"], c["api_key"])
            _DETECTED[key] = _guess(models) if models else {}
            if models:
                print(f"[llm] 自动探测到 {len(models)} 个模型：{', '.join(models)}",
                      file=sys.stderr)
        for k in ("model", "vl_model", "embed_model"):
            short = {"model": "chat", "vl_model": "vision", "embed_model": "embed"}[k]
            if not c[k] and _DETECTED[key].get(short):
                c[k] = _DETECTED[key][short]
    return c


def _config_raw() -> dict:
    return {
        "base_url": (os.getenv("LLM_BASE_URL") or "").rstrip("/"),
        "api_key": os.getenv("LLM_API_KEY") or "",
        "model": os.getenv("LLM_MODEL") or "",
        "vl_model": os.getenv("LLM_VL_MODEL") or "",
        "embed_model": os.getenv("LLM_EMBED_MODEL") or "",
        "timeout": float(os.getenv("LLM_TIMEOUT") or 60),
    }


def available(kind: str = "chat") -> bool:
    c = config()
    if not (c["base_url"] and c["api_key"]):
        return False
    if kind == "chat":
        return bool(c["model"])
    if kind == "vision":
        # 不拿文本模型顶替。看不见图的模型接上去只会输出幻觉，
        # 而且错误会藏在"看起来正常"的文字里——比直接报错糟得多。
        return bool(c["vl_model"])
    if kind == "embed":
        return bool(c["embed_model"])
    return False


def _require(kind: str) -> dict:
    c = config()
    if not c["base_url"] or not c["api_key"]:
        raise MissingConfig(
            "没有配置模型接入。设好这两个环境变量就能跑：\n"
            "  LLM_BASE_URL=https://api.deepseek.com/v1\n"
            "  LLM_API_KEY=sk-...\n"
            "  LLM_MODEL=deepseek-chat\n"
            "（通义、智谱、Kimi、OpenAI 都是同一套 OpenAI 兼容协议）")
    if kind == "chat" and not c["model"]:
        raise MissingConfig("缺 LLM_MODEL")
    if kind == "embed" and not c["embed_model"]:
        raise MissingConfig("缺 LLM_EMBED_MODEL")
    if kind == "vision" and not c["vl_model"]:
        raise MissingConfig("缺 LLM_VL_MODEL：需要一个能看图的模型")
    return c


def _unwrap_reasoning(resp: dict, payload: dict, cfg: dict):
    """推理模型会把 token 全花在 reasoning_content 上，content 是空的。

    这不是错误，是模型特性。遇到就用三倍预算重试一次；还空就返回空串，
    让上层走降级——不要拿思考过程冒充答案。
    """
    choice = (resp.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    text = msg.get("content") or ""
    truncated = choice.get("finish_reason") == "length"
    if text.strip() or not truncated:
        return text, resp

    retry = dict(payload)
    retry["max_tokens"] = int(payload.get("max_tokens", 800)) * 3
    resp2 = _post("/chat/completions", retry, cfg)
    msg2 = ((resp2.get("choices") or [{}])[0].get("message") or {})
    return (msg2.get("content") or ""), resp2


def _cache_key(kind: str, payload: dict) -> str:
    blob = json.dumps({"kind": kind, **payload}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _cache_get(key: str):
    p = CACHE / key[:2] / f"{key}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    return None


def _cache_put(key: str, value):
    p = CACHE / key[:2] / f"{key}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _log(entry: dict):
    TRACE.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y-%m-%d")
    with (TRACE / f"{day}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _post(path: str, payload: dict, cfg: dict, retries: int = 3) -> dict:
    """带退避的 POST。429 和 5xx 重试，4xx 直接抛——别拿重试掩盖配置错误。"""
    url = cfg["base_url"] + path
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {cfg['api_key']}"}

    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:300]
            last = f"HTTP {e.code}: {detail}"
            if e.code == 429 or 500 <= e.code < 600:
                time.sleep(1.5 ** attempt)
                continue
            raise RuntimeError(last) from None
        except (urllib.error.URLError, socket.timeout) as e:
            last = f"网络错误: {e}"
            time.sleep(1.5 ** attempt)
    raise RuntimeError(f"重试 {retries} 次仍失败：{last}")


def chat(messages, *, model=None, temperature=0.2, max_tokens=800,
         json_mode=False, use_cache=True, tag="") -> str:
    """普通对话。返回纯文本。"""
    cfg = _require("chat")
    model = model or cfg["model"]
    payload = {"model": model, "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    key = _cache_key("chat", payload)
    if use_cache:
        hit = _cache_get(key)
        if hit:
            _log({"ts": datetime.now().isoformat(timespec="seconds"), "kind": "chat",
                  "model": model, "tag": tag, "ms": 0, "cache": True})
            return hit["text"]

    t0 = time.perf_counter()
    resp = _post("/chat/completions", payload, cfg)
    text, resp = _unwrap_reasoning(resp, payload, cfg)
    ms = int((time.perf_counter() - t0) * 1000)
    usage = resp.get("usage") or {}

    # 空回答不写缓存。写进去就会污染后续所有同问调用——
    # 一次超时能让这个问题永久失效，这个坑必须堵死。
    if use_cache and text.strip():
        _cache_put(key, {"text": text, "model": model})
    _log({"ts": datetime.now().isoformat(timespec="seconds"), "kind": "chat",
          "model": model, "tag": tag, "ms": ms, "cache": False,
          "in": usage.get("prompt_tokens"), "out": usage.get("completion_tokens")})
    return text


def chat_stream(messages, *, model=None, temperature=0.2, tag=""):
    """流式对话，逐增量 yield。TTS 要首句先出，就必须走这条。"""
    cfg = _require("chat")
    model = model or cfg["model"]
    payload = {"model": model, "messages": messages,
               "temperature": temperature, "stream": True}
    url = cfg["base_url"] + "/chat/completions"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {cfg['api_key']}"})

    t0 = time.perf_counter()
    first = None
    with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            delta = (chunk.get("choices") or [{}])[0].get("delta", {})
            piece = delta.get("content")
            if piece:
                if first is None:
                    first = int((time.perf_counter() - t0) * 1000)
                yield piece

    _log({"ts": datetime.now().isoformat(timespec="seconds"), "kind": "chat_stream",
          "model": model, "tag": tag, "first_token_ms": first,
          "total_ms": int((time.perf_counter() - t0) * 1000)})


def vision(image_path, prompt, *, model=None, max_tokens=900, tag="") -> str:
    """看图说话。图片以 data URL 内联，避免本地文件对外暴露。"""
    cfg = _require("vision")
    model = model or cfg["vl_model"]
    data = Path(image_path).read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    mime = "image/png" if str(image_path).lower().endswith(".png") else "image/jpeg"

    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url",
         "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ]}]
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens}

    key = _cache_key("vision", {"model": model, "prompt": prompt,
                                "img": hashlib.sha256(data).hexdigest()[:16]})
    hit = _cache_get(key)
    if hit:
        _log({"ts": datetime.now().isoformat(timespec="seconds"), "kind": "vision",
              "model": model, "tag": tag, "ms": 0, "cache": True})
        return hit["text"]

    t0 = time.perf_counter()
    resp = _post("/chat/completions", payload, cfg)
    ms = int((time.perf_counter() - t0) * 1000)
    text = (resp.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    if text.strip():
        _cache_put(key, {"text": text, "model": model})
    _log({"ts": datetime.now().isoformat(timespec="seconds"), "kind": "vision",
          "model": model, "tag": tag, "ms": ms, "cache": False})
    return text


def embed(texts, *, model=None, tag="") -> list:
    """文本向量。检索层靠它解决"搭的是什么"和"搭城堡"没有字面重叠的问题。"""
    cfg = _require("embed")
    model = model or cfg["embed_model"]
    items = [texts] if isinstance(texts, str) else list(texts)
    if not items:
        return []

    payload = {"model": model, "input": items}
    key = _cache_key("embed", {"model": model, "items": items})
    hit = _cache_get(key)
    if hit:
        _log({"ts": datetime.now().isoformat(timespec="seconds"), "kind": "embed",
              "model": model, "tag": tag, "ms": 0, "cache": True, "n": len(items)})
        return hit["vectors"]

    t0 = time.perf_counter()
    resp = _post("/embeddings", payload, cfg)
    ms = int((time.perf_counter() - t0) * 1000)
    vectors = [d.get("embedding") or [] for d in resp.get("data") or []]
    _cache_put(key, {"vectors": vectors, "model": model})
    _log({"ts": datetime.now().isoformat(timespec="seconds"), "kind": "embed",
          "model": model, "tag": tag, "ms": ms, "cache": False, "n": len(items)})
    return vectors


def status() -> str:
    c = config()
    lines = ["模型接入状态："]
    if not c["base_url"]:
        lines.append("  ✗ 未配置。设 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 即可")
        return "\n".join(lines)
    lines.append(f"  base_url  {c['base_url']}")
    lines.append(f"  chat      {'✓ ' + c['model'] if c['model'] else '✗ 缺 LLM_MODEL'}")
    lines.append(f"  vision    {'✓ ' + c['vl_model'] if c['vl_model'] else '✗ 缺 LLM_VL_MODEL（英文书的叙事层需要它）'}")
    lines.append(f"  embed     {'✓ ' + c['embed_model'] if c['embed_model'] else '✗ 缺 LLM_EMBED_MODEL'}")
    n = len(list(CACHE.rglob("*.json"))) if CACHE.exists() else 0
    lines.append(f"  缓存      {n} 条（data/cache/llm）")
    return "\n".join(lines)


if __name__ == "__main__":
    print(status())
    if "--ping" in sys.argv:
        try:
            print("\n试探一次：", repr(chat(
                [{"role": "user", "content": "只回复 pong，不要任何其他内容"}],
                max_tokens=300, tag="ping")))
        except (MissingConfig, RuntimeError) as e:
            print(f"\n失败：{e}")
            sys.exit(1)

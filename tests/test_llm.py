#!/usr/bin/env python3
"""接入层自测：起一个假的 OpenAI 兼容服务，不需要真 key。

    python tests/test_llm.py

验四件事：普通调用、缓存命中、流式增量、错误重试。
真接上供应商之后这套测试仍然有用——它测的是我们的客户端，不是他们的服务。
"""

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

CALLS = {"chat": 0, "stream": 0, "fail": 0}


class Mock(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.endswith("/models"):
            return self._json({"data": [
                {"id": "qwen2.5-7b-instruct"},
                {"id": "bge-m3-embed"},
                {"id": "qwen2-vl-7b"},
            ]})
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        req = json.loads(self.rfile.read(n) or b"{}")

        if req.get("stream"):
            CALLS["stream"] += 1
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for piece in ("纸", "书", "智", "伴"):
                chunk = {"choices": [{"delta": {"content": piece}}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
                time.sleep(0.01)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        user = ""
        for m in req.get("messages") or []:
            if m.get("role") == "user":
                c = m.get("content")
                user = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)

        if "FAIL_ONCE" in user and CALLS["fail"] == 0:
            CALLS["fail"] += 1
            return self._json({"error": "boom"}, 500)

        CALLS["chat"] += 1
        self._json({"choices": [{"message": {"content": f"echo:{user}"}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 2}})


def main():
    port = 8799
    srv = ThreadingHTTPServer(("127.0.0.1", port), Mock)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    os.environ["LLM_NO_DOTENV"] = "1"      # 别让 .env.local 里的真实模型名混进来
    os.environ["LLM_BASE_URL"] = f"http://127.0.0.1:{port}/v1"
    os.environ["LLM_API_KEY"] = "test-key"
    os.environ["LLM_MODEL"] = "mock-model"

    import llm

    ok = True

    print("1. 普通调用")
    r1 = llm.chat([{"role": "user", "content": "你好"}], tag="t1")
    print("   ", r1)
    ok &= r1 == "echo:你好"

    print("2. 缓存命中（不该再发请求）")
    before = CALLS["chat"]
    r2 = llm.chat([{"role": "user", "content": "你好"}], tag="t1")
    print(f"    {r2} · 新增请求 {CALLS['chat'] - before} 次")
    ok &= (r2 == r1 and CALLS["chat"] == before)

    print("3. 流式增量")
    pieces = list(llm.chat_stream([{"role": "user", "content": "讲一句"}], tag="t2"))
    print("   ", "".join(pieces), f"（{len(pieces)} 段）")
    ok &= "".join(pieces) == "纸书智伴" and len(pieces) == 4

    print("4. 500 后重试成功")
    t0 = time.perf_counter()
    r3 = llm.chat([{"role": "user", "content": "FAIL_ONCE 测试"}], tag="t3",
                  use_cache=False)
    print(f"    {r3} · 耗时 {int((time.perf_counter()-t0)*1000)}ms")
    ok &= r3.startswith("echo:") and CALLS["fail"] == 1

    print("5. 自动探测模型")
    for k in ("LLM_MODEL", "LLM_VL_MODEL", "LLM_EMBED_MODEL"):
        os.environ.pop(k, None)
    import importlib
    importlib.reload(llm)
    c = llm.config()
    print(f"    chat={c['model']} · vl={c['vl_model']} · embed={c['embed_model']}")
    ok &= c["model"] == "qwen2.5-7b-instruct"
    ok &= c["embed_model"] == "bge-m3-embed"
    ok &= c["vl_model"] == "qwen2-vl-7b"

    srv.shutdown()
    print("\n全部通过" if ok else "\n有失败项")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

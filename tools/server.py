#!/usr/bin/env python3
"""本地演示服务：把执行器接到浏览器上。

    python tasks.py serve            # http://127.0.0.1:8765

"视频"暂时是页图序列，由 shots.jsonl 的时间轴驱动——
和真视频用的是同一套契约，换成 mp4 时前端只改取帧那一行。
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify import classify                       # noqa: E402
from executor import Book, Session, execute         # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DATA = ROOT / "data" / "books"
PORT = 8765

SESSIONS = {}
LOCK = threading.Lock()
BOOKS = {}


def load_book(book_id: str):
    if book_id not in BOOKS:
        book = Book(book_id)
        if not book.has_timeline:
            return None
        shots = []
        for s in book.shots:
            shots.append({
                "shot_id": s["shot_id"],
                "page_no": s.get("page_no"),
                "t_start": s["t_start"],
                "t_end": s["t_end"],
                "script_line": s.get("script_line", ""),
                "subtitles": s.get("subtitles") or [],
                "objects": [{"entity": o.get("entity"), "bbox": o.get("bbox")}
                            for o in (s.get("objects") or [])],
            })
        pages = {d["page_no"]: {"w": d["width"], "h": d["height"],
                                "src": d["image_path"]}
                 for d in book.docs}
        queries = []
        qpath = ROOT / "data" / "queries" / f"{book_id}.jsonl"
        if qpath.exists():
            queries = [json.loads(l) for l in qpath.read_text(encoding="utf-8").splitlines()
                       if l.strip()]
        BOOKS[book_id] = {"book": book, "shots": shots, "pages": pages,
                          "queries": queries}
    return BOOKS[book_id]


def list_books():
    out = []
    if not DATA.is_dir():
        return out
    for d in sorted(DATA.iterdir()):
        if (d / "shots.jsonl").exists():
            pages = sum(1 for _ in (d / "docs.jsonl").open(encoding="utf-8")) \
                if (d / "docs.jsonl").exists() else 0
            meta = {}
            if (d / "book.json").exists():
                meta = json.loads((d / "book.json").read_text(encoding="utf-8"))
            out.append({"book_id": d.name, "pages": pages,
                        "content_type": meta.get("content_type", "narrative"),
                        "text_layer": meta.get("text_layer", "?")})
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html"):
            return self._file(WEB / "index.html", "text/html; charset=utf-8")
        if path.startswith("/web/"):
            return self._file(WEB / path[5:], None)
        if path.startswith("/data/books/"):
            target = (ROOT / path.lstrip("/")).resolve()
            if not str(target).startswith(str(DATA.resolve())):
                return self._json({"error": "forbidden"}, 403)
            ctype = "image/png" if target.suffix == ".png" else "application/octet-stream"
            return self._file(target, ctype)
        if path == "/api/books":
            return self._json(list_books())
        if path.startswith("/api/book/"):
            bid = path[len("/api/book/"):]
            loaded = load_book(bid)
            if not loaded:
                return self._json({"error": "这本书还没有时间轴，先跑 timeline"}, 404)
            return self._json({
                "book_id": bid,
                "shots": loaded["shots"],
                "pages": {str(k): v for k, v in loaded["pages"].items()},
                "queries": [{"seq": q["seq"], "kind": q["kind"],
                             "raw_text": q["raw_text"], "required": q["required"]}
                            for q in loaded["queries"]],
            })
        if path == "/api/state":
            q = urlparse(self.path).query
            bid = q.split("book=")[1].split("&")[0] if "book=" in q else ""
            loaded = load_book(bid)
            if not loaded:
                return self._json({"error": "没有这本书的时间轴"}, 404)
            sess = SESSIONS.get(bid) or Session(loaded["book"])
            SESSIONS[bid] = sess
            return self._json({"video_time": sess.video_time,
                               "play_state": sess.play_state,
                               "page": sess.page})
        return self._json({"error": "not found"}, 404)

    def _file(self, path: Path, ctype):
        if not path.exists() or not path.is_file():
            return self._json({"error": "not found"}, 404)
        if ctype is None:
            ctype = ("text/css" if path.suffix == ".css" else
                     "application/javascript" if path.suffix == ".js" else
                     "text/html" if path.suffix == ".html" else
                     "application/octet-stream")
        self._send(200, path.read_bytes(), ctype)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)

        if path == "/api/act":
            bid = body.get("book_id")
            text = (body.get("text") or "").strip()
            loaded = load_book(bid)
            if not loaded:
                return self._json({"error": "没有这本书"}, 404)
            with LOCK:
                sess = SESSIONS.get(bid) or Session(loaded["book"])

                # 客户端才是播放时间的权威。服务端只在需要对齐时下发 seek_to，
                # 否则每次请求都回写 video_time，播放中的画面会被拽回旧位置。
                if isinstance(body.get("client_time"), (int, float)):
                    sess.video_time = float(body["client_time"])
                if isinstance(body.get("page"), int):
                    sess.page = int(body["page"])

                if body.get("reset"):
                    sess = Session(loaded["book"])
                    SESSIONS[bid] = sess
                    return self._json({"ok": True, "reset": True})

                if body.get("goto_shot"):
                    shot = sess.shot_by_id(body["goto_shot"])
                    if shot:
                        sess.video_time = shot["t_start"]
                        sess.page = shot.get("page_no", sess.page)
                        sess.last_shot = shot["shot_id"]
                    return self._json({"ok": True, "video_time": sess.video_time})

                if body.get("turn_page"):
                    sess.turn_page(int(body["turn_page"]))
                    return self._json({"ok": True, "video_time": sess.video_time,
                                       "page": sess.page})

                if not text:
                    return self._json({"error": "空输入"}, 400)

                before = sess.video_time
                route = classify(text)
                result = execute(route, text, sess, page=sess.page)
                SESSIONS[bid] = sess

                # 只有真正"跳"了的动作才下发目标时间；问答和控制不该移动画面
                moved = abs(sess.video_time - before) > 0.01
                return self._json({
                    "route": route,
                    "result": result,
                    "seek_to": round(sess.video_time, 2) if moved else None,
                    "play_state": sess.play_state,
                    "page": sess.page,
                })

        return self._json({"error": "not found"}, 404)


def main():
    if not WEB.is_dir():
        print(f"缺前端目录：{WEB}", file=sys.stderr)
        return 1
    books = list_books()
    if not books:
        print("没有可用的书，先跑 python tasks.py timeline", file=sys.stderr)
        return 1
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"纸书智伴 · 本地演示  http://127.0.0.1:{PORT}")
    print("可用书籍：" + "、".join(b["book_id"] for b in books))
    print("Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())

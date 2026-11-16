#!/usr/bin/env python3
"""评测：把 328 条脚本按顺序回放一遍，看系统能正确响应多少。

    python tasks.py eval
    python tasks.py eval --cat qa
    python tasks.py eval --fast        # 抽 50 条

诚实说明：seek 和 qa 目前没有 ground truth（seek 要人工标时间戳，qa 要建卡），
所以它们记的是"执行了没有"，不是"做对了没有"。两栏分开报，不混在一起。
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify import classify          # noqa: E402
from executor import Book, Session, execute   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
QUERIES = ROOT / "data" / "queries"

KIND_LABEL = {
    "control": "控制", "seek": "找画面", "search": "查文字",
    "highlight": "高亮", "touch": "点击物体", "qa": "问答",
}
# 有 ground truth 可判对错的
JUDGEABLE = {"control", "search", "highlight", "touch"}


def read_jsonl(path: Path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def judge(script, route, result):
    """能判的判，判不了的记 executed。"""
    kind = script["kind"]
    if route.get("kind") != kind:
        return "route_miss"
    if kind == "control":
        return "ok" if result.get("action") == script.get("action") else "wrong"
    if kind == "seek":
        return "executed" if result.get("ok") else "miss"
    if kind in ("search", "highlight"):
        return "ok" if result.get("ok") else "miss"
    if kind == "touch":
        return "ok" if result.get("ok") else "miss"
    if kind == "qa":
        tier = result.get("tier")
        if tier in ("strong", "weak"):
            return "answered"
        if tier == "quote":
            return "quoted"      # 引用原句，不算答对
        return "guide"
    return "unknown"


def main(argv):
    cat = None
    fast = False
    for a in argv:
        if a == "--fast":
            fast = True
        elif a.startswith("--cat="):
            cat = a.split("=", 1)[1]
        elif a.startswith("--cat"):
            i = argv.index(a)
            if i + 1 < len(argv):
                cat = argv[i + 1]

    stats = {}
    by_book = {}
    fails = []
    latencies = []
    total = 0

    for path in sorted(QUERIES.glob("*.jsonl")):
        book_id = path.stem
        book = Book(book_id)
        if not book.has_timeline:
            print(f"跳过 {book_id}：没有 shots.jsonl，先跑 timeline")
            continue
        sess = Session(book)
        scripts = read_jsonl(path)
        if fast:
            scripts = scripts[::7]

        for script in scripts:
            if script["kind"] == "touch" and not script.get("click_target"):
                continue
            kind = script["kind"]
            if cat and kind != cat:
                continue

            t0 = time.perf_counter()
            route = classify(script["raw_text"])
            result = execute(route, script["raw_text"], sess)
            latencies.append((time.perf_counter() - t0) * 1000)

            verdict = judge(script, route, result)
            bucket = stats.setdefault(kind, {"n": 0, "ok": 0, "executed": 0,
                                             "answered": 0, "quoted": 0, "miss": 0,
                                             "wrong": 0, "route_miss": 0})
            bucket["n"] += 1
            total += 1
            bb = by_book.setdefault(book_id, {"judgeable": 0, "ok": 0,
                                              "seek": 0, "seek_ok": 0,
                                              "qa": 0, "qa_ok": 0})
            if kind in JUDGEABLE:
                bb["judgeable"] += 1
                bb["ok"] += 1 if verdict == "ok" else 0
            elif kind == "seek":
                bb["seek"] += 1
                bb["seek_ok"] += 1 if verdict == "executed" else 0
            elif kind == "qa":
                bb["qa"] += 1
                bb["qa_ok"] += 1 if verdict == "answered" else 0
            if verdict in bucket:
                bucket[verdict] += 1
            if verdict in ("miss", "wrong", "route_miss"):
                fails.append((book_id, script["raw_text"], kind, verdict,
                              result.get("why") or ""))

    if not total:
        print("没有可评测的数据")
        return 0

    print(f"\n{'类别':<8} {'条数':>4}  {'判对':>9}  {'执行':>5}  {'答出':>5}  {'未中':>5}")
    for kind in ("control", "seek", "search", "highlight", "touch", "qa"):
        b = stats.get(kind)
        if not b:
            continue
        if kind in ("control",):
            score = f"{b['ok']}/{b['n']} {b['ok'] / b['n']:.0%}"
        elif kind in JUDGEABLE:
            score = f"{b['ok']}/{b['n']} {b['ok'] / b['n']:.0%}"
        elif kind == "seek":
            score = f"{b['executed']}/{b['n']}"
        else:
            score = f"{b['answered']}+{b['quoted']}引/{b['n']}"
        print(f"{KIND_LABEL[kind]:<8} {b['n']:>4}  {score:>9}  {b['executed']:>5}  "
              f"{b['answered']:>5}  {b['miss'] + b['wrong']:>5}")

    judgeable = sum(b["n"] for k, b in stats.items() if k in JUDGEABLE)
    right = sum(b["ok"] for k, b in stats.items() if k in JUDGEABLE)
    lat = sorted(latencies)
    p50 = lat[len(lat) // 2]
    p95 = lat[min(len(lat) - 1, int(len(lat) * 0.95))]
    print(f"\n可判定项（control/search/highlight/touch）：{right}/{judgeable} "
          f"= {right / judgeable:.1%}" if judgeable else "")
    print(f"本地计算耗时 p50={p50:.2f}ms p95={p95:.2f}ms（不含 ASR/TTS/网络）")
    print(f"seek/qa 还没有 ground truth，只记执行与答出，不计入正确率")

    print("\n按书看（可判定项 / 找画面执行 / 问答答出）：")
    for bid in sorted(by_book):
        b = by_book[bid]
        j = f"{b['ok']}/{b['judgeable']}" if b["judgeable"] else "-"
        s = f"{b['seek_ok']}/{b['seek']}" if b["seek"] else "-"
        q = f"{b['qa_ok']}/{b['qa']}" if b["qa"] else "-"
        print(f"  {bid:<8} {j:>8}   {s:>7}   {q:>7}")

    if fails:
        print(f"\n未命中最多的前 12 条：")
        for f in fails[:12]:
            print(f"  [{f[0]}] {f[2]:<9} {f[1]!r} → {f[3]} {f[4]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

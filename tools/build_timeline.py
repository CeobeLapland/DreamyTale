#!/usr/bin/env python3
"""时间轴骨架：把每页转成一个占位 shot，让播放器和路由先跑起来。

这是 M1 的地基。真视频还没生成，但 shots.jsonl 的契约可以先满足——
等真视频进来，只替换 shot 的内容，上层一行不用改。

    python tasks.py timeline            # 所有书
    python tasks.py timeline zh01       # 一本

字幕来源：书页文本层。中文三本够用；英文三本的文字在插图里，
这里必然抽不到字幕——那不是 bug，是等 OCR/VLM 补的缺口，audit 会照实报出来。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "books"
SEC_PER_PAGE = 6.0


def read_jsonl(path: Path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def build(book: Path, sec_per_page: float) -> list:
    docs = read_jsonl(book / "docs.jsonl")
    facts = read_jsonl(book / "facts.jsonl")
    narrative = {r["page_no"]: r for r in read_jsonl(book / "narrative.jsonl")}

    by_page = {}
    for f in facts:
        by_page.setdefault(f.get("page_no"), []).append(f)

    shots = []
    for doc in docs:
        page = doc["page_no"]
        t0 = (page - 1) * sec_per_page
        t1 = page * sec_per_page

        # 教学辅助文字（note）对"找画面"是有用的——它本来就在描述画面；
        # 但对"问答"有害——它不是故事。所以这里保留，问答语料那边剔除。
        blocks = doc.get("text_blocks") or []
        script_line = " ".join(b["text"] for b in blocks).strip()
        # 视觉叙事层优先入镜头文本——英文三本没有文本层，全靠这一句
        narr = narrative.get(page)
        if narr:
            script_line = (narr["text"] + " " + script_line).strip()

        # 字幕：把这一页的文字按块顺序均摊到这一镜的时长里
        subtitles = []
        if blocks:
            step = (t1 - t0) / len(blocks)
            for i, blk in enumerate(blocks):
                subtitles.append({
                    "text": blk["text"],
                    "t_start": round(t0 + i * step, 2),
                    "t_end": round(t0 + (i + 1) * step, 2),
                    "lang": "zh" if any("\u4e00" <= ch <= "\u9fff" for ch in blk["text"]) else "en",
                })

        ents = {f["subject"] for f in by_page.get(page, [])}
        if narr:
            ents |= set(narr.get("entities") or [])
        entities = sorted(e for e in ents if e)

        shots.append({
            "shot_id": f"st_{book.name}_p{page:02d}",
            "book_id": book.name,
            "page_no": page,
            "t_start": round(t0, 2),
            "t_end": round(t1, 2),
            "script_line": script_line,
            "speaker": "旁白",
            "entities": entities,
            "objects": [],
            "subtitles": subtitles,
            "keyframe_path": doc.get("image_path"),
            "seed": 0,
        })
    return shots


def main(argv):
    sec = SEC_PER_PAGE
    args = [a for a in argv if not a.startswith("--")]
    for a in argv:
        if a.startswith("--sec="):
            sec = float(a.split("=", 1)[1])

    if not DATA.is_dir():
        print("data/books 还不存在，先跑 ingest")
        return 1

    targets = ([DATA / a for a in args] if args
               else sorted(p for p in DATA.iterdir() if p.is_dir()))
    for book in targets:
        if not (book / "docs.jsonl").exists():
            print(f"跳过 {book.name}：没有 docs.jsonl")
            continue
        shots = build(book, sec)
        out = book / "shots.jsonl"
        with out.open("w", encoding="utf-8") as f:
            for s in shots:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        subs = sum(len(s["subtitles"]) for s in shots)
        dur = shots[-1]["t_end"] if shots else 0
        print(f"{book.name:<8} {len(shots):3d} 个片段 / {dur:6.1f}s / {subs} 条字幕")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

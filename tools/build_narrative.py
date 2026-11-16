#!/usr/bin/env python3
"""视觉叙事层：用 VLM 把书页图读成文字。

    python tasks.py narrative zh01           # 一本书
    python tasks.py narrative --all          # 所有缺叙事的书
    python tasks.py narrative en01 --limit 3 # 先试三页

为什么需要它：
英文三本的文字全部栅格化在插图里，PDF 文本层一个字都抽不出来。
中文三本每本只有 950 字，光靠这 950 字也答不好问题。
**先有内容，再谈检索和生成**——这条顺序在 decisions/0005 里已经吃过亏。

产出格式见 docs/02 的 Narrative 一节：page_no / text / entities / source。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "books"

PROMPT = """你在为儿童绘本做导读标注。看这一页图，写一段描述，要求：

1. 只写画面上看得见的东西：谁、在做什么、表情、位置、数量、明显颜色。
2. 80~150 字，中文，客观陈述，不要抒情、不要评价、不要揣测心理。
3. 如果画面里有印刷文字，原样引用出来，用「」括住。
4. 不要编造画面里没有的角色或动作。

只输出描述本身，不要任何前缀。"""

ENTITIES_PROMPT = """看这页图，列出画面里出现的实体名称，用顿号分隔。
只要名词：角色名（如果图上写着名字就用名字，否则用"扎马尾的女孩"这种描述）、
物品、动物、场景。
只输出名称列表，不要解释，不要编号。"""


def read_jsonl(path: Path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def desc_for(page_path: Path) -> tuple:
    text = llm.vision(page_path, PROMPT, tag="narrative").strip()
    ent_raw = llm.vision(page_path, ENTITIES_PROMPT, max_tokens=200, tag="entities")
    ents = [e.strip(" 。.\n") for e in ent_raw.replace("，", "、").replace(",", "、").split("、")]
    ents = [e for e in ents if 1 < len(e) <= 20][:10]
    return text, ents


def build(book: Path, limit=None, force=False) -> int:
    docs = read_jsonl(book / "docs.jsonl")
    if not docs:
        print(f"  · {book.name}：没有 docs.jsonl")
        return 0

    out = book / "narrative.jsonl"
    existing = {r["page_no"]: r for r in read_jsonl(out)} if not force else {}
    todo = [d for d in docs if force or d["page_no"] not in existing]
    if limit:
        todo = todo[:limit]
    if not todo:
        print(f"  · {book.name}：叙事层已齐全（{len(existing)} 页）")
        return 0

    print(f"  {book.name}：要处理 {len(todo)} 页")
    added = 0
    for doc in todo:
        img = ROOT / doc["image_path"]
        if not img.exists():
            print(f"    跳过 p{doc['page_no']}：缺页图")
            continue
        try:
            text, ents = desc_for(img)
        except Exception as e:                              # noqa: BLE001
            print(f"    ✗ p{doc['page_no']}：{e}")
            continue
        if len(text) < 10:
            print(f"    ✗ p{doc['page_no']}：模型没给出可用描述")
            continue
        existing[doc["page_no"]] = {
            "page_no": doc["page_no"], "source": "vlm",
            "entities": ents, "text": text,
        }
        added += 1
        print(f"    ✓ p{doc['page_no']}  {len(text)} 字 / {len(ents)} 实体")

    rows = [existing[k] for k in sorted(existing)]
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  写入 {out.name}：{len(rows)} 页（本次新增 {added}）")
    return added


def main(argv):
    limit = None
    for a in argv:
        if a.startswith("--limit"):
            limit = int(a.split("=", 1)[1]) if "=" in a else 3
    force = "--force" in argv
    all_books = "--all" in argv
    names = [a for a in argv if not a.startswith("--")]

    if not llm.available("vision"):
        print("没有可用的视觉模型。设 LLM_VL_MODEL（或复用 LLM_MODEL），"
              "并确认模型支持图片输入。", file=sys.stderr)
        return 1

    targets = ([DATA / n for n in names] if names
               else sorted(p for p in DATA.iterdir() if p.is_dir()))
    total = 0
    for book in targets:
        if not all_books and not names and (book / "narrative.jsonl").exists():
            continue
        total += build(book, limit=limit, force=force)
    print(f"\n共新增 {total} 页叙事")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

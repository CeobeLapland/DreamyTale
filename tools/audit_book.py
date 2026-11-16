#!/usr/bin/env python3
"""能力盘点：给定一本书，说清它现在能支持哪些交互、缺什么。

存在的原因：
"通用性"很容易变成一句口号。真正的检验是——拿任何一本书进来，
系统能明确说出"这一页我认得、这句话我查得到、这个问题我答不了"，
而不是含糊地全部返回失败。

    python tasks.py audit              # 盘所有书
    python tasks.py audit zh01         # 盘一本

纯标准库。任何目录只要符合 docs/02 的落盘约定就能盘。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "books"

OK, PENDING, MISSING = "✓", "·", "✗"


def read_jsonl(path: Path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def audit(book: Path) -> dict:
    docs = read_jsonl(book / "docs.jsonl")
    facts = read_jsonl(book / "facts.jsonl")
    cards = read_jsonl(book / "cards.jsonl")
    shots = read_jsonl(book / "shots.jsonl")
    meta_path = book / "book.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    pages = len(docs)
    blocks = sum(len(d.get("text_blocks") or []) for d in docs)
    chars = sum(len(b.get("text", "")) for d in docs for b in (d.get("text_blocks") or []))
    pages_with_text = sum(1 for d in docs if d.get("text_blocks"))
    images = len(list((book / "pages").glob("*.png"))) if (book / "pages").is_dir() else 0

    has_text = blocks > 0
    has_images = images > 0
    has_shots = len(shots) > 0
    has_subtitles = any(s.get("subtitles") for s in shots)
    has_objects = any(s.get("objects") for s in shots)
    has_facts = len(facts) > 0
    has_cards = len(cards) > 0

    caps = []

    # 有页图不等于能识别。之前这里报 ✓ 是假的——代码里一行页识别都没有。
    caps.append(("页图 / 翻页跟随", OK if has_images else MISSING,
                 f"{images} 张页图" if has_images else "没有页图"))
    caps.append(("页识别（认出是哪本书第几页）", MISSING,
                 "未实现：需要页指纹 + 特征匹配"))

    if has_shots:
        ents = sum(len(s.get("entities") or []) for s in shots)
        caps.append(("找画面 seek", OK if ents else PENDING,
                     f"{len(shots)} 个片段 / {ents} 个实体标注" if ents
                     else f"{len(shots)} 个片段，但没标实体"))
    else:
        caps.append(("找画面 seek", PENDING, "还没有 shots.jsonl，等时间轴生成"))

    if has_subtitles:
        caps.append(("查文字 / 高亮 search", OK, "有字幕轨"))
    elif has_text:
        caps.append(("查文字 / 高亮 search", PENDING,
                     f"有文本层（{chars} 字），但还没转成字幕轨"))
    else:
        caps.append(("查文字 / 高亮 search", MISSING, "没有文本层，也没有字幕轨，需要 OCR"))

    caps.append(("点击物体 touch", OK if has_objects else PENDING,
                 "有物体框" if has_objects else "还没有物体框（等检测或标注）"))

    if has_cards:
        qa = [c for c in cards if c.get("kind") == "qa"]
        src = "人工精标" if any(c.get("source") == "human" for c in qa) else "自动生成"
        caps.append(("问答 qa", OK, f"{len(qa)} 张卡，{src}"))
    elif has_text or has_facts:
        caps.append(("问答 qa", PENDING, "有素材但没有卡，只能走通用路径，答案不可控"))
    else:
        caps.append(("问答 qa", MISSING, "既没文本也没卡，只能给引导档"))

    return {
        "book_id": book.name,
        "pages": pages,
        "images": images,
        "blocks": blocks,
        "chars": chars,
        "pages_with_text": pages_with_text,
        "text_layer": meta.get("text_layer", "?"),
        "content_type": meta.get("content_type", "narrative"),
        "cards": len(cards),
        "facts": len(facts),
        "shots": len(shots),
        "caps": caps,
    }


def main(argv):
    if not DATA.is_dir():
        print("data/books 还不存在")
        return 0
    targets = ([DATA / a for a in argv] if argv
               else sorted(p for p in DATA.iterdir() if p.is_dir()))
    if not targets:
        print("还没有书籍目录")
        return 0

    for book in targets:
        if not book.is_dir():
            print(f"跳过 {book}（不是目录）", file=sys.stderr)
            continue
        r = audit(book)
        if not r["pages"]:
            print(f"{r['book_id']}：没有 docs.jsonl，先跑 ingest")
            continue
        print(f"\n{r['book_id']}  {r['pages']} 页 / {r['images']} 图 / "
              f"{r['blocks']} 文本块 / {r['chars']} 字 / "
              f"文本层={r['text_layer']} / 类型={r['content_type']}")
        if r["pages_with_text"] < r["pages"]:
            print(f"  {r['pages'] - r['pages_with_text']} 页没有文字")
        for name, mark, note in r["caps"]:
            print(f"  {mark} {name:<18} {note}")

    print("\n✓ 可用   · 差数据   ✗ 差能力（需要补前置步骤）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

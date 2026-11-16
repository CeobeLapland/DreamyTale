#!/usr/bin/env python3
"""向量索引构建：把书的内容编码成向量，供语义检索用。

    python tasks.py index            # 所有书
    python tasks.py index zh01       # 一本
    python tasks.py index --force    # 语料变了但哈希没变时强制重建

为什么必须有它：
中文没有空格，"搭的是什么"和"搭城堡"字面上零重叠。纯字面检索在绘本上
试过三次全失败（decisions/0005）。语义检索是唯一解。

语料哈希是防呆的：语料改了但索引没重建，向量和文本就对不上，
检索会给出看起来合理其实错误的结果——这是最坏的一种错。
"""

import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "books"
BATCH = 16


def read_jsonl(path: Path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def collect(book: Path) -> list:
    """把一本书的语料拆成检索单元。

    两类来源：书页上的叙述文字（排除教学辅助 note），以及 VLM 生成的视觉叙事。
    标签短于 8 字的不收——那是图注，不是句子，检索到也没用。
    """
    chunks = []
    for doc in read_jsonl(book / "docs.jsonl"):
        page = doc["page_no"]
        for blk in doc.get("text_blocks") or []:
            if blk.get("type") == "note":
                continue
            text = (blk.get("text") or "").strip()
            if len(text) < 8:
                continue
            chunks.append({"source": "page_text", "page_no": page,
                           "bbox": blk.get("bbox"), "text": text})
    for item in read_jsonl(book / "narrative.jsonl"):
        text = (item.get("text") or "").strip()
        if len(text) < 8:
            continue
        chunks.append({"source": "narrative", "page_no": item["page_no"],
                       "bbox": None, "text": text})
    return chunks


def corpus_hash(chunks: list) -> str:
    blob = "\n".join(f"{c['source']}|{c['page_no']}|{c['text']}" for c in chunks)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def build(book: Path, force: bool) -> bool:
    index_dir = book / "index"
    meta_path = index_dir / "meta.json"
    chunks = collect(book)
    if not chunks:
        print(f"  · {book.name}：没有可用语料，跳过")
        return False

    h = corpus_hash(chunks)
    if meta_path.exists() and not force:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("corpus_hash") == h:
            print(f"  · {book.name}：语料未变，索引已是最新（{meta.get('count')} 条）")
            return False

    if not llm.available("embed"):
        print(f"  ✗ {book.name}：没有配置向量模型（LLM_EMBED_MODEL）", file=sys.stderr)
        return False

    t0 = time.perf_counter()
    vectors = []
    for i in range(0, len(chunks), BATCH):
        batch = chunks[i:i + BATCH]
        vectors.extend(llm.embed([c["text"] for c in batch], tag=f"index:{book.name}"))
        print(f"    {book.name} {min(i + BATCH, len(chunks))}/{len(chunks)}", end="\r")

    if len(vectors) != len(chunks):
        print(f"\n  ✗ {book.name}：向量数与语料数不符（{len(vectors)} vs {len(chunks)}）",
              file=sys.stderr)
        return False

    index_dir.mkdir(parents=True, exist_ok=True)
    with (index_dir / "vectors.jsonl").open("w", encoding="utf-8") as f:
        for c, v in zip(chunks, vectors):
            f.write(json.dumps({
                "page_no": c["page_no"], "source": c["source"],
                "bbox": c["bbox"], "text": c["text"], "vec": [round(x, 6) for x in v],
            }, ensure_ascii=False) + "\n")

    meta = {
        "book_id": book.name,
        "model": llm.config()["embed_model"],
        "dim": len(vectors[0]) if vectors else 0,
        "count": len(chunks),
        "corpus_hash": h,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "build_ms": int((time.perf_counter() - t0) * 1000),
        "chunking": "按书页文本块 + 视觉叙事，短于 8 字丢弃，排除 note",
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  ✓ {book.name}：{len(chunks)} 条 / {meta['dim']} 维 / "
          f"{meta['build_ms']}ms")
    return True


def main(argv):
    force = "--force" in argv
    names = [a for a in argv if not a.startswith("--")]
    targets = ([DATA / n for n in names] if names
               else sorted(p for p in DATA.iterdir() if p.is_dir()))
    done = 0
    for book in targets:
        if (book / "docs.jsonl").exists() and build(book, force):
            done += 1
    print(f"\n完成 {done} 本")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""书籍入库：任意 PDF -> 归一化页图 + PageDocument。

这是冷启动的入口，也是"通用性"的第一块试金石。
代码里没有任何书名、页数、角色名的假设——换一本新书，一行不改。

    python tasks.py ingest <a.pdf> --book-id mybook
    python tasks.py ingest --all          # 跑命题组那六本

产出：
    data/books/{book_id}/pages/pNN.png
    data/books/{book_id}/docs.jsonl       PageDocument（见 docs/02）
    data/books/{book_id}/book.json        书籍元信息，不在契约内，供内部使用

归一化：长边固定 1600px（契约规定），原点左上。

依赖只有一个：pypdfium2（4MB，无额外依赖）。
PNG 用标准库 zlib 手写，不装 Pillow——少一个依赖就少一个装不上的理由。
"""

import argparse
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "books"

# 命题组六本，只用于 --all。新增书籍不写在这里。
COMPETITION_BOOKS = {
    "中文绘本01": "zh01",
    "中文绘本02": "zh02",
    "中文绘本03": "zh03",
    "英文绘本01": "en01",
    "英文绘本02": "en02",
    "英文绘本03": "en03",
}
SRC = ROOT / "企业预选赛绘本素材" / "绘本素材"


def need_pdfium():
    try:
        import pypdfium2
        return pypdfium2
    except ImportError:
        print("需要 pypdfium2：python -m pip install pypdfium2", file=sys.stderr)
        raise SystemExit(1)


# ---------------------------------------------------------------- PNG

def write_png(path: Path, width: int, height: int, data: bytes,
              stride: int = None, channels: int = 3) -> None:
    """BGR/BGRA 原始像素 -> PNG。标准库实现，不依赖 Pillow。

    pdfium 默认给 BGR（3 通道）。有行填充时按行裁，没有的话整块切片换序，
    后者是 C 层操作，比逐像素快一个数量级。
    """

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    stride = stride or width * channels

    if channels == 3 and stride == width * 3:
        body = bytearray(data)
        body[0::3], body[2::3] = data[2::3], data[0::3]  # BGR -> RGB
    else:
        body = bytearray()
        for y in range(height):
            row = data[y * stride: y * stride + width * channels]
            if channels == 4:
                for x in range(width):
                    i = x * 4
                    body += bytes((row[i + 2], row[i + 1], row[i]))
            else:
                for x in range(width):
                    i = x * 3
                    body += bytes((row[i + 2], row[i + 1], row[i]))

    stride_out = width * 3
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0
        raw += body[y * stride_out:(y + 1) * stride_out]

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
                     + chunk(b"IEND", b""))


# ---------------------------------------------------------------- 文本层

def _median(nums):
    return sorted(nums)[len(nums) // 2] if nums else 0


def collect_blocks(page, scale, page_h):
    """把 PDF 文本层的字符框聚成行、再聚成块。

    pdfium 给的是逐字符矩形（原点左下），这里换成左上坐标系，
    按纵向重叠聚行、按行距聚块，最后用 get_text_bounded 取回带空格的文本。
    """
    tp = page.get_textpage()
    n = tp.count_rects()
    if n == 0:
        return [], []

    chars = []
    for i in range(n):
        l, b, r, t = tp.get_rect(i)
        chars.append({
            "x0": l, "x1": r,
            "y0": page_h - t, "y1": page_h - b,   # 换成左上原点
        })
    if not chars:
        return [], []

    # 聚行：按顶边排序，纵心落在当前行高度范围内就算同一行
    chars.sort(key=lambda c: (c["y0"], c["x0"]))
    lines = []
    for ch in chars:
        placed = False
        for line in lines[-4:]:
            h = line["y1"] - line["y0"]
            cy = (ch["y0"] + ch["y1"]) / 2
            lcy = (line["y0"] + line["y1"]) / 2
            if abs(cy - lcy) < max(h, 4) * 0.6:
                line["items"].append(ch)
                line["y0"] = min(line["y0"], ch["y0"])
                line["y1"] = max(line["y1"], ch["y1"])
                line["x0"] = min(line["x0"], ch["x0"])
                line["x1"] = max(line["x1"], ch["x1"])
                placed = True
                break
        if not placed:
            lines.append({"x0": ch["x0"], "x1": ch["x1"], "y0": ch["y0"],
                          "y1": ch["y1"], "items": [ch]})

    for line in lines:
        line["items"].sort(key=lambda c: c["x0"])
    lines.sort(key=lambda l: (l["y0"], l["x0"]))

    # 聚块：相邻行、行距小于行高、横向有重叠
    blocks = []
    for line in lines:
        h = line["y1"] - line["y0"]
        joined = False
        if blocks:
            prev = blocks[-1]
            gap = line["y0"] - prev["y1"]
            overlap = min(prev["x1"], line["x1"]) - max(prev["x0"], line["x0"])
            min_w = max(1, min(prev["x1"] - prev["x0"], line["x1"] - line["x0"]))
            if gap < h * 0.55 and overlap > min_w * 0.5 and len(prev["heights"]) < 6:
                prev["x0"] = min(prev["x0"], line["x0"])
                prev["x1"] = max(prev["x1"], line["x1"])
                prev["y1"] = max(prev["y1"], line["y1"])
                prev["heights"].append(h)
                joined = True
        if not joined:
            blocks.append({"x0": line["x0"], "x1": line["x1"], "y0": line["y0"],
                           "y1": line["y1"], "heights": [h]})

    out = []
    sizes = []
    for idx, blk in enumerate(blocks, 1):
        # get_text_bounded 用 PDF 坐标（原点左下）
        text = tp.get_text_bounded(left=blk["x0"], right=blk["x1"],
                                   bottom=page_h - blk["y1"],
                                   top=page_h - blk["y0"])
        text = " ".join(text.split())
        if not text:
            continue
        size = _median(blk["heights"])
        sizes.append(size)
        out.append({
            "block_id": f"b{idx:02d}",
            "bbox": [int(round(blk["x0"] * scale)), int(round(blk["y0"] * scale)),
                     int(round((blk["x1"] - blk["x0"]) * scale)),
                     int(round((blk["y1"] - blk["y0"]) * scale))],
            "text": text,
            "type": "body",
            "size": size,
        })

    # 明显大于全页中位字号的，判为标题
    med = _median(sizes)
    for blk in out:
        if med and blk["size"] > med * 1.35 and len(blk["text"]) <= 40:
            blk["type"] = "title"
        blk.pop("size")

    order = [b["block_id"] for b in
             sorted(out, key=lambda b: (round(b["bbox"][1] / 40), b["bbox"][0]))]
    return out, order


# ---------------------------------------------------------------- 主流程

def _rel(path: Path) -> str:
    """尽量给相对路径，给不了就用绝对路径。别为了好看而崩。"""
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except (ValueError, OSError):
        return path.as_posix()


def ingest_one(pdf_path, book_id, long_edge, out_root):
    pdfium = need_pdfium()
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        print(f"找不到文件：{pdf_path}", file=sys.stderr)
        return None

    out = out_root / book_id
    pages_dir = out / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    doc = pdfium.PdfDocument(str(pdf_path))
    records = []
    pages_no_text = 0
    pages_no_text_or_image = 0

    for i in range(len(doc)):
        page = doc[i]
        w_pt, h_pt = page.get_width(), page.get_height()
        scale = long_edge / max(w_pt, h_pt)

        bitmap = page.render(scale=scale)
        name = f"p{i + 1:02d}.png"
        png_path = pages_dir / name
        write_png(png_path, bitmap.width, bitmap.height, bytes(bitmap.buffer),
                  stride=bitmap.stride, channels=bitmap.n_channels)

        blocks, order = collect_blocks(page, scale, h_pt)
        if not blocks:
            pages_no_text += 1
            if not page.get_objects():
                pages_no_text_or_image += 1

        for blk in blocks:
            x, y, bw, bh = blk["bbox"]
            x = max(0, min(x, bitmap.width - 1))
            y = max(0, min(y, bitmap.height - 1))
            blk["bbox"] = [x, y, max(1, min(bw, bitmap.width - x)),
                           max(1, min(bh, bitmap.height - y))]

        records.append({
            "doc_id": f"pg_{book_id}_p{i + 1:02d}",
            "book_id": book_id,
            "page_no": i + 1,
            "image_path": f"data/books/{book_id}/pages/{name}",
            "width": bitmap.width,
            "height": bitmap.height,
            "source_type": "pdf",
            "text_blocks": blocks,
            "reading_order": order,
            "sha256": hashlib.sha256(png_path.read_bytes()).hexdigest(),
        })
        bitmap.close()

    with (out / "docs.jsonl").open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    meta = {
        "book_id": book_id,
        "source_pdf": _rel(pdf_path),
        "pages": len(records),
        "long_edge": long_edge,
        "page_sizes": sorted({f"{r['width']}x{r['height']}" for r in records}),
        "pages_without_text": pages_no_text,
        "pages_without_text_or_image": pages_no_text_or_image,
        "text_layer": "none" if pages_no_text == len(records) else
                      ("sparse" if pages_no_text > len(records) * 0.4 else "ok"),
    }
    (out / "book.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{book_id:<8} {len(records):3d} 页  文本层={meta['text_layer']:<6} "
          f"无文字页={pages_no_text}")
    if meta["text_layer"] != "ok":
        print(f"         → 建议补 OCR（{pages_no_text} 页没有文本层）", file=sys.stderr)
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser(description="任意 PDF 入库")
    ap.add_argument("pdf", nargs="?", help="PDF 路径")
    ap.add_argument("--book-id", help="书短名，小写字母开头；默认由文件名推导")
    ap.add_argument("--long-edge", type=int, default=1600, help="归一化长边，默认 1600")
    ap.add_argument("--all", action="store_true", help="跑命题组那六本")
    ap.add_argument("--out", default=str(DATA), help="输出根目录")
    args = ap.parse_args(argv)

    out_root = Path(args.out)

    if args.all:
        if not SRC.is_dir():
            print(f"找不到素材目录：{SRC}", file=sys.stderr)
            return 1
        ok = 0
        for name, book_id in COMPETITION_BOOKS.items():
            pdf = SRC / f"{name}.pdf"
            if not pdf.exists():
                print(f"  跳过，找不到 {pdf}", file=sys.stderr)
                continue
            if ingest_one(pdf, book_id, args.long_edge, out_root):
                ok += 1
        print(f"\n完成 {ok} 本，产物在 {out_root}")
        return 0 if ok else 1

    if not args.pdf:
        ap.print_help()
        return 2

    pdf = Path(args.pdf)
    book_id = args.book_id or pdf.stem.lower().replace(" ", "-")
    if not book_id.isascii() or not book_id[0].isalpha():
        print(f"book_id 必须小写字母开头、纯 ASCII，当前推导得到 {book_id!r}，"
              f"请用 --book-id 指定", file=sys.stderr)
        return 2
    ingest_one(pdf, book_id, args.long_edge, out_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

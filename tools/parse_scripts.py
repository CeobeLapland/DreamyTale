#!/usr/bin/env python3
"""把命题组 txt 脚本解析成 InteractionScript(jsonl)。

纯标准库，不依赖任何第三方包。跑法：make parse
输入：企业预选赛绘本素材/绘本素材/{书名}.txt
输出：data/queries/{book_id}.jsonl + data/queries/_summary.json
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "企业预选赛绘本素材" / "绘本素材"
OUT = ROOT / "data" / "queries"

BOOKS = {
    "中文绘本01": "zh01",
    "中文绘本02": "zh02",
    "中文绘本03": "zh03",
    "英文绘本01": "en01",
    "英文绘本02": "en02",
    "英文绘本03": "en03",
}

SEQ_RE = re.compile(r"^(\d+)\.\s*(.+)$")
CLICK_RE = re.compile(r"^\s*\[点击\]\s*(.+)$")
MARK = "（必选）"
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
QUOTE_RE = re.compile(r"[“”\"'「」『』]")
TRAIL_RE = re.compile(r"[“”\"'「」『』]|几个字$|这句话$")

CONTROL = {
    "播放": "play",
    "暂停": "pause",
    "继续": "resume",
    "结束播放": "stop",
    "play": "play",
    "pause": "pause",
    "continue": "resume",
    "resume": "resume",
    "stop": "stop",
}

KIND_LABEL = {
    "control": "控制",
    "seek": "找画面",
    "search": "查文字",
    "highlight": "高亮",
    "touch": "点击物体",
    "qa": "问答",
}


def clean(text: str) -> str:
    return text.replace(MARK, "").strip()


def strip_quotes(text: str) -> str:
    return TRAIL_RE.sub("", text).strip()


def classify(text: str) -> str:
    low = text.lower().strip()
    if low in CONTROL:
        return "control"
    if text.startswith("查找"):
        return "search"
    if text.startswith("高亮"):
        return "highlight"
    if low.startswith("find the ") or low.startswith("show me "):
        return "seek"
    if text.startswith("找到"):
        # 找到“还不倒” 是在找一句台词，不是找画面
        return "search" if QUOTE_RE.search(text) else "seek"
    if text.endswith("的画面") or "的画面，" in text:
        return "seek"
    return "qa"


def extract_text(text: str) -> str:
    for prefix in ("查找文字", "查找", "高亮文字", "高亮"):
        if text.startswith(prefix):
            return strip_quotes(text[len(prefix):].strip())
    return strip_quotes(text)


def detect_lang(text: str) -> str:
    return "zh" if CJK_RE.search(text) else "en"


def resolve_audio(book_dir: str, seq: int) -> str:
    """按编号找音频。素材里有 14(必选)wav.wav 这种错名，所以用前缀匹配兜住。"""
    folder = SRC / book_dir
    exact = sorted(folder.glob(f"{seq:02d}*.wav"))
    if not exact:
        return None
    return str(exact[0].relative_to(ROOT)).replace("\\", "/")


def parse_book(path: Path, book_id: str, book_dir: str) -> list:
    records = []
    pending = None  # 上一个编号动作，供 [点击] 挂靠
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue

        click = CLICK_RE.match(line)
        if click:
            if pending is None:
                print(f"  ! {book_id}: [点击] 前面没有编号动作，跳过", file=sys.stderr)
                continue
            body = clean(click.group(1))
            target, _, action = body.partition("|")
            target = target.strip()
            if target.startswith("点击"):
                target = target[2:].strip()
            records.append({
                "script_id": f"{book_id}-{pending:03d}t",
                "book_id": book_id,
                "seq": pending,
                "kind": "touch",
                "raw_text": body,
                "required": MARK in line,
                "lang": detect_lang(target),
                "audio_path": None,
                "click_target": target,
                "click_action": action.strip(),
                "card_id": None,
            })
            continue

        m = SEQ_RE.match(line.strip())
        if not m:
            print(f"  ! {book_id}: 无法解析 {line!r}", file=sys.stderr)
            continue

        seq = int(m.group(1))
        raw_text = m.group(2).strip()
        text = clean(raw_text)
        kind = classify(text)
        required = MARK in raw_text

        rec = {
            "script_id": f"{book_id}-{seq:03d}",
            "book_id": book_id,
            "seq": seq,
            "kind": kind,
            "raw_text": text,
            "required": required,
            "lang": detect_lang(text),
            "audio_path": resolve_audio(book_dir, seq),
            "click_target": None,
            "click_action": None,
            "card_id": None,
        }

        if kind == "control":
            rec["action"] = CONTROL[text.lower().strip()]
        elif kind == "seek":
            rec["seek_query"] = text
        elif kind in ("search", "highlight"):
            rec["needle"] = extract_text(text)

        records.append(rec)
        pending = seq

    return records


def main() -> int:
    if not SRC.is_dir():
        print(f"找不到素材目录：{SRC}", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    total = Counter()
    per_book = {}

    for book_dir, book_id in BOOKS.items():
        path = SRC / f"{book_dir}.txt"
        if not path.exists():
            print(f"  ! 缺少脚本：{path}", file=sys.stderr)
            continue
        records = parse_book(path, book_id, book_dir)
        out = OUT / f"{book_id}.jsonl"
        with out.open("w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        kinds = Counter(r["kind"] for r in records)
        total.update(kinds)
        per_book[book_id] = {
            "records": len(records),
            "required": sum(1 for r in records if r["required"]),
            "kinds": dict(kinds),
            "missing_audio": [
                r["audio_path"] for r in records
                if r["audio_path"] and not (ROOT / r["audio_path"]).exists()
            ],
        }
        print(f"{book_id}  {len(records):3d} 条  " + "  ".join(
            f"{KIND_LABEL[k]}={v}" for k, v in sorted(kinds.items())))

    summary = {
        "total_records": sum(total.values()),
        "by_kind": dict(total),
        "books": per_book,
    }
    (OUT / "_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n合计 " + "  ".join(
        f"{KIND_LABEL[k]}={v}" for k, v in sorted(total.items())))
    print(f"共 {sum(total.values())} 条，写入 {OUT}")

    missing = sum(len(v["missing_audio"]) for v in per_book.values())
    if missing:
        print(f"警告：{missing} 条记录找不到对应音频", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

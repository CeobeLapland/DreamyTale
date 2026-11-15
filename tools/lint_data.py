#!/usr/bin/env python3
"""数据校验器。把 docs/02-数据契约.md 变成可执行的检查。

纯标准库，git clone 就能跑，不需要装任何依赖。
跑法：make lint-data
退出码 0 = 干净，1 = 有错误。警告不拦提交，错误拦。
"""

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

BOOK_IDS = {"zh01", "zh02", "zh03", "en01", "en02", "en03"}
# 命题组这六本只是已知集，不是白名单。任何符合规范的新书都合法。
BOOK_ID_RE = re.compile(r"^[a-z][a-z0-9]{1,11}$")

KINDS = {"control", "seek", "search", "highlight", "touch", "qa"}
INTENTS = {
    "identify", "count", "locate", "attribute", "why", "plot",
    "predict", "feeling", "compare", "vocab", "common", "other",
}
ACTIONS = {"play", "pause", "resume", "stop"}
LANGS = {"zh", "en"}
SUBJECT_TYPES = {"character", "object", "scene", "action"}
SOURCES = {"human", "auto"}
TIERS = {"strong", "weak", "generic", "guide"}
VERDICTS = {"ok", "wrong", "miss", "stuck"}
BLOCK_TYPES = {"title", "body", "caption", "sfx"}
ATTR_KEYS = {"颜色", "数量", "动作", "表情", "位置", "穿着", "状态", "大小", "材质", "形状"}

STRONG_MAX = 30
WEAK_MAX = 90

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
ID_RE = re.compile(r"^(bk|pg|ft|cd|st|tr)_[a-z0-9]+(_p\d{2})?(_\d{3})?$")


class Report:
    def __init__(self):
        self.errors = []
        self.warns = []
        self.files = 0
        self.records = 0

    def err(self, where, msg):
        self.errors.append(f"{where}: {msg}")

    def warn(self, where, msg):
        self.warns.append(f"{where}: {msg}")

    def show(self):
        for w in self.warns:
            print(f"  warn  {w}")
        for e in self.errors:
            print(f"  ERROR {e}")
        print(f"\n检查 {self.files} 个文件 / {self.records} 条记录")
        print(f"错误 {len(self.errors)} · 警告 {len(self.warns)}")
        return 0 if not self.errors else 1


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def bbox_ok(v, width=None, height=None):
    if not isinstance(v, list) or len(v) != 4 or not all(is_int(x) for x in v):
        return "bbox 必须是 4 个整数 [x,y,w,h]"
    x, y, w, h = v
    if w <= 0 or h <= 0:
        return "bbox 的 w/h 必须为正"
    if x < 0 or y < 0:
        return "bbox 坐标不能为负"
    if width and height and (x + w > width or y + h > height):
        return f"bbox 越界（页图 {width}x{height}）"
    return None


def canon_hash(rec):
    body = {k: v for k, v in rec.items() if k != "hash"}
    blob = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def lint_queries(rep):
    """InteractionScript：从命题组 txt 解析出来的 300+ 条。"""
    qdir = DATA / "queries"
    if not qdir.is_dir():
        rep.warn("data/queries", "目录不存在，先跑 make parse")
        return

    for path in sorted(qdir.glob("*.jsonl")):
        rep.files += 1
        seqs = set()
        for i, rec in enumerate(read_jsonl(path), 1):
            rep.records += 1
            where = f"{path.name}:{i}"
            for key in ("script_id", "book_id", "seq", "kind", "raw_text", "required", "lang"):
                if key not in rec:
                    rep.err(where, f"缺少字段 {key}")
            if not BOOK_ID_RE.match(str(rec.get("book_id", ""))):
                rep.err(where, f"book_id 不符合规范（小写字母开头，2~12 位字母数字）："
                               f"{rec.get('book_id')!r}")
            if rec.get("kind") not in KINDS:
                rep.err(where, f"未知 kind {rec.get('kind')!r}")
            if rec.get("lang") not in LANGS:
                rep.err(where, f"lang 必须是 zh 或 en，实际 {rec.get('lang')!r}")
            if not is_int(rec.get("seq", None)):
                rep.err(where, "seq 必须是整数")
            elif rec.get("kind") != "touch":
                if rec["seq"] in seqs:
                    rep.err(where, f"seq {rec['seq']} 重复")
                seqs.add(rec["seq"])
            for key in ("click_target", "click_action"):
                if rec.get("kind") == "touch" and not rec.get(key):
                    rep.err(where, f"touch 类型缺少 {key}")
            audio = rec.get("audio_path")
            if audio and not (ROOT / audio).exists():
                rep.err(where, f"音频不存在 {audio}")
        if not seqs:
            rep.warn(path.name, "没有解析出任何编号动作")


def lint_books(rep):
    bdir = DATA / "books"
    if not bdir.is_dir():
        print("data/books 还没有内容（等 PDF 入库后再校验）")
        return

    for book in sorted(p for p in bdir.iterdir() if p.is_dir()):
        if not BOOK_ID_RE.match(book.name):
            rep.err(book.name, "book_id 不符合规范（小写字母开头，2~12 位字母数字）")
            continue
        if book.name not in BOOK_IDS:
            print(f"  · 新书 {book.name}（不在命题组六本里，走通用路径）")
        dims = load_page_dims(rep, book)
        facts = lint_facts(rep, book, dims)
        cards = lint_cards(rep, book, facts)
        lint_shots(rep, book)
        lint_docs(rep, book, dims)
        check_refs(rep, book, facts, cards)


def load_page_dims(rep, book):
    dims = {}
    path = book / "docs.jsonl"
    if not path.exists():
        return dims
    for rec in read_jsonl(path):
        if is_int(rec.get("page_no")):
            dims[rec["page_no"]] = (rec.get("width"), rec.get("height"))
    return dims


def lint_docs(rep, book, dims):
    path = book / "docs.jsonl"
    if not path.exists():
        return
    rep.files += 1
    seen = set()
    for i, rec in enumerate(read_jsonl(path), 1):
        rep.records += 1
        where = f"{book.name}/docs.jsonl:{i}"
        page = rec.get("page_no")
        if not is_int(page):
            rep.err(where, "page_no 必须是整数")
            continue
        if page in seen:
            rep.err(where, f"page_no {page} 重复")
        seen.add(page)
        for key in ("width", "height"):
            if not is_int(rec.get(key)) or rec[key] <= 0:
                rep.err(where, f"{key} 必须是正整数")
        if rec.get("source_type") not in {"pdf", "photo"}:
            rep.err(where, "source_type 必须是 pdf 或 photo")
        for j, blk in enumerate(rec.get("text_blocks") or [], 1):
            msg = bbox_ok(blk.get("bbox"), rec.get("width"), rec.get("height"))
            if msg:
                rep.err(f"{where} text_blocks[{j}]", msg)
            if blk.get("type") not in BLOCK_TYPES:
                rep.err(f"{where} text_blocks[{j}]", f"未知 type {blk.get('type')!r}")


def lint_facts(rep, book, dims):
    path = book / "facts.jsonl"
    facts = {}
    if not path.exists():
        return facts
    rep.files += 1
    for i, rec in enumerate(read_jsonl(path), 1):
        rep.records += 1
        where = f"{book.name}/facts.jsonl:{i}"
        fid = rec.get("fact_id")
        if not fid:
            rep.err(where, "缺少 fact_id")
            continue
        if not ID_RE.match(str(fid)):
            rep.err(where, f"fact_id 不符合命名规范：{fid}")
        if fid in facts:
            rep.err(where, f"fact_id 重复：{fid}")
        facts[fid] = rec

        for key in ("subject", "subject_type", "attributes", "bbox", "source", "version"):
            if key not in rec:
                rep.err(where, f"缺少字段 {key}")
        if rec.get("subject_type") not in SUBJECT_TYPES:
            rep.err(where, f"未知 subject_type {rec.get('subject_type')!r}")
        if rec.get("source") not in SOURCES:
            rep.err(where, f"source 必须是 human 或 auto，实际 {rec.get('source')!r}")
        if not is_num(rec.get("confidence", None)) or not 0 <= rec.get("confidence", -1) <= 1:
            rep.err(where, "confidence 必须在 0~1")
        if not is_int(rec.get("version")) or rec.get("version", 0) < 1:
            rep.err(where, "version 必须是 >=1 的整数")

        page = rec.get("page_no")
        width, height = dims.get(page, (None, None))
        msg = bbox_ok(rec.get("bbox"), width, height)
        if msg:
            rep.err(where, msg)

        attrs = rec.get("attributes") or {}
        if not isinstance(attrs, dict):
            rep.err(where, "attributes 必须是对象")
        else:
            for k in attrs:
                if k not in ATTR_KEYS:
                    rep.err(where, f"attributes 键不在受控词表：{k}（见 docs/02）")

        if rec.get("hash") and rec["hash"] != canon_hash(rec):
            rep.err(where, "hash 与内容不符，条目被改过但没重算 hash")

    detect_same_box(rep, book.name, facts)
    return facts


def detect_same_box(rep, book_name, facts):
    """同一页上两块 bbox 几乎重合但主体不同 —— 典型的重标错。"""
    by_page = {}
    for fid, rec in facts.items():
        if isinstance(rec.get("bbox"), list) and len(rec["bbox"]) == 4:
            by_page.setdefault(rec.get("page_no"), []).append((fid, rec))
    for page, items in by_page.items():
        for a in range(len(items)):
            for b in range(a + 1, len(items)):
                fa, ra = items[a]
                fb, rb = items[b]
                if ra.get("subject") == rb.get("subject"):
                    continue
                if iou(ra["bbox"], rb["bbox"]) > 0.85:
                    rep.warn(book_name, f"p{page} 上 {fa}({ra['subject']}) 与 "
                                        f"{fb}({rb['subject']}) 位置几乎重合，疑似重复标注")


def iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


def lint_cards(rep, book, facts):
    path = book / "cards.jsonl"
    cards = {}
    if not path.exists():
        return cards
    rep.files += 1
    for i, rec in enumerate(read_jsonl(path), 1):
        rep.records += 1
        where = f"{book.name}/cards.jsonl:{i}"
        cid = rec.get("card_id")
        if not cid:
            rep.err(where, "缺少 card_id")
            continue
        if not ID_RE.match(str(cid)):
            rep.err(where, f"card_id 不符合命名规范：{cid}")
        if cid in cards:
            rep.err(where, f"card_id 重复：{cid}")
        cards[cid] = rec

        kind = rec.get("kind")
        if kind not in KINDS:
            rep.err(where, f"未知 kind {kind!r}")
            continue
        if rec.get("source") != "human":
            rep.err(where, "预设卡 source 必须是 human")
        if rec.get("book_id") != book.name:
            rep.err(where, f"book_id 与目录不符：{rec.get('book_id')}")
        if rec.get("priority") not in (1, 2, 3):
            rep.err(where, "priority 必须是 1/2/3")
        langs = rec.get("langs")
        if not isinstance(langs, list) or not langs or not set(langs) <= LANGS:
            rep.err(where, "langs 必须是非空数组，元素取自 zh/en")
        variants = rec.get("variants")
        if not isinstance(variants, list) or len(variants) < 1:
            rep.err(where, "variants 必须是非空数组")

        need = {
            "control": ("action", lambda v: v in ACTIONS, "action 必须是 play/pause/resume/stop"),
            "seek": ("seek_query", lambda v: bool(v), "seek 类型必须有 seek_query"),
            "search": ("search_text", lambda v: bool(v), "search 类型必须有 search_text"),
            "highlight": ("highlight_text", lambda v: bool(v), "highlight 类型必须有 highlight_text"),
            "touch": ("touch_target", lambda v: bool(v), "touch 类型必须有 touch_target"),
        }
        if kind in need:
            key, check, msg = need[kind]
            if not check(rec.get(key)):
                rep.err(where, msg)

        if kind == "qa":
            lint_answers(rep, where, rec, langs or [])
            if rec.get("intent") not in INTENTS:
                rep.err(where, f"qa 的 intent 不在受控词表：{rec.get('intent')!r}")
            ev = rec.get("evidence")
            if not isinstance(ev, list) or not ev:
                rep.warn(where, "qa 卡没有 evidence，答辩时无法溯源")
            else:
                for j, e in enumerate(ev, 1):
                    if e.get("fact_id") and e["fact_id"] not in facts:
                        rep.err(f"{where} evidence[{j}]", f"引用的 fact 不存在：{e['fact_id']}")
                    if "page_no" in e:
                        msg = bbox_ok(e.get("bbox"))
                        if msg:
                            rep.err(f"{where} evidence[{j}]", msg)

        if rec.get("hash") and rec["hash"] != canon_hash(rec):
            rep.err(where, "hash 与内容不符")
    return cards


def lint_answers(rep, where, rec, langs):
    answers = rec.get("answers")
    if not isinstance(answers, dict) or not answers:
        rep.err(where, "qa 卡必须有 answers")
        return
    for lang in langs:
        if lang not in answers:
            rep.err(where, f"langs 声明了 {lang} 但 answers 里没有")
    for lang, body in answers.items():
        if lang not in LANGS:
            rep.err(where, f"answers 的键必须是 zh/en，实际 {lang!r}")
            continue
        if not isinstance(body, dict):
            rep.err(where, f"answers.{lang} 必须是对象")
            continue
        for tier in ("strong", "weak", "guide"):
            if not body.get(tier):
                rep.err(where, f"answers.{lang}.{tier} 不能为空")
        strong = body.get("strong") or ""
        weak = body.get("weak") or ""
        if len(strong) > STRONG_MAX:
            rep.err(where, f"answers.{lang}.strong 超过 {STRONG_MAX} 字（{len(strong)}）")
        if len(weak) > WEAK_MAX:
            rep.warn(where, f"answers.{lang}.weak 超过 {WEAK_MAX} 字（{len(weak)}）")


def lint_shots(rep, book):
    path = book / "shots.jsonl"
    if not path.exists():
        return
    rep.files += 1
    seen = set()
    for i, rec in enumerate(read_jsonl(path), 1):
        rep.records += 1
        where = f"{book.name}/shots.jsonl:{i}"
        sid = rec.get("shot_id")
        if not sid:
            rep.err(where, "缺少 shot_id")
            continue
        if sid in seen:
            rep.err(where, f"shot_id 重复：{sid}")
        seen.add(sid)
        t0, t1 = rec.get("t_start"), rec.get("t_end")
        if not is_num(t0) or not is_num(t1):
            rep.err(where, "t_start / t_end 必须是数字")
        elif t1 <= t0:
            rep.err(where, "t_end 必须大于 t_start")
        if not rec.get("entities"):
            rep.warn(where, "shot 没有 entities，seek 检索会漏")
        for j, sub in enumerate(rec.get("subtitles") or [], 1):
            if not sub.get("text"):
                rep.err(f"{where} subtitles[{j}]", "text 不能为空")
            if sub.get("lang") not in LANGS:
                rep.err(f"{where} subtitles[{j}]", "lang 必须是 zh 或 en")
        for j, obj in enumerate(rec.get("objects") or [], 1):
            msg = bbox_ok(obj.get("bbox"))
            if msg:
                rep.err(f"{where} objects[{j}]", msg)


def check_refs(rep, book, facts, cards):
    used = set()
    for rec in cards.values():
        for e in rec.get("evidence") or []:
            if e.get("fact_id"):
                used.add(e["fact_id"])
    orphan = set(facts) - used
    if orphan:
        rep.warn(book.name, f"{len(orphan)} 条 fact 没有被任何卡引用（正常，但别太多）")

    qpath = DATA / "queries" / f"{book.name}.jsonl"
    if not qpath.exists():
        return
    card_ids = set(cards)
    for i, rec in enumerate(read_jsonl(qpath), 1):
        cid = rec.get("card_id")
        if cid and cid not in card_ids:
            rep.err(f"{book.name}/queries:{i}", f"card_id 不存在：{cid}")


def read_jsonl(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"  ERROR {path.name}: JSON 解析失败 —— {exc}")


def main():
    rep = Report()
    lint_queries(rep)
    lint_books(rep)
    return rep.show()


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""执行器：把"一句话"变成"一个动作"。

这是 M1 的核心。输入是意图路由的结果，输出是播放器要执行的动作。
不生成任何内容，只做检索、定位、比对——那 211 条确定性交互靠的就是它。

会话状态是要紧的：脚本是线性有序的，"找到花花独处的画面"之后那句"她想念谁"
默认就在那个片段的语境里。状态错了，后面全错。
"""

import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

CLEAN_RE = re.compile(r"[^\w\u4e00-\u9fff]+")
STOP = ("找到", "的画面", "画面", "镜头", "片段", "那一段", "那段", "这一段",
        "带我看", "给我看", "跳到", "翻到", "回到", "的时候", "的地方", "从头")
GUIDE = "这个我还真不知道。我们一起翻回去看看，你觉得会是怎么回事？"


def norm(s: str) -> str:
    return CLEAN_RE.sub("", s or "").lower()


def bigrams(s: str) -> set:
    s = norm(s)
    if len(s) <= 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def read_jsonl(path: Path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


class Book:
    """一本书的全部可检索资产。没有的东西就是没有，不假装。"""

    def __init__(self, book_id: str, root: Path = None):
        base = (root or ROOT / "data" / "books") / book_id
        self.book_id = book_id
        self.shots = read_jsonl(base / "shots.jsonl")
        self.cards = read_jsonl(base / "cards.jsonl")
        self.facts = read_jsonl(base / "facts.jsonl")
        self.docs = read_jsonl(base / "docs.jsonl")
        self.passages = []
        self.notes = []
        for doc in self.docs:
            for blk in doc.get("text_blocks") or []:
                item = {"text": blk["text"], "page_no": doc["page_no"],
                        "bbox": blk.get("bbox")}
                if blk.get("type") == "note":
                    self.notes.append(item)      # 给"家长提示卡"用
                else:
                    self.passages.append(item)   # 故事内容，给问答用
        # 视觉叙事层：VLM 把图读成文字。绘本只有 950 字，没有这层检索必然答不动。
        self.narrative = []
        npath = base / "narrative.jsonl"
        if npath.exists():
            for line in npath.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.narrative.append(json.loads(line))
        for item in self.narrative:
            self.passages.append({"text": item["text"], "page_no": item["page_no"],
                                  "bbox": None, "kind": "narrative"})

        self.index = []
        idx = base / "index" / "vectors.jsonl"
        if idx.exists():
            for line in idx.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.index.append(json.loads(line))

        self.subtitles = []
        for shot in self.shots:
            for sub in shot.get("subtitles") or []:
                self.subtitles.append({**sub, "shot_id": shot["shot_id"],
                                       "page_no": shot.get("page_no")})

    @property
    def has_timeline(self) -> bool:
        return bool(self.shots)


class Session:
    """会话状态。跨多轮保持，翻页是最高优先级事件。"""

    def __init__(self, book: Book):
        self.book = book
        self.video_time = 0.0
        self.play_state = "paused"
        self.page = 1
        self.last_shot = None
        self.last_lang = "zh"

    def turn_page(self, page: int):
        self.page = page
        for shot in self.book.shots:
            if shot.get("page_no") == page:
                self.video_time = shot["t_start"]
                self.last_shot = shot["shot_id"]
                return

    def shot_by_id(self, shot_id):
        for shot in self.book.shots:
            if shot["shot_id"] == shot_id:
                return shot
        return None


def _card_match(book: Book, text: str):
    """交互卡优先。human 卡先，auto 卡后——通用性的实现就在这里。"""
    key = norm(text)
    best, best_score = None, 0.0
    for card in book.cards:
        cands = [card.get("question_canonical") or ""] + list(card.get("variants") or [])
        for cand in cands:
            ck = norm(cand)
            if not ck:
                continue
            if ck == key:
                score = 1.0
            elif ck in key or key in ck:
                score = 0.85
            else:
                q, c = bigrams(key), bigrams(ck)
                score = (len(q & c) / len(q | c)) if (q and c) else 0.0
            if card.get("source") == "human":
                score += 0.05
            if score > best_score:
                best, best_score = card, score
    return best, best_score


def do_control(route, sess: Session):
    act = route.get("action")
    if act in ("play", "resume"):
        sess.play_state = "playing"
    elif act == "pause":
        sess.play_state = "paused"
    elif act == "stop":
        sess.play_state = "stopped"
    return {"kind": "control", "action": act, "ok": act is not None}


def do_seek(route, sess: Session):
    if not sess.book.shots:
        return {"kind": "seek", "ok": False, "why": "没有时间轴"}
    q = route.get("seek") or ""
    for w in STOP:
        q = q.replace(w, "")
    qb = bigrams(q)
    if not qb:
        return {"kind": "seek", "ok": False, "why": "查询太短"}

    best, best_score = None, 0.0
    for shot in sess.book.shots:
        hay = bigrams(shot.get("script_line") or "")
        for ent in shot.get("entities") or []:
            hay |= bigrams(ent)
        if not hay:
            continue
        score = len(qb & hay) / len(qb)
        if score > best_score:
            best, best_score = shot, score

    if not best or best_score < 0.3:
        return {"kind": "seek", "ok": False, "why": "没找到对应片段"}
    sess.video_time = best["t_start"]
    sess.last_shot = best["shot_id"]
    sess.page = best.get("page_no", sess.page)
    return {"kind": "seek", "ok": True, "shot_id": best["shot_id"],
            "t": best["t_start"], "score": round(best_score, 3)}


def do_search(route, sess: Session, highlight=False):
    needle = norm(route.get("needle") or "")
    kind = "highlight" if highlight else "search"
    if not needle:
        return {"kind": kind, "ok": False, "why": "没提取到检索词"}
    for sub in sess.book.subtitles:
        if needle in norm(sub.get("text", "")):
            sess.video_time = sub["t_start"]
            sess.last_shot = sub["shot_id"]
            return {"kind": kind, "ok": True, "text": sub["text"],
                    "t": sub["t_start"], "shot_id": sub["shot_id"]}
    return {"kind": kind, "ok": False, "why": "字幕里没有这句", "needle": needle}


def do_touch(route, sess: Session):
    target = norm(route.get("target") or "")
    for shot in sess.book.shots:
        for obj in shot.get("objects") or []:
            if target and (target in norm(obj.get("entity", ""))
                           or norm(obj.get("entity", "")) in target):
                return {"kind": "touch", "ok": True, "entity": obj["entity"],
                        "bbox": obj.get("bbox"), "shot_id": shot["shot_id"]}
    # 退一步：用标注过的事实框当点击候选
    for fact in sess.book.facts:
        if target and (target in norm(fact.get("subject", ""))
                       or norm(fact.get("subject", "")) in target):
            return {"kind": "touch", "ok": True, "entity": fact["subject"],
                    "bbox": fact.get("bbox"), "page_no": fact.get("page_no"),
                    "source": "fact"}
    return {"kind": "touch", "ok": False, "why": "没有可点的物体框", "target": target}


def _cos(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


ANSWER_PROMPT = """你是绘本伴读，正在回答一个 3~8 岁孩子的问题。

规则：
- 只能根据下面给出的书页内容回答，不许编造。
- 如果这些内容不足以回答，就回"这个我还真不知道"，不要猜。
- 中文回答，不超过 25 个字，口语，用"你"不用"您"。
- 不要复述问题，不要说"根据书页内容"。

书页内容：
{context}

问题：{question}

只输出答案本身。"""


REFUSAL = ("不知道", "不知道", "无法回答", "答不上", "真知道", "不知道呀")


def _usable_answer(text) -> bool:
    """退化输出要拦住：空串、太短、明显是拒绝、或者只是在复述问题。

    小模型常见的失败形态不是"答错"，而是"答了个像答案的东西"——那种最难发现。
    """
    if not text:
        return False
    s = text.strip()
    if len(s) < 2:
        return False
    if any(w in s for w in REFUSAL):
        return False
    return True


REFUSAL = ("不知道", "不知道", "无法回答", "答不上", "真知道", "不知道呀")


def _usable_answer(text) -> bool:
    """退化输出要拦住：空串、太短、明显是拒绝、或者只是在复述问题。

    小模型常见的失败形态不是"答错"，而是"答了个像答案的东西"——那种最难发现。
    """
    if not text:
        return False
    s = text.strip()
    if len(s) < 2:
        return False
    if any(w in s for w in REFUSAL):
        return False
    return True


def _vector_qa(query_text: str, sess: Session, page=None):
    """语义检索 + 生成。这是知识层真正的通用路径：换任何一本书都能用。

    检索不到就返回 None，交给调用方降级，绝不硬答。
    """
    if not sess.book.index or not llm.available("embed"):
        return None
    try:
        qv = llm.embed(query_text, tag="qa")[0]
    except Exception:                                        # noqa: BLE001
        return None

    # 先只在当前页附近找。孩子翻到第 2 页问"小满在干什么"，
    # 答案必须来自第 2 页，而不是全书最像的那一段（那可能是最后几页）。
    pool_all = list(sess.book.index)
    pool_near = [i for i in pool_all if page and abs((i.get("page_no") or 0) - page) <= 2]
    pool = pool_near if len(pool_near) >= 3 else pool_all
    scope = "nearby" if pool is pool_near else "book"

    # 视觉叙事是完整句子，书页文本块常常是碎片（"三块、"这种）。
    # 同等相关度下优先给完整的那条，否则模型拿到半句话只能答"不知道"。
    def _rank(item):
        bonus = 0.04 if item.get("source") == "narrative" else 0.0
        return -(_cos(qv, item["vec"]) + bonus)

    scored = sorted(((_cos(qv, item["vec"]), item) for item in pool),
                    key=lambda x: -_rank(x[1]))[:5]
    if not scored or scored[0][0] < 0.34:
        return None

    # 字面闸门：向量分高不代表找对了。中文小向量模型会把"搭的是什么"和
    # "咬的是什么"判成 0.83——因为句式像。所以问题里的实词必须在片段里真的出现，
    # 否则不许拿来回答。低精度比低召回更糟：错答案比"不知道"伤得多。
    anchor = _anchor(query_text, sess.book)
    if anchor:
        gated = [(s, i) for s, i in scored if anchor in i["text"]]
        if not gated:
            # 向量 recall 不行时（中文小模型常见），就在全量里按实词捞，
            # 再用向量分排序。宁可窄召回，不要错召回。
            gated = sorted(((_cos(qv, i["vec"]), i) for i in pool
                            if anchor in i["text"]), key=lambda x: -x[0])[:3]
        if not gated:
            return None
        scored = gated

    ctx = "\n".join(f"[第 {item['page_no']} 页] {item['text']}"
                     for _, item in scored if item["text"])
    top = scored[0][1]

    answer = None
    if llm.available("chat"):
        try:
            answer = llm.chat([{"role": "user",
                                "content": ANSWER_PROMPT.format(context=ctx,
                                                                question=query_text)}],
                              # 推理型小模型会把预算先花在思考上，80 个字根本轮不到答案
                              max_tokens=400, temperature=0.2, tag="qa").strip()
        except Exception:                                    # noqa: BLE001
            answer = None
    if not _usable_answer(answer):
        return None

    return {"kind": "qa", "ok": True, "tier": "strong",
            "answer": answer,
            "evidence": [{"page_no": top["page_no"], "bbox": top.get("bbox")}],
            "score": round(scored[0][0], 3), "source": "vector+llm",
            "scope": scope}


def _lead_in(query_text: str) -> str:
    """按问法换个说法的开头。不生成内容，只是把检索到的原话递出去。"""
    if any(w in query_text for w in ("为什么", "为啥", "怎么", "why", "How")):
        return "书上是这么写的："
    if any(w in query_text for w in ("哪里", "哪儿", "在哪", "where", "Where")):
        return "书里提到："
    return "书里写的是："


def _idf(book):
    """bigram 的逆文档频率。功能词（是、的、什么）到处都是，权重自然低；
    实词（城堡、积木）只在少数段落出现，权重高。这样检索就不会被疑问词带走。"""
    if getattr(book, "_idf", None) is not None:
        return book._idf
    df = Counter()
    for psg in book.passages:
        for bg in bigrams(psg["text"]):
            df[bg] += 1
    n = max(1, len(book.passages))
    book._idf = ({bg: math.log((n + 1) / (c + 0.5)) for bg, c in df.items()}, df, n)
    return book._idf


# 疑问词与虚词。不剔掉的话，"是什么"会把任何一句带"什么"的话顶上来。
QW = ("为什么", "为啥", "什么", "怎么", "怎么样", "哪里", "哪儿", "哪些",
      "谁", "多少", "几个", "几只", "是不是", "是什么", "这句话", "什么意思")
FW = set("的了是在有和也都就这那他她它我你们个一不又还正很太更最")


def strip_question(text: str) -> str:
    t = text
    for w in QW:
        t = t.replace(w, "")
    return "".join(ch for ch in t if ch not in FW)


def _content_bigrams(query_text: str, book):
    """挑出这句话里真正有信息量的 bigram。功能词全部丢掉。"""
    _, df, n = _idf(book)
    core = strip_question(query_text)
    qb = bigrams(core)
    limit = n * 0.3
    return {bg for bg in qb if 1 <= df.get(bg, 0) <= limit}


def _anchor(query_text: str, book):
    """找出这句话里最该被匹配的那一个词。

    只认一个锚点，理由：绘本一页就一两句，多个候选必然打平，
    打平之后再怎么调权重都是拍脑袋。宁可认一个锚点、认准了再用。
    """
    core = strip_question(query_text)
    if not core:
        return None
    _, df, n = _idf(book)
    qb = [bg for bg in bigrams(core) if 1 <= df.get(bg, 0) <= n * 0.3]
    if qb:
        return max(qb, key=lambda bg: df and -df.get(bg, 0) or 0)  # 最罕见的那个
    return core if len(core) <= 3 else None


def _passage_lookup(query_text: str, sess: Session):
    """检索式引用：找到书里最相关的那句话，引用它。

    注意措辞——是"书上是这么写的"，不是"答案是"。绘本信息量太少，
    硬答必错。宁可给一句原文，让人自己判断。
    """
    if not sess.book.passages:
        return None
    anchor = _anchor(query_text, sess.book)
    if not anchor:
        return None

    best, best_hit = None, 0
    for psg in sess.book.passages:
        text = psg["text"]
        if len(text) < 8:
            continue
        hits = text.count(anchor)
        if hits > best_hit:
            best, best_hit = psg, hits

    if not best:
        return None
    text = best["text"]
    if len(text) > 80:
        text = text[:80] + "…"
    return {"kind": "qa", "ok": True, "tier": "quote",
            "answer": f"这个我不敢下结论，不过书上是这么写的：「{text}」",
            "evidence": [{"page_no": best["page_no"], "bbox": best["bbox"]}],
            "anchor": anchor, "source": "passage"}


def do_qa(query_text, sess: Session, page=None):
    card, score = _card_match(sess.book, query_text)
    if card and score >= 0.85:
        lang = "en" if route_lang(query_text) == "en" else "zh"
        ans = (card.get("answers") or {}).get(lang) or \
              next(iter((card.get("answers") or {}).values()), {})
        return {"kind": "qa", "ok": True, "tier": "strong" if score >= 0.95 else "weak",
                "answer": ans.get("strong"), "card_id": card["card_id"],
                "evidence": card.get("evidence")}
    if card and score >= 0.5:
        ans = next(iter((card.get("answers") or {}).values()), {})
        return {"kind": "qa", "ok": True, "tier": "weak", "answer": ans.get("weak"),
                "card_id": card["card_id"], "evidence": card.get("evidence")}

    # 语义检索 + 生成：有索引就能用，这是通用路径
    semantic = _vector_qa(query_text, sess, page=page or sess.page)
    if semantic:
        return semantic

    # 退而求其次：字面引用原句（不需要任何模型，但只能给原文）
    grounded = _passage_lookup(query_text, sess)
    if grounded:
        return grounded
    return {"kind": "qa", "ok": False, "tier": "guide", "answer": GUIDE}


def route_lang(text: str) -> str:
    return "zh" if any("\u4e00" <= ch <= "\u9fff" for ch in text) else "en"


def execute(route, query_text, sess: Session, page=None):
    kind = route.get("kind")
    if kind == "control":
        return do_control(route, sess)
    if kind == "seek":
        return do_seek(route, sess)
    if kind == "search":
        return do_search(route, sess)
    if kind == "highlight":
        return do_search(route, sess, highlight=True)
    if kind == "touch":
        return do_touch(route, sess)
    if kind == "qa":
        return do_qa(query_text, sess, page=page)
    return {"kind": "other", "ok": False, "tier": "guide", "answer": GUIDE}

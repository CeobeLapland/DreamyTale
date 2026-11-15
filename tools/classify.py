#!/usr/bin/env python3
"""意图路由：一句话 -> 六类交互之一（或 other）。

这是能力层的第一块。设计上只描述"用户想干什么"，不匹配任何一本书的原文，
所以对 328 条脚本之外的说法同样有效。

    python tools/classify.py "帮我看看搭积木那段"
    python tools/classify.py --bench        # 跑两套基准

设计要点：
1. **先判"是不是控制指令"，再判别的。** 控制指令一定是短祈使句，用长度和问号挡掉
   "他继续往前走会怎样"这类其实是提问的句子。
2. **"找到X"和"找到'X'"要分开。** 前者是找画面，后者是找台词。
3. **宁可选 other，不要瞎猜。** other 会走通用对话通道，猜错会执行错动作。
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
QUOTE_RE = re.compile(r"[“”\"'「」『』]")
PUNCT_RE = re.compile(r"[，。、！？；：,.!?;:~～\s]+")

# 控制类：只认短祈使句。顺序即优先级，stop 必须最先。
CONTROL = [
    ("stop", ["结束播放", "停止播放", "结束", "停止", "停掉", "关掉", "退出", "不看了", "不听了"],
     ["stop", "quit", "end", "turn off", "shut"]),
    ("pause", ["暂停", "停一下", "等一下", "先停", "别放", "暂停一下", "停"],
     ["pause", "hold on", "wait"]),
    ("resume", ["继续播放", "继续", "接着放", "接着", "往下放", "继续看"],
     ["continue", "resume", "go on", "keep going"]),
    ("play", ["开始播放", "播放", "开始", "放一下", "放吧", "放"],
     ["play", "start"]),
]

HIGHLIGHT_HINT = ["高亮", "标出", "标注", "标一下", "框出", "圈出", "强调", "highlight"]
SEARCH_HINT = ["查找", "查一下", "搜一下", "搜索", "找一下", "哪一句", "在哪句",
               "第几分钟", "第几秒"]
SEARCH_EN = ["find the word", "search for", "look for the word"]
TOUCH_HINT = ["点击", "点一下", "点点", "点这个", "点那", "戳", "按一下", "选中",
              "tap", "click", "touch"]
SEEK_HINT = ["画面", "镜头", "片段", "那一段", "那段", "这一段", "出现的时候",
             "什么时候出现", "跳到", "带我看", "给我看", "回到", "翻到", "从头",
             "的地方", "那会儿", "那里"]
SEEK_EN = ["show me", "the part where", "the scene", "jump to", "go back to", "find the"]
QA_HINT = ["为什么", "为啥", "怎么", "什么", "啥", "哪里", "哪儿", "谁", "多少",
           "几只", "几个", "是不是", "对不对", "吗", "呢", "什么意思", "干嘛", "干什么"]
QA_EN = ["why", "what", "who", "where", "when", "which", "how", "is ", "are ",
         "does", "do ", "did", "can ", "will ", "mean"]

ACTIONS = {"play", "pause", "resume", "stop"}


def normalize(text: str) -> str:
    t = text.strip()
    t = t.replace("（", "(").replace("）", ")")
    t = PUNCT_RE.sub(" ", t)
    return t.strip()


def has_any(text: str, words) -> bool:
    return any(w in text for w in words)


def is_question(text: str, raw: str) -> bool:
    if "?" in raw or "？" in raw:
        return True
    low = text.lower()
    if has_any(low, QA_EN):
        return True
    return has_any(text, QA_HINT)


def extract_needle(text: str) -> str:
    """从「查找文字"X"」「把 X 标一下」里挖出 X。"""
    m = re.search(r"[“\"'「『](.+?)[”\"'」』]", text)
    if m:
        return strip_tail(m.group(1))
    m = re.search(r"把\s*(.+?)\s*(?:标一下|标出来|高亮出来|高亮|圈出来|框出来|找一下)", text)
    if m:
        return strip_tail(m.group(1))
    for verb in ("查找文字", "高亮文字", "查找", "高亮", "标出", "圈出", "帮我找一下", "找一下"):
        if text.startswith(verb):
            return strip_tail(text[len(verb):])
    return strip_tail(text)


def strip_tail(s: str) -> str:
    """去掉「这几个字」「这个词」这类尾巴，它们是量词不是内容。"""
    s = s.strip()
    s = re.sub(r"(这|那)?[几]?个字$|(这|那)?个词$|这几个字$", "", s)
    return s.strip()


def control_at_edge(text: str, low: str):
    """控制词必须出现在句首或句尾才算。

    这是挡「刚才那一段再放一次」的关键——它含「放」，但「放」在句子中间，
    用户想的是回到那段，不是按播放键。位置比关键词更能说明意图。
    """
    for action, zh, en in CONTROL:
        for w in zh:
            if text.startswith(w) or text.endswith(w):
                return action
        tail = low.rstrip(".。!")
        for w in en:
            if low.startswith(w) or tail.endswith(w):
                return action
    return None


def extract_target(text: str, low: str) -> str:
    """从「戳一下那个机器人」里挖出「机器人」。

    输出可能为空——「点这个」的目标要靠指尖坐标定，不靠文字。
    """
    t = text
    for verb in ("点击", "点一下", "点这个", "点点", "按一下", "选中", "戳", "点"):
        t = t.replace(verb, "")
    for w in ("tap", "click", "touch"):
        t = re.sub(w, "", t, flags=re.IGNORECASE)
    for noise in ("一下", "那个", "这个", "那边", "这边"):
        t = t.replace(noise, "")
    return t.strip(" 的")


def classify(raw: str) -> dict:
    """返回 {kind, action?, needle?, seek?, lang, note?}。"""
    text = normalize(raw)
    low = text.lower()
    lang = "zh" if CJK_RE.search(raw) else "en"
    question = is_question(text, raw)

    # 1. 控制类：短祈使句 + 控制词在句首或句尾
    if len(text) <= 16 and not question:
        action = control_at_edge(text, low)
        if action and "不停" not in text:
            return {"kind": "control", "action": action, "lang": lang}

    # 2. 高亮
    if has_any(text, HIGHLIGHT_HINT) or has_any(low, ["highlight"]):
        return {"kind": "highlight", "needle": extract_needle(text), "lang": lang}

    # 3. 查文字：动词命中，或「带引号的原文 + 定位词」
    quoted = QUOTE_RE.search(raw) is not None
    if has_any(text, SEARCH_HINT) or has_any(low, SEARCH_EN) \
            or (quoted and (text.startswith("找到") or has_any(
                text, ["有没有", "第几", "在哪", "哪句", "这句", "那句"]))):
        return {"kind": "search", "needle": extract_needle(text), "lang": lang}

    # 4. 点击物体
    if has_any(text, TOUCH_HINT) or has_any(low, ["tap", "click", "touch"]):
        return {"kind": "touch", "target": extract_target(text, low), "lang": lang}

    # 5. 找画面（必须在问答之前：Show me the part where... 是定位不是提问）
    if has_any(text, SEEK_HINT) or has_any(low, SEEK_EN) \
            or (text.startswith("找到") and not quoted):
        seek = text
        for verb in ("找到", "带我看", "给我看", "跳到"):
            seek = seek.replace(verb, "")
        return {"kind": "seek", "seek": seek.strip(), "lang": lang}

    # 6. 问答 / 其他
    if question:
        return {"kind": "qa", "lang": lang}
    return {"kind": "other", "lang": lang,
            "note": "没听出要干什么，走通用对话通道"}


# ---------------------------------------------------------------- 基准

def bench_scripts():
    """328 条脚本：路由结果应与脚本解析结果一致。这是最低标准，不是目标。"""
    import json
    qdir = ROOT / "data" / "queries"
    total = ok = 0
    fails = []
    for path in sorted(qdir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            got = classify(rec["raw_text"])["kind"]
            total += 1
            if got == rec["kind"]:
                ok += 1
            else:
                fails.append((rec["book_id"], rec["raw_text"], rec["kind"], got))
    return ok, total, fails


def bench_paraphrase():
    """手写的口语变体：这才是通用性的证据，因为它不在脚本里。"""
    import json
    path = ROOT / "data" / "eval" / "paraphrase.jsonl"
    if not path.exists():
        return None
    total = ok = 0
    fails = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        got = classify(rec["text"])["kind"]
        total += 1
        if got == rec["kind"]:
            ok += 1
        else:
            fails.append((rec["text"], rec["kind"], got))
    return ok, total, fails


def main(argv):
    if "--bench" in argv:
        ok, total, fails = bench_scripts()
        print(f"脚本基准（328 条，应接近 100%）：{ok}/{total} = {ok / total:.1%}")
        for f in fails[:12]:
            print(f"  ✗ {f[0]} {f[1]!r} 期望{f[2]} 得到{f[3]}")
        if len(fails) > 12:
            print(f"  ... 另外 {len(fails) - 12} 条")

        para = bench_paraphrase()
        if para:
            ok2, total2, fails2 = para
            print(f"\n口语基准（手写变体，不在脚本里）：{ok2}/{total2} = {ok2 / total2:.1%}")
            for f in fails2[:20]:
                print(f"  ✗ {f[0]!r} 期望{f[1]} 得到{f[2]}")
        else:
            print("\n口语基准：data/eval/paraphrase.jsonl 不存在")
        return 0

    text = " ".join(argv).strip()
    if not text:
        print("用法：python tools/classify.py \"一句话\"  或  --bench", file=sys.stderr)
        return 2
    result = classify(text)
    print(f"{result}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

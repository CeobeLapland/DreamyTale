"""Parse the organizer's script txt into a v2 QuerySet and normalize audio."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from contracts.models import (
    ControlAction,
    QueryAction,
    QueryItem,
    QueryKind,
    QueryLang,
    QuerySet,
    QuerySetSource,
)

from .config import DATA, BookSpec

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")
QUOTE_RE = re.compile(r"[“\"]([^”\"]+)[”\"]")
STEP_RE = re.compile(r"^(\d{2})[.、]\s*(.+)$")
CONTROL_MAP = {
    "播放": ControlAction.play,
    "play": ControlAction.play,
    "暂停": ControlAction.pause,
    "pause": ControlAction.pause,
    "继续": ControlAction.resume,
    "resume": ControlAction.resume,
    "结束播放": ControlAction.stop,
    "stop": ControlAction.stop,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _has_mandatory(text: str) -> bool:
    return "必选" in text


def _clean(text: str) -> str:
    text = re.sub(r"[（(]\s*必选\s*[）)]", "", text)
    text = text.replace("【必选】", "").replace("[必选]", "")
    return text.strip()


def _detect_lang(text: str) -> QueryLang:
    has_cjk = bool(CJK_RE.search(text))
    has_latin = bool(LATIN_RE.search(text))
    if has_cjk and has_latin:
        return QueryLang.mixed
    if has_cjk:
        return QueryLang.zh
    if has_latin:
        return QueryLang.en
    return QueryLang.mixed


def _extract_quote(text: str) -> str | None:
    match = QUOTE_RE.search(text)
    return match.group(1).strip() if match else None


def _strip_search_prefix(text: str) -> str:
    text = re.sub(r"^(查找|搜索|find(\s+the)?(\s+(text|words?))?)\s*", "", text, flags=re.I)
    text = text.replace("几个字", "").replace("文字", "").strip()
    return text.strip("“”\"' ")


def _split_click(raw: str) -> tuple[str, str]:
    body = raw.split("[点击]", 1)[1].strip() if "[点击]" in raw else raw.strip()
    if "|" in body:
        left, right = body.split("|", 1)
    else:
        left, right = body, ""
    target = _clean(left).removeprefix("点击").strip()
    action_text = _clean(right)
    return target, action_text


def _classify(instruction: str, last_search_text: str | None) -> tuple[QueryKind, dict]:
    low = instruction.strip().lower()
    control_match = re.fullmatch(r"(播放|暂停|继续|结束播放|play|pause|resume|stop)[。.]?", low)
    if control_match:
        return QueryKind.control, {"control_action": CONTROL_MAP[control_match.group(1)]}

    if instruction.startswith("高亮"):
        quote = _extract_quote(instruction)
        return QueryKind.highlight, {"highlight_text": quote or last_search_text or "这句话"}

    if instruction.startswith("查找"):
        quote = _extract_quote(instruction)
        return QueryKind.search, {"search_text": quote or _strip_search_prefix(instruction)}

    if instruction.startswith("找到") or low.startswith("find") or low.startswith("show me"):
        quote = _extract_quote(instruction)
        if quote and "画面" not in instruction:
            return QueryKind.search, {"search_text": quote}
        return QueryKind.seek, {"seek_query": instruction}

    return QueryKind.qa, {}


def _find_audio(audio_dir: Path, number: int) -> Path | None:
    if not audio_dir.is_dir():
        return None
    candidates = sorted(
        p for p in audio_dir.glob(f"{number:02d}*.wav") if p.is_file()
    )
    return candidates[0] if candidates else None


def parse_script(spec: BookSpec) -> QuerySet:
    script_path = spec.script_path
    if not script_path.exists():
        raise FileNotFoundError(script_path)

    lines = script_path.read_text(encoding="utf-8-sig").splitlines()
    steps: list[dict] = []
    current: dict | None = None
    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            continue
        step_match = STEP_RE.match(line.strip())
        if step_match:
            current = {
                "number": int(step_match.group(1)),
                "raw": step_match.group(2).strip(),
                "clicks": [],
            }
            steps.append(current)
        elif line.strip().startswith("[点击]") and current is not None:
            current["clicks"].append(line.strip())

    book_dir = DATA / spec.book_id
    audio_out = book_dir / "audio"
    audio_out.mkdir(parents=True, exist_ok=True)
    query_dir = book_dir / "query_sets"
    query_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / "derived").mkdir(parents=True, exist_ok=True)

    items: list[QueryItem] = []
    missing_audio: list[int] = []
    last_search_text: str | None = None

    for step in steps:
        number = step["number"]
        raw = step["raw"]
        instruction = _clean(raw)
        mandatory = _has_mandatory(raw) or any(_has_mandatory(c) for c in step["clicks"])
        kind, extra = _classify(instruction, last_search_text)

        actions: list[QueryAction] = []
        query_id = f"{spec.book_id}-q{number:03d}"
        actions.append(
            QueryAction(
                action_id=f"{query_id}-a01",
                kind=kind,
                text=instruction,
                mandatory=_has_mandatory(raw),
                **extra,
            )
        )
        if kind == QueryKind.search:
            last_search_text = extra.get("search_text")

        for pos, click_raw in enumerate(step["clicks"], start=2):
            target, action_text = _split_click(click_raw)
            actions.append(
                QueryAction(
                    action_id=f"{query_id}-a{pos:02d}",
                    kind=QueryKind.click,
                    text=action_text or target,
                    mandatory=_has_mandatory(click_raw),
                    target=target,
                )
            )

        audio_src = _find_audio(spec.audio_path, number)
        audio_rel: str | None = None
        if audio_src is not None:
            audio_dst = audio_out / f"{number:02d}.wav"
            if audio_src.resolve() != audio_dst.resolve():
                shutil.copy2(audio_src, audio_dst)
            audio_rel = f"audio/{number:02d}.wav"
        else:
            missing_audio.append(number)

        items.append(
            QueryItem(
                query_id=query_id,
                number=number,
                instruction=instruction,
                audio_path=audio_rel,
                mandatory=mandatory,
                lang=_detect_lang(instruction),
                actions=actions,
                expected=None,
            )
        )

    query_set = QuerySet(
        query_set_id=f"{spec.book_id}-script-v1",
        book_id=spec.book_id,
        name="命题组脚本",
        language=QueryLang.mixed,
        source=QuerySetSource.official_script,
        items=items,
    )

    out_path = query_dir / f"{query_set.query_set_id}.json"
    out_path.write_text(
        json.dumps(query_set.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    book_path = book_dir / "book.json"
    if book_path.exists():
        book = json.loads(book_path.read_text(encoding="utf-8"))
        ids = book.setdefault("query_set_ids", [])
        if query_set.query_set_id not in ids:
            ids.append(query_set.query_set_id)
        book["updated_at"] = _now().isoformat().replace("+00:00", "Z")
        book_path.write_text(json.dumps(book, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "book_id": spec.book_id,
        "query_set_id": query_set.query_set_id,
        "items": len(items),
        "actions": sum(len(item.actions) for item in items),
        "mandatory_items": sum(1 for item in items if item.mandatory),
        "missing_audio": missing_audio,
    }
    (book_dir / "derived" / "query_set_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return query_set


def parse_all(specs: list[BookSpec]) -> list[QuerySet]:
    query_sets: list[QuerySet] = []
    for spec in specs:
        print(f"parse scripts {spec.book_id} <- {spec.script_path.name}")
        query_set = parse_script(spec)
        print(
            f"  items={len(query_set.items)} "
            f"actions={sum(len(i.actions) for i in query_set.items)} "
            f"mandatory={sum(1 for i in query_set.items if i.mandatory)}"
        )
        query_sets.append(query_set)
    return query_sets

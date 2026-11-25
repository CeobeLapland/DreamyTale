"""Turn an evaluation run into something you can look at.

A correctness rate is a claim; a finished video with burned-in subtitles next
to the page image with the evidence box on it is proof. This writes one
self-contained HTML file per run with three layers:

1. the effect   - per book: the finished film, the page wall with the
                  clickable boxes drawn on it, the questions that can be
                  answered and what the answer is
2. your turn    - a live console that posts to the running service, so every
                  number in the report can be re-checked by hand
3. the details - the evaluation table (accuracy is one line in it, not the
                  headline)

The page references the local artifacts (page images, videos) by relative
path, so it must be opened from the repository.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .config import DATA

REPO_ROOT = DATA.parent.parent
RUNS_DIR = REPO_ROOT / "runs"

VERDICT_LABEL = {
    "ok": "正确",
    "wrong": "答错",
    "miss": "没答上",
    "fallback": "降级",
}

KIND_LABEL = {
    "control": "播放控制",
    "search": "查找文字",
    "highlight": "高亮文字",
    "seek": "定位片段",
    "click": "点击识别",
    "qa": "问答",
}

# 回答档位（契约 §9.2）。guide 是引导，不是答案。
TIER_LABEL = {
    "strong": "确切答案",
    "weak": "要点答案",
    "quote": "原文引用",
    "guide": "引导（未作答）",
}

KIND_ORDER = ("control", "search", "highlight", "seek", "click", "qa")

_STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin:0; font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif;
       background:#f5f3ee; color:#22201d; }
a { color:#8a5a20; }
header { padding:28px 32px 22px; background:#23211e; color:#f7f4ec; }
h1 { margin:0 0 6px; font-size:22px; font-weight:600; }
.sub { opacity:.75; font-size:13px; }
.tabs { display:flex; gap:6px; margin-top:16px; }
.tab { padding:7px 16px; border-radius:8px 8px 0 0; font-size:14px; cursor:pointer;
       background:rgba(255,255,255,.06); color:#cfc9bd; border:1px solid rgba(255,255,255,.12);
       border-bottom:none; }
.tab.on { background:#f5f3ee; color:#22201d; font-weight:600; }
.cards { display:flex; flex-wrap:wrap; gap:12px; margin-top:18px; }
.card { background:rgba(255,255,255,.08); border-radius:10px; padding:12px 16px; min-width:120px; }
.card b { display:block; font-size:24px; font-weight:600; }
.card span { font-size:12px; opacity:.75; }
.note { margin:18px 32px; padding:14px 18px; background:#fffdf7; border-left:4px solid #c98a3c;
        border-radius:0 8px 8px 0; font-size:13px; line-height:1.8; }
.note code { background:#efece4; padding:1px 5px; border-radius:4px; font-size:12px; }
.toolbar { display:flex; gap:10px; flex-wrap:wrap; padding:14px 32px; background:#eae6dd;
           position:sticky; top:0; z-index:5; }
.toolbar select, .toolbar button, .play select, .play input, .play button {
  font:inherit; padding:6px 10px; border:1px solid #c9c2b4; border-radius:6px;
  background:#fffdf7; cursor:pointer; }
.play button { background:#8a5a20; color:#fff; border-color:#8a5a20; font-weight:600; }
section.book { margin:22px 32px; background:#fffdf7; border-radius:12px; padding:18px 20px;
               box-shadow:0 1px 3px rgba(0,0,0,.08); }
section.book h2 { margin:0 0 4px; font-size:18px; }
.bookhead { display:flex; gap:20px; align-items:flex-start; flex-wrap:wrap; margin-bottom:14px; }
.bookhead video { width:420px; border-radius:8px; background:#000; }
.kinds { display:flex; gap:10px; flex-wrap:wrap; }
.kind { background:#efece4; border-radius:8px; padding:8px 12px; font-size:12px; min-width:110px; }
.kind b { font-size:17px; display:block; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th { text-align:left; font-weight:600; color:#6b6558; font-size:12px; padding:8px 6px;
     border-bottom:1px solid #ded8ca; }
td { padding:8px 6px; border-bottom:1px solid #f0ece2; vertical-align:top; }
.badge { display:inline-block; padding:2px 8px; border-radius:20px; font-size:12px; color:#fff; }
.badge.ok { background:#4f8a4f; } .badge.wrong { background:#b5453c; }
.badge.miss { background:#b08a3c; } .badge.fallback { background:#8a8a8a; }
.evidence { width:210px; }
.evidence .frame { position:relative; display:inline-block; border:1px solid #ddd6c8; border-radius:6px;
                  overflow:hidden; background:#fff; }
.evidence img { display:block; width:100%; }
.evidence .box { position:absolute; border:2px solid #d2452f; background:rgba(210,69,47,.15); }
.evidence .none { color:#a09884; font-size:12px; }
.answer { max-width:420px; }
.answer q { color:#33302a; }
.ms { color:#8b8474; font-size:12px; white-space:nowrap; }
.hide { display:none; }
h3.sec { margin:30px 32px 6px; font-size:16px; }
.wall { display:flex; gap:8px; overflow-x:auto; padding:6px 2px 12px; }
.wall .cell { flex:0 0 auto; width:132px; }
.wall .frame { position:relative; border:1px solid #ddd6c8; border-radius:6px; overflow:hidden;
               background:#fff; }
.wall img { display:block; width:100%; }
.wall .box { position:absolute; border:2px solid #2f7fd2; background:rgba(47,127,210,.14); }
.wall .cap { font-size:11px; color:#7d7669; margin-top:3px; line-height:1.4; height:3.2em;
             overflow:hidden; }
.qacard { border-left:3px solid #c98a3c; padding:6px 10px; margin:8px 0; background:#fbf8f0;
          border-radius:0 6px 6px 0; font-size:13px; }
.qacard .q { font-weight:600; }
.qacard .a { color:#4a453c; margin-top:3px; }
.play { margin:18px 32px; background:#fffdf7; border-radius:12px; padding:18px 20px;
        box-shadow:0 1px 3px rgba(0,0,0,.08); }
.play .row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
.play .out { margin-top:14px; border-top:1px dashed #ded8ca; padding-top:12px; }
.play pre { background:#f1eee6; border-radius:8px; padding:10px; font-size:12px; overflow:auto;
            max-height:280px; }
.stat { display:flex; flex-wrap:wrap; gap:10px; margin-bottom:10px; }
.stat div { background:#efece4; border-radius:8px; padding:7px 12px; font-size:12px; }
.stat b { font-size:16px; display:block; }
.stat span { color:#8b8474; }
.src { font-size:11px; color:#a09884; }
"""

_SCRIPT = """
function switchTab(id) {
  document.querySelectorAll('.tab').forEach(function (t) {
    t.classList.toggle('on', t.dataset.tab === id);
  });
  document.querySelectorAll('.pane').forEach(function (p) {
    p.classList.toggle('hide', p.id !== id);
  });
}
document.querySelectorAll('.tab').forEach(function (t) {
  t.addEventListener('click', function () { switchTab(t.dataset.tab); });
});

function filterRows() {
  var book = document.getElementById('book').value;
  var kind = document.getElementById('kind').value;
  var verdict = document.getElementById('verdict').value;
  document.querySelectorAll('tr[data-row]').forEach(function (row) {
    var show = (book === 'all' || row.dataset.book === book)
      && (kind === 'all' || row.dataset.kind === kind)
      && (verdict === 'all' || row.dataset.verdict === verdict);
    row.classList.toggle('hide', !show);
  });
  document.querySelectorAll('section.book[data-book]').forEach(function (section) {
    var any = section.querySelectorAll('tr[data-row]:not(.hide)').length > 0;
    section.classList.toggle('hide', !any);
  });
}
['book', 'kind', 'verdict'].forEach(function (id) {
  document.getElementById(id).addEventListener('change', filterRows);
});

function boxStyle(bbox, w, h) {
  if (!bbox || !w || !h) return '';
  var x1 = Math.max(0, Math.min(100, bbox[0] / w * 100));
  var y1 = Math.max(0, Math.min(100, bbox[1] / h * 100));
  var bw = Math.max(0.5, Math.min(100 - x1, (bbox[2] - bbox[0]) / w * 100));
  var bh = Math.max(0.5, Math.min(100 - y1, (bbox[3] - bbox[1]) / h * 100));
  return 'left:' + x1.toFixed(2) + '%;top:' + y1.toFixed(2) + '%;width:' + bw.toFixed(2)
    + '%;height:' + bh.toFixed(2) + '%';
}

function evidenceHtml(bookId, evidence) {
  if (!evidence || !evidence.length) return '<div class="none">无证据</div>';
  var first = evidence[0];
  var page = first.page_index || 0;
  var size = (DREAMYTALE.pages[bookId] || {})[page];
  var img = 'data/books/' + bookId + '/pages/' + String(page).padStart(3, '0') + '.png';
  var style = boxStyle(first.bbox_px, size && size[0], size && size[1]);
  if (!style) {
    return '<div class="frame"><img src="' + img + '" loading="lazy"></div>';
  }
  return '<div class="frame"><img src="' + img + '" loading="lazy">'
    + '<div class="box" style="' + style + '"></div></div>';
}

function fillExamples() {
  var book = document.getElementById('pbook').value;
  var kind = document.getElementById('pkind').value;
  var data = DREAMYTALE.books[book] || {};
  var examples = (data.examples || []).filter(function (e) { return e.kind === kind; });
  var select = document.getElementById('pexample');
  select.innerHTML = '';
  examples.forEach(function (e) {
    var option = new Option(e.text, e.text);
    select.appendChild(option);
  });
  var input = document.getElementById('ptext');
  input.value = examples.length ? examples[0].text : '';
  refreshClick();
}

function refreshClick() {
  var book = document.getElementById('pbook').value;
  var kind = document.getElementById('pkind').value;
  var row = document.getElementById('clickrow');
  row.classList.toggle('hide', kind !== 'click');
  if (kind !== 'click') return;
  var select = document.getElementById('pclick');
  select.innerHTML = '';
  var hotspots = (DREAMYTALE.books[book] || {}).hotspots || [];
  hotspots.forEach(function (h) {
    select.appendChild(new Option(h.label + '（第 ' + h.page_index + ' 页）', h.hotspot_id));
  });
}

async function ask() {
  var book = document.getElementById('pbook').value;
  var kind = document.getElementById('pkind').value;
  var text = document.getElementById('ptext').value;
  var out = document.getElementById('pout');
  var payload = {
    book_id: book,
    session_id: 'report-' + Date.now(),
    kind: kind,
    input: { text: text, language: (DREAMYTALE.books[book] || {}).language },
    context: {}
  };
  if (kind === 'click') {
    var hotspot = ((DREAMYTALE.books[book] || {}).hotspots || []).filter(function (h) {
      return h.hotspot_id === document.getElementById('pclick').value;
    })[0];
    if (!hotspot) { out.innerHTML = '<div class="none">这本书还没有热区，先跑 pipeline hotspots。</div>'; return; }
    payload.input.page_index = hotspot.page_index;
    payload.input.click = {
      x_px: Math.round((hotspot.bbox_px[0] + hotspot.bbox_px[2]) / 2),
      y_px: Math.round((hotspot.bbox_px[1] + hotspot.bbox_px[3]) / 2)
    };
    payload.input.text = hotspot.label;
  }
  out.innerHTML = '<div class="none">正在请求服务…</div>';
  var started = performance.now();
  try {
    var response = await fetch(DREAMYTALE.base_url + '/api/interact', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    var data = await response.json();
    var ms = Math.round(performance.now() - started);
    var answer = data.answer || {};
    var status = data.status || '?';
    var badge = status === 'ok' ? 'ok' : (status === 'fallback' ? 'fallback' : 'wrong');
    var evidence = answer.evidence || [];
    out.innerHTML =
      '<div class="stat"><div><b><span class="badge ' + badge + '">'
      + (status === 'ok' ? '正常' : (status === 'fallback' ? '降级' : '出错'))
      + '</span></b><span>返回状态</span></div>'
      + '<div><b>' + ms + ' ms</b><span>往返耗时</span></div>'
      + '<div><b>' + (answer.tier || '-') + '</b><span>回答档位</span></div>'
      + '<div><b>' + (evidence.length) + '</b><span>证据条数</span></div></div>'
      + '<p class="qacard"><span class="q">' + escapeHtml(text || '（点击热区）') + '</span>'
      + '<div class="a">' + escapeHtml(answer.text || (data.error && data.error.message) || '（无回答）')
      + '</div></p>'
      + '<div class="evidence">' + evidenceHtml(book, evidence) + '</div>'
      + '<pre>' + escapeHtml(JSON.stringify(data, null, 2)) + '</pre>';
  } catch (err) {
    out.innerHTML = '<div class="none">请求失败：' + escapeHtml(String(err))
      + '<br>确认服务在跑：' + DREAMYTALE.base_url + '</div>';
  }
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

document.getElementById('pbook').addEventListener('change', fillExamples);
document.getElementById('pkind').addEventListener('change', fillExamples);
document.getElementById('pclick').addEventListener('change', function () {
  var hotspot = ((DREAMYTALE.books[document.getElementById('pbook').value] || {}).hotspots || [])
    .filter(function (h) { return h.hotspot_id === document.getElementById('pclick').value; })[0];
  if (hotspot) document.getElementById('ptext').value = hotspot.label;
});
document.getElementById('pask').addEventListener('click', ask);
fillExamples();
"""


def _rel(path: str) -> str:
    return path.replace("\\", "/")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    items: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items


def _book_state(book_id: str) -> dict[str, Any]:
    """Everything the report shows about one book, read from the artifacts."""
    root = DATA / book_id
    book = _read_json(root / "book.json")
    pages = book.get("pages", [])
    timeline = _read_json(root / "derived" / "scene" / "timeline.json")
    scene_plan = _read_json(root / "derived" / "scene" / "scene_plan.json")
    story = _read_json(root / "derived" / "story" / "story_plan.json")
    cards = _read_jsonl(root / "derived" / "knowledge" / "cards.jsonl")
    narratives = _read_jsonl(root / "derived" / "understanding" / "narrative.jsonl")

    hotspots: list[dict[str, Any]] = []
    for page in pages:
        for hotspot in page.get("hotspots", []) or []:
            hotspots.append(hotspot)

    subtitles = sum(len(scene.get("subtitles", []) or []) for scene in scene_plan.get("scenes", []))
    pages_with_text = sum(1 for page in pages if str(page.get("text") or "").strip())
    page_sizes = {
        int(page["index"]): [int(page.get("width_px") or 0), int(page.get("height_px") or 0)]
        for page in pages
        if page.get("index") is not None
    }

    return {
        "book_id": book_id,
        "title": book.get("title") or book_id,
        "language": book.get("language") or "",
        "page_count": len(pages),
        "pages_with_text": pages_with_text,
        "scene_count": len(scene_plan.get("scenes", [])),
        "subtitle_count": subtitles,
        "duration_ms": int(timeline.get("total_ms") or 0),
        "card_count": len(cards),
        "hotspots": hotspots,
        "cards": cards,
        "narratives": narratives,
        "page_sizes": page_sizes,
        "pages": pages,
        "logline": story.get("logline") or "",
    }


def _examples_for(book_id: str) -> list[dict[str, Any]]:
    """A handful of real questions from the official script, per kind."""
    query_sets = sorted((DATA / book_id / "query_sets").glob("*.json"))
    if not query_sets:
        return []
    query_set = _read_json(query_sets[0])
    examples: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in query_set.get("items", []):
        for action in item.get("actions", []):
            kind = str(action.get("kind") or "")
            text = str(action.get("text") or item.get("instruction") or "").strip()
            if not kind or not text:
                continue
            key = (kind, text)
            if key in seen:
                continue
            seen.add(key)
            examples.append({"kind": kind, "text": text})
    return examples


def _video_for(book_id: str) -> str:
    root = DATA / book_id / "derived" / "video"
    for name in ("final.mp4", "book.mp4"):
        if (root / name).is_file():
            return f"../../data/books/{book_id}/derived/video/{name}"
    return ""


def _wall_html(book_id: str, state: dict[str, Any]) -> str:
    """The page wall: every page with its clickable boxes drawn on top."""
    cells: list[str] = []
    narratives = {int(item.get("page_index") or 0): str(item.get("text") or "")
                  for item in state["narratives"]}
    sizes = state["page_sizes"]
    for page in state["pages"]:
        index = int(page.get("index") or 0)
        image = f"../../data/books/{book_id}/pages/{index:03d}.png"
        width, height = sizes.get(index, (0, 0))
        boxes = []
        for hotspot in page.get("hotspots", []) or []:
            style = _box_style(hotspot.get("bbox_px"), width, height)
            if style:
                boxes.append(f"<div class='box' style='{style}' title='{html.escape(str(hotspot.get('label') or ''))}'></div>")
        caption = html.escape(narratives.get(index, "")[:70])
        cells.append(
            f"<div class='cell'><div class='frame'><img src='{image}' loading='lazy' alt='第{index}页'>"
            + "".join(boxes)
            + f"</div><div class='cap'>第 {index} 页 · {caption}</div></div>"
        )
    return f"<div class='wall'>{''.join(cells)}</div>"


def _box_style(bbox: Any, width: int, height: int) -> str:
    if not bbox or len(bbox) != 4 or not width or not height:
        return ""
    x1, y1, x2, y2 = (int(value) for value in bbox)
    left = max(0.0, min(100.0, x1 / width * 100))
    top = max(0.0, min(100.0, y1 / height * 100))
    box_w = max(0.5, min(100.0 - left, (x2 - x1) / width * 100))
    box_h = max(0.5, min(100.0 - top, (y2 - y1) / height * 100))
    return f"left:{left:.2f}%;top:{top:.2f}%;width:{box_w:.2f}%;height:{box_h:.2f}%"


def _cards_html(state: dict[str, Any]) -> str:
    cards = state["cards"][:6]
    if not cards:
        return "<div class='ms'>还没有问答卡。</div>"
    rows: list[str] = []
    for card in cards:
        answers = card.get("answers") or {}
        answer = {}
        for value in answers.values():
            if isinstance(value, dict):
                answer = value
                break
        question = str(card.get("question_canonical") or "")
        strong = str(answer.get("strong") or "")
        evidence = card.get("evidence") or []
        page = evidence[0].get("page_index") if evidence else "?"
        rows.append(
            f"<div class='qacard'><span class='q'>问：{html.escape(question)}</span>"
            f"<div class='a'>答：{html.escape(strong[:120])}</div>"
            f"<div class='src'>证据在第 {page} 页 · 共 {len(card.get('variants') or [])} 种问法</div></div>"
        )
    more = ""
    if len(state["cards"]) > len(cards):
        more = f"<div class='src'>还有 {len(state['cards']) - len(cards)} 张卡，在 derived/knowledge/cards.jsonl</div>"
    return "".join(rows) + more


def _evidence_html(book_id: str, evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return '<div class="none">无证据</div>'
    first = evidence[0]
    page_index = int(first.get("page_index") or 0)
    bbox = first.get("bbox_px")
    image = f"../../data/books/{book_id}/pages/{page_index:03d}.png"
    if not bbox or len(bbox) != 4:
        return (
            f'<div class="evidence"><div class="frame">'
            f'<img src="{image}" loading="lazy">'
            f"</div></div>"
        )
    page = DATA / book_id / "book.json"
    width = height = 0
    if page.is_file():
        data = json.loads(page.read_text(encoding="utf-8"))
        for item in data.get("pages", []):
            if int(item.get("index") or 0) == page_index:
                width = int(item.get("width_px") or 0)
                height = int(item.get("height_px") or 0)
    if not width or not height:
        return '<div class="none">页面尺寸未知</div>'
    x1, y1, x2, y2 = (int(value) for value in bbox)
    left = max(0.0, min(100.0, x1 / width * 100))
    top = max(0.0, min(100.0, y1 / height * 100))
    box_w = max(0.5, min(100.0 - left, (x2 - x1) / width * 100))
    box_h = max(0.5, min(100.0 - top, (y2 - y1) / height * 100))
    return (
        f'<div class="evidence"><div class="frame">'
        f'<img src="{image}" loading="lazy">'
        f'<div class="box" style="left:{left:.2f}%;top:{top:.2f}%;width:{box_w:.2f}%;height:{box_h:.2f}%"></div>'
        f"</div></div>"
    )


def _case_row(case: dict[str, Any], result: dict[str, Any]) -> str:
    verdict = str(result.get("verdict") or "")
    kind = str(result.get("kind") or "")
    answer = str(result.get("answer_text") or "")
    notes = str(result.get("notes") or "")
    latency = int(result.get("latency_ms") or 0)
    tier = str(result.get("tier") or "")
    evidence = result.get("evidence") or []
    tier_mark = (
        f"<br><span class='ms'>档位 {TIER_LABEL.get(tier, tier)}</span>" if tier else ""
    )
    return (
        f'<tr data-row data-book="{case["book_id"]}" data-kind="{kind}" data-verdict="{verdict}">'
        f"<td>{case['number']}<br><span class='ms'>{KIND_LABEL.get(kind, kind)}</span></td>"
        f"<td>{html.escape(str(case.get('query_text') or ''))}</td>"
        f'<td><span class="badge {verdict}">{VERDICT_LABEL.get(verdict, verdict)}</span>'
        + tier_mark
        + (f"<br><span class='ms'>{html.escape(notes)}</span>" if notes else "")
        + "</td>"
        f'<td class="answer"><q>{html.escape(answer[:160])}</q></td>'
        f"<td>{_evidence_html(case['book_id'], evidence)}</td>"
        f'<td class="ms">{latency} ms</td>'
        "</tr>"
    )


def _duration_text(milliseconds: int) -> str:
    if not milliseconds:
        return "—"
    seconds = milliseconds / 1000
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}分{rest:02d}秒" if minutes else f"{rest}秒"


def build_report(run_id: str) -> Path:
    """Write runs/<run_id>/report.html from a finished run."""
    run_root = RUNS_DIR / run_id
    run = _read_json(run_root / "run.json")
    results = [
        json.loads(line)
        for line in (run_root / "results.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    cases_path = run_root / "cases.jsonl"
    cases: dict[str, dict[str, Any]] = {}
    if cases_path.is_file():
        for line in cases_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            case = json.loads(line)
            cases[case["case_id"]] = case
    if not cases:
        # Rebuild the case list from the query sets when the file is missing.
        from .config import BOOKS
        from .eval import load_cases

        for case in load_cases(BOOKS):
            cases[case.case_id] = case.model_dump(mode="json")

    metrics = run.get("metrics", {})
    by_kind = metrics.get("by_kind", {})
    detail = metrics.get("by_kind_detail", {})

    book_ids = sorted({case["book_id"] for case in cases.values()})
    states = {book_id: _book_state(book_id) for book_id in book_ids}

    parts: list[str] = []
    parts.append("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>")
    parts.append("<title>DreamyTale 效果报告</title><style>")
    parts.append(_STYLE)
    parts.append("</style></head><body>")

    total_pages = sum(state["page_count"] for state in states.values())
    total_duration = sum(state["duration_ms"] for state in states.values())
    total_cards = sum(state["card_count"] for state in states.values())
    total_hotspots = sum(len(state["hotspots"]) for state in states.values())
    total_subtitles = sum(state["subtitle_count"] for state in states.values())

    parts.append("<header><h1>DreamyTale 效果报告</h1>")
    parts.append(
        f"<div class='sub'>run {html.escape(run.get('run_id', ''))} · "
        f"服务 {html.escape(str(metrics.get('service', '')))} · "
        f"{html.escape(str(run.get('started_at', ''))[:19])}</div>"
    )
    parts.append(
        "<div class='cards'>"
        f"<div class='card'><b>{len(states)}</b><span>绘本</span></div>"
        f"<div class='card'><b>{total_duration // 60000}分{total_duration % 60000 // 1000:02d}秒</b><span>成片总时长</span></div>"
        f"<div class='card'><b>{total_subtitles}</b><span>字幕条数</span></div>"
        f"<div class='card'><b>{total_cards}</b><span>可答问题</span></div>"
        f"<div class='card'><b>{total_hotspots}</b><span>可点热区</span></div>"
        f"<div class='card'><b>{total_pages}</b><span>画面页数</span></div>"
        f"<div class='card'><b>{html.escape(str(metrics.get('ok', 0)))}/{html.escape(str(metrics.get('total', 0)))}</b><span>评测正确（参考）</span></div>"
        f"<div class='card'><b>{html.escape(str(metrics.get('p95_ms', 0)))} ms</b><span>响应 p95</span></div>"
        "</div>"
    )
    parts.append(
        "<div class='tabs'>"
        "<div class='tab on' data-tab='effect'>① 效果</div>"
        "<div class='tab' data-tab='play'>② 自己动手试</div>"
        "<div class='tab' data-tab='detail'>③ 评测明细</div>"
        "</div>"
    )
    parts.append("</header>")

    parts.append(
        "<div class='note'>"
        "<b>先说清楚这页是什么：</b>正确率只是最后一行。第一层是<b>效果</b>——每本书的成片、"
        "逐页画面、点了会说话的框、能问的问题和答案。第二层是<b>你自己动手</b>——"
        "在页面上直接向正在跑的服务提问，返回的原文和证据框都会摊开给你看，"
        "不需要相信任何统计数字。<br>"
        "<b>怎么验证：</b>服务跑在 <code>" + html.escape(str(metrics.get("service", "http://127.0.0.1:8000")))
        + "</code>；整套东西重新跑一遍是 <code>python -m pipeline eval --all</code>，"
        "再 <code>python -m pipeline report</code> 生成本页。"
        "完整阅读器在 <code>http://127.0.0.1:8000/reader/</code>。"
        "</div>"
    )

    # ---------- pane 1: the effect ----------
    parts.append("<div class='pane' id='effect'>")
    for book_id in book_ids:
        state = states[book_id]
        parts.append(f"<section class='book' data-book='{book_id}'>")
        parts.append(
            f"<h2>{html.escape(str(state['title']))} <span class='ms'>{html.escape(book_id)}</span></h2>"
        )
        if state["logline"]:
            parts.append(f"<div class='ms' style='margin-bottom:10px'>{html.escape(str(state['logline'])[:160])}</div>")
        parts.append("<div class='bookhead'>")
        video = _video_for(book_id)
        if video:
            parts.append(f"<video controls preload='metadata' src='{video}'></video>")
        parts.append(
            "<div class='stat'>"
            f"<div><b>{_duration_text(state['duration_ms'])}</b><span>成片时长</span></div>"
            f"<div><b>{state['page_count']}</b><span>画面页数</span></div>"
            f"<div><b>{state['subtitle_count']}</b><span>字幕条数</span></div>"
            f"<div><b>{state['card_count']}</b><span>能答的问题</span></div>"
            f"<div><b>{len(state['hotspots'])}</b><span>能点的热区</span></div>"
            f"<div><b>{state['pages_with_text']}/{state['page_count']}</b><span>有文字层</span></div>"
            "</div>"
        )
        parts.append("</div>")
        parts.append(
            "<div class='src'>数据来源：derived/video/final.mp4（烧录字幕）、"
            "derived/scene/scene_plan.json（字幕）、derived/knowledge/cards.jsonl（问答卡）、"
            "book.json 的 page.hotspots（热区）</div>"
        )
        parts.append("<h3 class='sec' style='margin:16px 0 4px'>逐页画面（蓝框＝可点的热区）</h3>")
        parts.append(_wall_html(book_id, state))
        parts.append("<h3 class='sec' style='margin:16px 0 4px'>孩子会问的问题，答案长这样</h3>")
        parts.append(_cards_html(state))
        parts.append("</section>")
    parts.append("</div>")

    # ---------- pane 2: hands-on ----------
    parts.append("<div class='pane hide' id='play'>")
    parts.append(
        "<div class='play'><h3 style='margin:0 0 4px'>自己动手验一遍</h3>"
        "<div class='ms'>下面这个框直接打正在跑的服务（"
        + html.escape(str(metrics.get("service", "http://127.0.0.1:8000")))
        + "）。题目来自官方脚本的原句，回答、证据框、原始 JSON 都会摊开。"
        "换成你自己的问题也行。</div>"
        "<div class='row' style='margin-top:12px'>"
        "<select id='pbook'>"
        + "".join(
            f"<option value='{book_id}'>{html.escape(str(states[book_id]['title']))}</option>"
            for book_id in book_ids
        )
        + "</select>"
        "<select id='pkind'>"
        + "".join(
            f"<option value='{kind}'>{KIND_LABEL.get(kind, kind)}</option>"
            for kind in KIND_ORDER
            if kind in by_kind
        )
        + "</select>"
        "<select id='pexample'></select>"
        "<input id='ptext' style='min-width:280px' placeholder='输入问题或指令'>"
        "<button id='pask'>问一次</button>"
        "</div>"
        "<div class='row hide' id='clickrow' style='margin-top:8px'>"
        "<span class='ms'>点哪个热区：</span><select id='pclick'></select></div>"
        "<div class='out' id='pout'><div class='none'>点「问一次」，这里会显示服务返回的原文。</div></div>"
        "</div>"
    )
    parts.append("</div>")

    # ---------- pane 3: evaluation details ----------
    parts.append("<div class='pane hide' id='detail'>")
    parts.append(
        "<div class='note' style='margin-left:0;margin-right:0'>"
        "<b>这些数字的口径：</b>逐条回放官方脚本里的 "
        f"{html.escape(str(metrics.get('total', 0)))} 个动作，打真实服务，按 kind 判分："
        "control 看返回的动作类型，search/highlight 看证据里有没有目标词，"
        "seek 看返回的页是不是问题指向的那一页，click 看命中的热点名字，"
        "qa 只要答得出且有证据就算通过。<br>"
        "<b>要当心：</b>qa 的「通过」是「答得上且有证据」，语义对不对没有标准答案可自动判，"
        "必须人工抽检；seek 的判定用页正文当基准，措辞不同会低估。"
        "<b>正确率是参考，不是效果。</b>"
        "</div>"
    )
    parts.append(
        "<div class='toolbar' style='margin:0 0 14px'>"
        "<select id='book'><option value='all'>全部书</option>"
        + "".join(f"<option value='{book}'>{book}</option>" for book in book_ids)
        + "</select>"
        "<select id='kind'><option value='all'>全部类型</option>"
        + "".join(
            f"<option value='{k}'>{KIND_LABEL.get(k, k)}</option>"
            for k in KIND_ORDER
            if k in by_kind
        )
        + "</select>"
        "<select id='verdict'><option value='all'>全部判定</option>"
        + "".join(f"<option value='{v}'>{VERDICT_LABEL.get(v, v)}</option>" for v in VERDICT_LABEL)
        + "</select></div>"
    )

    by_book: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for result in results:
        case = cases.get(result.get("case_id", ""))
        if case is None:
            continue
        by_book.setdefault(case["book_id"], []).append((case, result))

    for book_id in sorted(by_book):
        rows = by_book[book_id]
        parts.append(f"<section class='book' data-book='{book_id}'>")
        parts.append(f"<h2>{html.escape(book_id)}</h2>")
        parts.append("<div class='bookhead'><div class='kinds'>")
        for kind in KIND_ORDER:
            bucket = detail.get(kind)
            if not bucket:
                continue
            parts.append(
                f"<div class='kind'><b>{int(bucket.get('ok', 0))}/{bucket.get('total', 0)}</b>"
                f"{html.escape(KIND_LABEL.get(kind, kind))}</div>"
            )
        parts.append("</div></div>")
        parts.append(
            "<table><thead><tr><th>#</th><th>题目</th><th>判定</th><th>回答</th>"
            "<th>证据（页图 + 框）</th><th>延迟</th></tr></thead><tbody>"
        )
        for case, result in rows:
            parts.append(_case_row(case, result))
        parts.append("</tbody></table></section>")
    parts.append("</div>")

    payload = {
        "base_url": str(metrics.get("service") or "http://127.0.0.1:8000"),
        "pages": {book_id: states[book_id]["page_sizes"] for book_id in book_ids},
        "books": {
            book_id: {
                "language": states[book_id]["language"],
                "hotspots": states[book_id]["hotspots"],
                "examples": _examples_for(book_id),
            }
            for book_id in book_ids
        },
    }
    parts.append(
        "<script>const DREAMYTALE = "
        + json.dumps(payload, ensure_ascii=False)
        + ";</script>"
    )
    parts.append(f"<script>{_SCRIPT}</script></body></html>")

    report_path = run_root / "report.html"
    report_path.write_text("".join(parts), encoding="utf-8")
    return report_path

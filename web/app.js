'use strict';

const KIND_LABEL = {
  control: '控制', seek: '找画面', search: '查文字',
  highlight: '高亮', touch: '点击', qa: '问答', other: '其他',
};

const $ = (id) => document.getElementById(id);
const stage = $('stage'), frame = $('frame'), subtitle = $('subtitle');
const badge = $('badge'), bbox = $('bbox'), answer = $('answer');
const qEl = $('q'), aEl = $('a'), listEl = $('list');
const clock = $('clock'), pageLabel = $('pagelabel'), truth = $('truth');

let shots = [], pages = {}, queries = [], bookId = null;

/* ---- 播放状态：时间只由本地推进，服务端不参与计时 ---- */
let time = 0, playing = false, lastTs = 0;
let shownShotId = null, shownSubText = null, shownPage = null;
let highlightUntil = 0, activeRow = null;

const fmt = (s) => {
  const m = Math.floor(s / 60), sec = Math.floor(s % 60);
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
};

function shotAt(t) {
  for (const s of shots) if (t >= s.t_start && t < s.t_end) return s;
  return shots[shots.length - 1] || null;
}

function pageOf(t) {
  const s = shotAt(t);
  return s ? s.page_no : 1;
}

function hideBbox() { bbox.style.display = 'none'; }

function showBbox(box, pageNo) {
  const p = pages[pageNo];
  if (!p || !box) return;
  const sx = frame.clientWidth / p.w, sy = frame.clientHeight / p.h;
  const [x, y, w, h] = box;
  Object.assign(bbox.style, {
    left: `${x * sx}px`, top: `${y * sy}px`,
    width: `${w * sx}px`, height: `${h * sy}px`, display: 'block',
  });
}

/* ---- 渲染：只在真正变化时才动 DOM，避免闪烁与"乱跳" ---- */
function render() {
  const shot = shotAt(time);
  if (!shot) return;

  if (shot.shot_id !== shownShotId) {
    shownShotId = shot.shot_id;
    if (shot.page_no !== shownPage) {
      shownPage = shot.page_no;
      const p = pages[shot.page_no];
      if (p) frame.src = '/' + p.src;
      badge.textContent = `p${shot.page_no}`;
      pageLabel.textContent = `第 ${shot.page_no} 页`;
      hideBbox();
    }
  }

  clock.textContent = fmt(time);

  const sub = (shot.subtitles || []).find((s) => time >= s.t_start && time < s.t_end);
  const text = sub ? sub.text : '';
  if (text !== shownSubText) {
    shownSubText = text;
    subtitle.textContent = text;
  }
  const needle = subtitle.dataset.needle;
  if (needle && highlightUntil > time && text.includes(needle)) {
    subtitle.innerHTML = text.replace(needle, `<mark>${needle}</mark>`);
  } else if (subtitle.innerHTML !== text && shownSubText === text) {
    subtitle.textContent = text;
  }
}

function tick(ts) {
  if (!lastTs) lastTs = ts;
  const dt = Math.min(0.25, (ts - lastTs) / 1000);   // 切后台回来不要暴冲
  lastTs = ts;
  if (playing) {
    time += dt;
    const end = shots.length ? shots[shots.length - 1].t_end : 0;
    if (time >= end) { time = end; playing = false; }
    render();
  }
  requestAnimationFrame(tick);
}

function showAnswer(q, text, tier, note) {
  qEl.textContent = q;
  aEl.textContent = text || '（没有内容）';
  truth.textContent = note || '';
  answer.classList.toggle('guide', tier === 'guide' || tier === 'quote');
  answer.classList.add('show');
  clearTimeout(showAnswer._t);
  showAnswer._t = setTimeout(() => answer.classList.remove('show'), 7000);
}

function jumpTo(t) {
  time = Math.max(0, Math.min(t, shots.length ? shots[shots.length - 1].t_end : 0));
  shownShotId = null;        // 强制重绘，但只有页面真的变了才换图
  render();
}

/* ---- 脚本列表 ---- */
function buildList() {
  listEl.innerHTML = '';
  queries.forEach((q) => {
    const row = document.createElement('div');
    row.className = 'row';
    row.dataset.seq = q.seq;
    row.innerHTML = `<div class="no">${q.seq}</div>
      <div class="txt">${q.raw_text}${q.required ? ' <span class="req">*</span>' : ''}</div>
      <div class="chip ${q.kind}">${KIND_LABEL[q.kind] || q.kind}</div>`;
    row.onclick = () => send(q.raw_text, row);
    listEl.appendChild(row);
  });
  $('count').textContent = `${queries.length} 条 · * 为必选`;
}

function markRow(row) {
  if (activeRow) activeRow.classList.remove('active');
  if (row) { row.classList.add('active'); activeRow = row; }
}

/* ---- 主流程 ---- */
async function send(text, row) {
  if (!bookId) return;
  markRow(row);

  let data;
  try {
    const res = await fetch('/api/act', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        book_id: bookId,
        text,
        client_time: Number(time.toFixed(2)),   // 告诉服务端"我现在在哪"
        page: pageOf(time),
      }),
    });
    data = await res.json();
  } catch (e) {
    showAnswer(text, '服务没响应：' + e.message, 'guide');
    return;
  }
  if (data.error) { showAnswer(text, data.error, 'guide'); return; }

  const { route, result } = data;

  switch (route.kind) {
    case 'control':
      if (route.action === 'play' || route.action === 'resume') playing = true;
      else playing = false;
      break;

    case 'seek':
      if (result.ok) {
        jumpTo(result.t);
        showAnswer(text, `跳到 ${fmt(result.t)} · 第 ${result.page ?? pageOf(result.t)} 页`,
                   'strong', `把握 ${Math.round((result.score || 0) * 100)}%`);
      } else {
        showAnswer(text, '我没找到那一段。换个说法，或者说"翻到第几页"？', 'guide');
      }
      break;

    case 'search':
    case 'highlight':
      if (result.ok) {
        jumpTo(result.t);
        subtitle.dataset.needle = route.needle || '';
        highlightUntil = result.t + 5;
        showAnswer(text, `找到了：${result.text}`, 'strong');
      } else {
        showAnswer(text, `这句书里没有：（${route.needle || '空'}）`, 'guide');
      }
      break;

    case 'touch':
      if (result.ok && result.bbox) {
        showBbox(result.bbox, result.page_no || pageOf(time));
        showAnswer(text, `这是「${result.entity}」`, 'strong');
      } else {
        showAnswer(text, '这里没有我能认出来的东西', 'guide');
      }
      break;

    case 'qa':
      if (result.evidence && result.evidence[0] && result.evidence[0].bbox) {
        showBbox(result.evidence[0].bbox, result.evidence[0].page_no);
      }
      showAnswer(text, result.answer, result.tier,
                 result.tier === 'quote' ? '只是引用原文，不是答案' : '');
      break;

    default:
      showAnswer(text, result.answer || '没听清，能再说一次吗？', 'guide');
  }
}

/* ---- 载入 ---- */
async function loadBook(id) {
  bookId = id;
  const data = await (await fetch(`/api/book/${id}`)).json();
  if (data.error) { alert(data.error); return; }
  shots = data.shots;
  pages = data.pages;
  queries = data.queries;
  time = shots.length ? shots[0].t_start : 0;
  playing = false;
  shownShotId = shownPage = shownSubText = null;
  activeRow = null;
  highlightUntil = 0;
  subtitle.dataset.needle = '';
  subtitle.textContent = '';
  answer.classList.remove('show');
  hideBbox();
  buildList();
  render();
}

async function boot() {
  const books = await (await fetch('/api/books')).json();
  const sel = $('book');
  sel.innerHTML = '';
  books.forEach((b) => {
    const o = document.createElement('option');
    o.value = b.book_id;
    o.textContent = `${b.book_id} · ${b.pages} 页${b.text_layer === 'none' ? '（无文字）' : ''}`;
    sel.appendChild(o);
  });
  sel.onchange = () => loadBook(sel.value);
  if (books.length) await loadBook(books[0].book_id);
  requestAnimationFrame(tick);
}

document.querySelectorAll('footer [data-act]').forEach((btn) => {
  btn.onclick = () => {
    const m = { play: '播放', pause: '暂停', resume: '继续', stop: '结束播放' };
    send(m[btn.dataset.act]);
  };
});

$('send').onclick = () => {
  const v = $('say').value.trim();
  if (v) { send(v); $('say').value = ''; }
};
$('say').onkeydown = (e) => { if (e.key === 'Enter') $('send').click(); };

$('reset').onclick = async () => {
  await fetch('/api/act', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ book_id: bookId, reset: true }),
  });
  await loadBook(bookId);
};

window.addEventListener('resize', hideBbox);

boot();

const $ = id => document.getElementById(id);
let book = null, result = null, canonicalResult = null, variants = [], activeVariant = 'canonical', plan = null, index = 0, busy = false, recorder = null, stream = null, wasPlaying = false, turns = [], session = crypto.randomUUID(), qaCards = [], editing = null, toolsLoaded = false, showVideoObjects = true;
const video = $('video'), reply = $('reply');
const TIER_LABEL = { strong: '卡片', weak: '模型作答', quote: '原文', guide: '引导' };
const notify = t => $('notice').textContent = t;
async function api(path, options = {}) {
  const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 120000); try { const r = await fetch(path, { ...options, signal: controller.signal }); const data = await r.json(); if (!r.ok) throw Error(data.error?.message || data.detail || `HTTP ${r.status}`); return data; } finally { clearTimeout(timer); }
}
const asset = path => `/api/books/${encodeURIComponent(book.book_id)}/assets/${path.split('/').map(encodeURIComponent).join('/')}`;
const audioUrls = [];
function audioMessage(file) {
  const bubble = document.createElement('div'); bubble.className = 'bubble user voiceBubble'; bubble.title = file.name;
  const player = document.createElement('audio'); player.preload = 'metadata'; player.hidden = true;
  const url = URL.createObjectURL(file); audioUrls.push(url); player.src = url;
  const play = document.createElement('button'); play.type = 'button'; play.className = 'voicePlay'; play.textContent = '▶ 语音消息'; play.setAttribute('aria-label', '播放语音消息');
  const time = document.createElement('span'); time.className = 'voiceTime'; time.textContent = '0:00';
  const volume = document.createElement('input'); volume.type = 'range'; volume.min = '0'; volume.max = '1'; volume.step = '0.05'; volume.value = '1'; volume.className = 'voiceVolume'; volume.setAttribute('aria-label', '语音音量'); volume.title = '调整音量'; volume.oninput = () => { player.volume = Number(volume.value); };
  const clock = value => {
    if (!Number.isFinite(value)) return '0:00'; return `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, '0')}`;
  };
  const update = () => {
    time.textContent = Number.isFinite(player.duration) ? `${clock(player.currentTime)} / ${clock(player.duration)}` : clock(player.currentTime);
  };
  play.onclick = async () => {
    if (player.paused) {
      try { await player.play(); } catch { notify('这段音频暂时无法播放，请检查文件格式。'); }
    } else player.pause();
  };
  player.onplay = () => {
    video.pause(); reply.pause(); speechSynthesis.cancel(); document.querySelectorAll('#messages audio').forEach(a => { if (a !== player) a.pause(); }); play.textContent = 'Ⅱ 语音消息'; play.setAttribute('aria-label', '暂停语音消息');
  };
  player.onpause = player.onended = () => {
    play.textContent = '▶ 语音消息'; play.setAttribute('aria-label', '播放语音消息'); update();
  };
  player.onloadedmetadata = player.ontimeupdate = update;
  player.onerror = () => {
    time.textContent = '无法播放'; notify('音频无法解码，请尝试 WAV 或 MP3 文件。');
  };
  bubble.append(play, time, volume, player); $('messages').append(bubble); bubble.scrollIntoView({ block: 'nearest' });
}
function clearAudio() {
  document.querySelectorAll('#messages audio').forEach(a => a.pause()); audioUrls.splice(0).forEach(URL.revokeObjectURL);
}
function message(text, user = false) {
  const el = document.createElement('div'); el.className = 'bubble' + (user ? ' user' : ''); el.textContent = text; $('messages').append(el); el.scrollIntoView({ block: 'nearest' });
}
function clearEvidence() { $('overlay').replaceChildren(); }
function evidenceBox(ev) {
  if (Array.isArray(ev.bbox_px)) return ev.bbox_px;
  const page = book?.pages?.find(p => p.index === ev.page_index);
  if (!page || !ev.quote) return null;
  const quote = String(ev.quote).replace(/\s/g, '').toLowerCase();
  const spans = (page.text_spans || []).filter(span => {
    const text = String(span.text || '').replace(/\s/g, '').toLowerCase();
    return text.length >= 2 && quote.includes(text);
  });
  if (!spans.length) return null;
  const boxes = spans.map(span => span.bbox_px);
  return [Math.min(...boxes.map(b => b[0])), Math.min(...boxes.map(b => b[1])), Math.max(...boxes.map(b => b[2])), Math.max(...boxes.map(b => b[3]))];
}
function highlightEvidence(evidence) {
  clearEvidence();
  if (!book || !evidence?.length) return;
  const page = book.pages[index];
  const list = evidence.map(ev => ({ ev, box: evidenceBox(ev) })).filter(item => item.ev.page_index === page?.index && item.box);
  if (!list.length) return;
  // Show the page image, not the letterboxed video, so the box lines up with
  // the printed page. "继续故事" switches back to the video.
  syncPageImage();
  video.pause(); video.hidden = true; $('page').hidden = false;
  updateVideoObjects();
  notify('已暂停视频并显示证据；点击“继续故事”回到视频。');
  const draw = () => {
    const stage = document.querySelector('.stage'), img = $('page');
    if (!img.naturalWidth) return;
    const s = stage.getBoundingClientRect(), r = img.getBoundingClientRect();
    const scale = Math.min(r.width / img.naturalWidth, r.height / img.naturalHeight);
    const w = img.naturalWidth * scale, h = img.naturalHeight * scale;
    const ox = r.left - s.left + (r.width - w) / 2, oy = r.top - s.top + (r.height - h) / 2;
    for (const item of list) {
      const [x1, y1, x2, y2] = item.box;
      const box = document.createElement('div'); box.className = 'evidenceBox';
      box.style.left = `${ox + (x1 / page.width_px) * w}px`;
      box.style.top = `${oy + (y1 / page.height_px) * h}px`;
      box.style.width = `${((x2 - x1) / page.width_px) * w}px`;
      box.style.height = `${((y2 - y1) / page.height_px) * h}px`;
      $('overlay').append(box);
    }
  };
  const img = $('page');
  if (img.complete && img.naturalWidth) requestAnimationFrame(draw);
  else img.addEventListener('load', draw, { once: true });
}
function answerBubble(response, text) {
  const bubble = document.createElement('div'); bubble.className = 'bubble';
  const body = document.createElement('div'); body.textContent = text; bubble.append(body);
  const meta = document.createElement('div'); meta.className = 'meta';
  const tier = response.answer?.tier;
  if (tier) {
    const badge = document.createElement('span'); badge.className = 'badge' + (tier === 'guide' ? ' warn' : ''); badge.textContent = TIER_LABEL[tier] || tier; meta.append(badge);
  }
  if (response.status && response.status !== 'ok') {
    const badge = document.createElement('span'); badge.className = 'badge warn'; badge.textContent = '能力受限'; meta.append(badge);
  }
  if (response.latency?.total != null) {
    const item = document.createElement('span'); item.textContent = `${Math.round(response.latency.total)} ms`; meta.append(item);
  }
  if (response.transcript) {
    const item = document.createElement('span'); item.textContent = `听到：${response.transcript}`; meta.append(item);
  }
  (response.answer?.evidence || []).forEach((ev, i) => {
    if (ev.bbox_px == null && !ev.quote) return;
    const chip = document.createElement('button'); chip.type = 'button'; chip.className = 'evidence';
    chip.textContent = `依据 ${i + 1} · 第 ${ev.page_index} 页`; chip.title = ev.quote || '点击定位';
    chip.onclick = () => jumpToEvidence(ev, response.action?.time_ms);
    meta.append(chip);
  });
  if (meta.childElementCount) bubble.append(meta);
  $('messages').append(bubble); bubble.scrollIntoView({ block: 'nearest' });
}
function jumpToEvidence(ev, timeMs) {
  if (!book) return;
  // Clicking a source is an explicit navigation: cancel the pending auto-resume
  // so the evidence box is not wiped by "continue the story".
  wasPlaying = false; speechSynthesis.cancel(); reply.pause();
  const target = book.pages.find(p => p.index === ev.page_index);
  if (!target) return;
  const position = book.pages.indexOf(target);
  if (position !== index) { index = position; showPage(); }
  if (result?.full_video_path) {
    const page = result.pages?.find(p => p.page_index === ev.page_index);
    const ms = timeMs != null ? timeMs : page?.start_ms;
    if (ms != null) video.currentTime = ms / 1000;
  }
  highlightEvidence([ev]);
  notify(`依据：第 ${ev.page_index} 页${ev.quote ? ` · ${ev.quote}` : ''}（点击“继续故事”回到视频）`);
}
function pause() {
  document.querySelectorAll('#messages audio').forEach(a => a.pause()); wasPlaying = !video.paused; video.pause(); reply.pause(); speechSynthesis.cancel();
}
async function resume() {
  document.querySelectorAll('#messages audio').forEach(a => a.pause()); reply.pause(); speechSynthesis.cancel();
  if (video.hasAttribute('src')) {
    if (book) {
      const page = book.pages[index];
      const pageInfo = result?.pages?.find(item => item.page_index === page?.index);
      const current = video.currentTime * 1000;
      if (video.ended || (pageInfo && (current < pageInfo.start_ms || current >= pageInfo.end_ms))) {
        video.currentTime = (pageInfo?.start_ms || 0) / 1000;
      }
    }
    video.hidden = false; $('page').hidden = true; $('empty').hidden = true; clearEvidence(); updateVideoObjects();
    try { await video.play(); notify('已回到视频。'); } catch { notify('请点击视频播放按钮继续。'); }
  } else if (book) {
    showPage();
  }
}
function currentMs() {
  return Math.round(video.currentTime * 1000) + (result?.full_video_path ? 0 : (result?.pages?.find(p => p.page_index === book?.pages[index]?.index)?.start_ms || 0));
}
function syncPageImage() {
  if (!book) return;
  const page = book.pages[index];
  if (!page) return;
  const src = asset(page.image_path);
  if ($('page').getAttribute('src') !== src) $('page').src = src;
}
function showPage() {
  const p = book.pages[index]; $('pageNumber').textContent = `第 ${index + 1} / ${book.pages.length} 页`; syncPageImage(); const path = result?.full_video_path || result?.pages?.find(x => x.page_index === p.index)?.video_path; video.hidden = !path; $('page').hidden = !!path; $('empty').hidden = true; if (path) {
    const url = asset(path);
    if (video.getAttribute('src') !== url) {
      video.src = url; video.load();
    }
  } else {
    video.removeAttribute('src'); video.load();
  } $('subtitle').textContent = ''; clearEvidence(); updateVideoObjects();
}
function sessionFor(bookId) {
  const key = `dreamytale.session.${bookId}`;
  let value = localStorage.getItem(key);
  if (!value) { value = crypto.randomUUID(); localStorage.setItem(key, value); }
  return value;
}
function applyVariant(id) {
  if (!book) return;
  pause();
  activeVariant = id;
  const variant = variants.find(item => item.id === id);
  result = variant
    ? { ...(canonicalResult || {}), full_video_path: variant.video_path, pages: variant.pages?.length ? variant.pages : (canonicalResult?.pages || []), variant: variant.id }
    : canonicalResult;
  showPage();
  const page = book.pages[index];
  const pageInfo = result?.pages?.find(item => item.page_index === page?.index);
  const target = pageInfo ? pageInfo.start_ms / 1000 : 0;
  const seek = () => { try { video.currentTime = target; } catch { /* metadata not ready */ } };
  if (video.readyState >= 1) seek();
  else video.addEventListener('loadedmetadata', seek, { once: true });
  $('subtitle').textContent = '';
  notify(variant ? `已切换到 ${variant.name}；该版本字幕由视频自带，物体框为按页近似位置。` : '已切回页动画版本。');
}
$('videoVariant').onchange = () => applyVariant($('videoVariant').value);

function videoFramePageRect() {
  const stage = document.querySelector('.stage');
  const page = book?.pages?.[index];
  if (!stage || !page || !video.videoWidth) return null;
  const s = stage.getBoundingClientRect(), r = video.getBoundingClientRect();
  const vw = video.videoWidth, vh = video.videoHeight;
  if (!vw || !vh) return null;
  const scale = Math.min(r.width / vw, r.height / vh);
  const frameWidth = vw * scale, frameHeight = vh * scale;
  const left = r.left - s.left + (r.width - frameWidth) / 2;
  const top = r.top - s.top + (r.height - frameHeight) / 2;
  // The renderer letterboxes the page inside the video frame.
  const pageAspect = page.width_px / page.height_px;
  const frameAspect = vw / vh;
  let pageWidth = frameWidth, pageHeight = frameHeight, ox = 0, oy = 0;
  if (pageAspect > frameAspect) {
    pageHeight = frameWidth / pageAspect;
    oy = (frameHeight - pageHeight) / 2;
  } else {
    pageWidth = frameHeight * pageAspect;
    ox = (frameWidth - pageWidth) / 2;
  }
  return { left, top, width: frameWidth, height: frameHeight, pageWidth, pageHeight, ox, oy };
}

function updateVideoObjects() {
  const layer = $('videoObjects');
  if (!book || !showVideoObjects || video.hidden || !video.getAttribute('src')) {
    layer.hidden = true; layer.replaceChildren(); layer.dataset.signature = ''; return;
  }
  const page = book.pages[index];
  const hotspots = page?.hotspots || [];
  const rect = videoFramePageRect();
  if (!hotspots.length || !rect) {
    layer.hidden = true; layer.replaceChildren(); layer.dataset.signature = ''; return;
  }
  layer.hidden = false;
  layer.style.left = `${rect.left}px`;
  layer.style.top = `${rect.top}px`;
  layer.style.width = `${rect.width}px`;
  layer.style.height = `${rect.height}px`;

  const pageInfo = result?.pages?.find(item => item.page_index === page.index);
  const progress = pageInfo && pageInfo.end_ms > pageInfo.start_ms
    ? Math.max(0, Math.min(1, (currentMs() - pageInfo.start_ms) / (pageInfo.end_ms - pageInfo.start_ms)))
    : 0;
  const camera = (plan?.scenes || []).filter(item => item.page_index === page.index)[0]?.camera || '';
  let scale = 1.02, tx = 0, ty = 0;
  if (/推|push/i.test(camera)) { scale = 1 + 0.08 * progress; ty = -0.04 * progress; }
  else if (/拉|pull/i.test(camera)) { scale = 1 + 0.08 * (1 - progress); ty = 0.04 * progress; }
  else if (/平移|pan/i.test(camera)) { scale = 1.05; tx = (progress - 0.5) * 0.1; }
  layer.style.transform = `translate(${tx * 100}%, ${ty * 100}%) scale(${scale})`;

  const signature = `${page.index}:${rect.pageWidth.toFixed(0)}x${rect.pageHeight.toFixed(0)}:${hotspots.map(item => item.hotspot_id).join(',')}`;
  if (layer.dataset.signature === signature) return;
  layer.replaceChildren(...hotspots.map(hotspot => {
    const [x1, y1, x2, y2] = hotspot.bbox_px;
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'videoObject'; button.dataset.label = hotspot.label;
    button.title = `点击：${hotspot.label}`;
    const boxWidth = Math.max(44, ((x2 - x1) / page.width_px) * rect.pageWidth);
    const boxHeight = Math.max(32, ((y2 - y1) / page.height_px) * rect.pageHeight);
    const centerX = rect.ox + (((x1 + x2) / 2) / page.width_px) * rect.pageWidth;
    const centerY = rect.oy + (((y1 + y2) / 2) / page.height_px) * rect.pageHeight;
    button.style.left = `${centerX - boxWidth / 2}px`;
    button.style.top = `${centerY - boxHeight / 2}px`;
    button.style.width = `${boxWidth}px`;
    button.style.height = `${boxHeight}px`;
    button.onclick = event => {
      event.stopPropagation();
      lock(async () => {
        pause();
        await answer(request('click', {
          text: '识别点击对象',
          click: {
            x_norm: ((x1 + x2) / 2) / page.width_px,
            y_norm: ((y1 + y2) / 2) / page.height_px,
          },
        }));
      });
    };
    return button;
  }));
  layer.dataset.signature = signature;
}
$('showVideoObjects').onchange = () => { showVideoObjects = $('showVideoObjects').checked; updateVideoObjects(); };
async function loadQaCards() {
  qaCards = [];
  if (!book) return;
  try {
    const text = await fetch(asset('derived/knowledge/cards.jsonl')).then(r => r.ok ? r.text() : '');
    qaCards = text.split(/\r?\n/).filter(line => line.trim()).map(line => JSON.parse(line)).filter(card => card.status === 'active');
  } catch { qaCards = []; }
}
async function loadTurns() {
  turns = [];
  if (!book) return;
  const list = await api(`/api/books/${encodeURIComponent(book.book_id)}/turns?session_id=${encodeURIComponent(session)}&limit=30`).catch(() => []);
  $('messages').replaceChildren();
  for (const turn of list) {
    if (turn.input_text) message((turn.input_audio ? '【语音】' : '') + turn.input_text, true);
    if (turn.reply_text) {
      answerBubble({
        answer: { text: turn.reply_text, tier: turn.tier, evidence: turn.evidence || [] },
        latency: turn.latency || {},
        status: 'ok',
        action: { time_ms: turn.video_time },
      }, turn.reply_text);
    }
    turns.push({ ...turn, request_id: turn.turn_id });
  }
}
async function selectBook(id) {
  if (recorder?.state === 'recording') return; pause(); book = await api(`/api/books/${encodeURIComponent(id)}`); index = 0; session = sessionFor(id); turns = []; qaCards = []; canonicalResult = null; variants = []; activeVariant = 'canonical'; $('variantRow').hidden = true; $('variantNote').textContent = ''; clearAudio(); $('messages').replaceChildren(); result = null; plan = null; const responses = await Promise.allSettled(['generation-result', 'scene-plan'].map(p => api(`/api/books/${encodeURIComponent(id)}/${p}`))); if (responses[0].status === 'fulfilled') result = responses[0].value; if (responses[1].status === 'fulfilled') plan = responses[1].value; canonicalResult = result; $('title').textContent = book.title; showPage(); notify(result ? '已载入生成产物；点击播放开始阅读。' : '绘本已载入，目前还没有可播放的生成视频。');
  const variantPayload = await api(`/api/books/${encodeURIComponent(id)}/video-variants`).catch(() => ({ variants: [] }));
  variants = variantPayload.variants || [];
  if (variants.length) {
    $('videoVariant').replaceChildren(new Option('页动画（可复现）', 'canonical'), ...variants.map(item => new Option(item.name, item.id)));
    $('videoVariant').value = 'canonical';
    $('variantNote').textContent = variants.map(item => item.note || '').filter(Boolean)[0] || '';
    $('variantRow').hidden = false;
  }
  await Promise.allSettled([loadQaCards(), loadTurns()]);
  renderReview();
  Promise.allSettled([loadAnnotations(), loadReviews()]);
  $('traceList').replaceChildren(); $('manifestList').replaceChildren(); $('criticList').replaceChildren(); $('capability').replaceChildren(); $('evalRun').replaceChildren();
  if (!$('tab-trace').hidden) loadTracePanel();
  if (!$('tab-eval').hidden) loadEvalPanel();
}
async function refresh() {
  const list = await api('/api/books'); $('books').replaceChildren(new Option('请选择绘本', ''), ...list.map(b => new Option(b.title, b.book_id))); if (book) $('books').value = book.book_id; notify(`已连接后端，书架共 ${list.length} 本绘本。`);
}
async function jobWait(job) {
  for (let n = 0; n < 900; n++) {
    $('job').textContent = `${job.stage} · ${job.status} · ${Math.round(job.progress * 100)}%`; if (['completed', 'degraded'].includes(job.status)) return job; if (['failed', 'cancelled'].includes(job.status)) throw Error(job.error || '任务未完成'); await new Promise(r => setTimeout(r, 2000)); job = await api(`/api/jobs/${encodeURIComponent(job.job_id)}`);
  } throw Error('等待超时，任务可能仍在后台运行。');
}
async function lock(fn) {
  if (busy) return; busy = true; document.querySelectorAll('button,select').forEach(x => x.disabled = true);
  try { await fn(); } catch (e) { notify(e.name === 'AbortError' ? '请求超时，请检查后台任务状态。' : e.message); } finally { busy = false; document.querySelectorAll('button,select').forEach(x => x.disabled = false); }
}
function request(kind, input) {
  return { book_id: book.book_id, session_id: session, kind, input: { page_index: book.pages[index].index, current_time_ms: currentMs(), language: book.language, ...input }, context: { last_page_index: book.pages[index].index, history_turn_ids: turns.map(t => t.request_id) } };
}
async function answer(payload, audioFile = null, alreadyPaused = false) {
  if (!book) throw Error('请先选择绘本');
  if (!alreadyPaused) pause(); let response; const started = performance.now(); if (audioFile) { const form = new FormData(); form.append('audio', audioFile, audioFile.name || 'recording.webm'); form.append('request', JSON.stringify(payload)); response = await api('/api/interact/audio', { method: 'POST', body: form }); } else response = await api('/api/interact', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  turns.push({ ...response, client_elapsed_ms: Math.round(performance.now() - started) }); const text = response.answer?.text || response.error?.message || '没有返回回答'; answerBubble(response, (response.status === 'ok' ? '' : '[能力受限] ') + text); loadTracePanel(); const a = response.action || {}; if (a.type === 'seek' && a.time_ms != null) { const page = result?.pages?.find(p => a.time_ms >= p.start_ms && a.time_ms < p.end_ms); if (page) { index = book.pages.findIndex(p => p.index === page.page_index); showPage(); video.currentTime = (a.time_ms - (result.full_video_path ? 0 : page.start_ms)) / 1000; } }
  if (['play', 'resume'].includes(a.type)) { await resume(); return; } if (['pause', 'stop'].includes(a.type)) { wasPlaying = false; return; } if (response.status !== 'ok') { notify(response.error?.message || '后端当前能力不足，故事保持暂停。'); return; } highlightEvidence(response.answer?.evidence || []);
  const finish = () => { if (wasPlaying) resume(); };
  if (response.answer?.audio_path) { reply.src = asset(response.answer.audio_path); reply.hidden = false; reply.onended = finish; try { await reply.play(); } catch { notify('点击回答音频播放，或点击继续故事。'); } } else if ($('speak').checked && text) { const speech = new SpeechSynthesisUtterance(text); speech.lang = book.language; speech.onend = finish; speech.onerror = () => notify('朗读不可用，可点击继续故事。'); speechSynthesis.speak(speech); } else finish();
}
$('refresh').onclick = () => lock(refresh); $('books').onchange = () => lock(async () => {
  const id = $('books').value; if (id) {
    busy = false; try {
      await selectBook(id);
    } finally { busy = true; }
  }
});
let preparedUpload = null;
async function importSelected(key) {
  const job = await api('/api/reader/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ upload_id: preparedUpload.upload_id, key }) });
  $('uploadDialog').close(); notify('正在解析绘本，请稍候…');
  const completed = await jobWait(job); await refresh(); await selectBook(completed.book_id); $('books').value = completed.book_id;
}
$('upload').onclick = () => {
  if (busy || recorder?.state === 'recording') { notify('请先结束当前操作。'); return; } $('archive').value = ''; $('archive').click();
};
$('archive').onchange = () => lock(async () => {
  const file = $('archive').files[0]; if (!file) return;
  if (!/\.(pdf|zip)$/i.test(file.name)) throw Error('请选择 PDF 或 ZIP');
  if (file.size > 300 * 1024 * 1024) throw Error('上传文件不得超过 300 MB');
  const form = new FormData(); form.append('file', file); notify('正在上传并检查绘本…');
  preparedUpload = await api('/api/reader/uploads', { method: 'POST', body: form });
  if (preparedUpload.books.length === 1) {
    await importSelected(preparedUpload.books[0].key); return;
  }
  $('selectedArchive').textContent = `${file.name} · 检测到 ${preparedUpload.books.length} 本绘本`;
  $('key').replaceChildren(...preparedUpload.books.map(b => new Option(b.title, b.key)));
  $('uploadDialog').showModal();
});
$('cancelUpload').onclick = () => $('uploadDialog').close();
$('confirmUpload').onclick = () => lock(() => importSelected($('key').value));
$('uploadAudio').onclick = () => {
  if (busy || recorder?.state === 'recording') return; if (!book) {
    notify('请先选择绘本'); return;
  } $('audioFile').click();
};
$('generate').onclick = () => lock(async () => {
  if (!book) throw Error('请先选择绘本'); await jobWait(await api(`/api/books/${encodeURIComponent(book.book_id)}/generate`, { method: 'POST' })); busy = false; try { await selectBook(book.book_id); } finally { busy = true; }
});
$('question').onsubmit = e => {
  e.preventDefault(); if (recorder?.state === 'recording') return; lock(async () => { if (!book) throw Error('请先选择绘本'); const text = $('text').value.trim(); if (!text) return; message(text, true); $('text').value = ''; await answer(request('auto', { text })); });
};
$('audioFile').onchange = () => {
  const f = $('audioFile').files[0]; if (!f || recorder?.state === 'recording') return; lock(async () => { if (!book) throw Error('请先选择绘本'); audioMessage(f); await answer(request('qa', {}), f); }); $('audioFile').value = '';
};
$('record').onclick = async () => {
  if (recorder?.state === 'recording') {
    recorder.stop(); return;
  } if (!book) { notify('请先选择绘本'); return; } try {
    if (!navigator.mediaDevices?.getUserMedia) throw Error('录音需要 localhost 或 HTTPS'); stream = await navigator.mediaDevices.getUserMedia({ audio: true }); pause(); const chunks = []; recorder = new MediaRecorder(stream); recorder.ondataavailable = e => { if (e.data.size) chunks.push(e.data); }; const timer = setTimeout(() => { if (recorder.state === 'recording') recorder.stop(); }, 60000); recorder.onstop = () => {
      clearTimeout(timer); stream.getTracks().forEach(t => t.stop()); $('record').textContent = '开始录音'; const blob = new Blob(chunks, { type: recorder.mimeType }); const extension = recorder.mimeType.includes('mp4') ? 'm4a' : recorder.mimeType.includes('ogg') ? 'ogg' : 'webm';
      lock(async () => { const file = new File([blob], `recording.${extension}`, { type: blob.type }); audioMessage(file); await answer(request('qa', {}), file, true); });
    }; recorder.start(); $('record').textContent = '停止录音并发送'; notify('正在录音，最长 60 秒。');
  } catch (e) { stream?.getTracks().forEach(t => t.stop()); notify(e.message); }
};
for (const [id, delta] of [['prev', -1], ['next', 1]]) $(id).onclick = () => {
  if (!book || busy || recorder?.state === 'recording') return; pause(); index = Math.max(0, Math.min(book.pages.length - 1, index + delta)); showPage(); if (result?.full_video_path) video.currentTime = (result.pages.find(p => p.page_index === book.pages[index].index)?.start_ms || 0) / 1000;
  renderReview();
};
$('resume').onclick = () => {
  if (recorder?.state !== 'recording') resume();
};
$('page').onclick = e => lock(async () => {
  if (!book || recorder?.state === 'recording') return; const img = $('page'), r = img.getBoundingClientRect(); const scale = Math.min(r.width / img.naturalWidth, r.height / img.naturalHeight), w = img.naturalWidth * scale, h = img.naturalHeight * scale; const x = (e.clientX - r.left - (r.width - w) / 2) / w, y = (e.clientY - r.top - (r.height - h) / 2) / h; if (x < 0 || x > 1 || y < 0 || y > 1) return; await answer(request('click', { text: '识别点击对象', click: { x_norm: x, y_norm: y } }));
});
video.ontimeupdate = () => {
  if (!book) return; const ms = currentMs(); if (result?.full_video_path) {
    const p = result.pages.find(p => ms >= p.start_ms && ms < p.end_ms); if (p) { index = book.pages.findIndex(x => x.index === p.page_index); syncPageImage(); $('pageNumber').textContent = `第 ${index + 1} / ${book.pages.length} 页`; }
  } updateVideoObjects(); if (activeVariant !== 'canonical') { $('subtitle').textContent = ''; return; } const page = result?.pages?.find(p => p.page_index === book.pages[index]?.index); const local = ms - (page?.start_ms || 0); $('subtitle').textContent = (plan?.scenes || []).filter(s => s.page_index === book.pages[index]?.index).flatMap(s => s.subtitles || []).find(s => local >= s.start_ms && local < s.end_ms)?.text || '';
};
video.addEventListener('loadedmetadata', updateVideoObjects);
window.addEventListener('resize', updateVideoObjects);
video.onerror = () => notify('视频加载失败，请检查后端产物文件与媒体路径。');
$('export').onclick = () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(turns, null, 2)], { type: 'application/json' })); const a = document.createElement('a'); a.href = url; a.download = 'interaction-results.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
};

/* --- tabs --- */
function selectTab(name) {
  document.querySelectorAll('.tab').forEach(btn => btn.classList.toggle('active', btn.dataset.tab === name));
  document.querySelectorAll('.tabPanel').forEach(panel => panel.hidden = panel.id !== `tab-${name}`);
  history.replaceState(null, '', `#${name}`);
  if (name === 'review') loadReview();
  if (name === 'trace') loadTracePanel();
  if (name === 'eval') loadEvalPanel();
}
document.querySelectorAll('.tab').forEach(btn => btn.onclick = () => selectTab(btn.dataset.tab));
const initialTab = location.hash.slice(1);
if (['chat', 'review', 'trace', 'eval'].includes(initialTab)) selectTab(initialTab);

/* --- review / annotations --- */
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
function actionButton(text, onClick) {
  const element = document.createElement('button'); element.type = 'button'; element.textContent = text; element.onclick = onClick; return element;
}
function table(headers, rows) {
  const table = document.createElement('table');
  const head = document.createElement('thead'); const headRow = document.createElement('tr');
  for (const header of headers) { const th = document.createElement('th'); th.textContent = header; headRow.append(th); }
  head.append(headRow); table.append(head);
  const body = document.createElement('tbody');
  for (const cells of rows) {
    const tr = document.createElement('tr');
    for (const cell of cells) {
      const td = document.createElement('td');
      if (cell instanceof Node) td.append(cell); else td.textContent = cell;
      tr.append(td);
    }
    body.append(tr);
  }
  table.append(body); return table;
}
function sectionTitle(text) { const h = document.createElement('h3'); h.textContent = text; return h; }
function renderReview() {
  const wrap = $('reviewTargets');
  if (!book) { wrap.textContent = '请先选择绘本。'; return; }
  const page = book.pages[index];
  wrap.replaceChildren();
  wrap.append(sectionTitle(`第 ${page.index} 页 · 热区 ${page.hotspots.length} 个`));
  wrap.append(table(['热区', '描述', 'bbox', ''], page.hotspots.map(hotspot => [hotspot.label, hotspot.description || '', JSON.stringify(hotspot.bbox_px), actionButton('编辑', () => editHotspot(hotspot))])));
  wrap.append(sectionTitle(`文字块 ${page.text_spans.length} 个`));
  wrap.append(table(['文字', 'bbox', ''], page.text_spans.slice(0, 40).map(span => [span.text || '', JSON.stringify(span.bbox_px), actionButton('编辑', () => editSpan(span))])));
  const pageCards = qaCards.filter(card => (card.evidence || []).some(ev => ev.page_index === page.index));
  wrap.append(sectionTitle(`问答卡 ${pageCards.length} 张（本页）`));
  wrap.append(table(['问题', '强答案', ''], pageCards.map(card => [card.question_canonical || '', card.answers?.zh?.strong || card.answers?.en?.strong || '', actionButton('编辑', () => editCard(card))])));
}
function editHotspot(hotspot) {
  startEdit('hotspot', hotspot.hotspot_id, `热区：${hotspot.label}`, [
    { field: 'description', label: '描述', value: hotspot.description || '', json: false },
    { field: 'label', label: '标签', value: hotspot.label || '', json: false },
    { field: 'bbox_px', label: 'bbox（JSON）', value: hotspot.bbox_px, json: true },
  ]);
}
function editSpan(span) {
  startEdit('text_span', span.span_id, `文字块：${span.text}`, [
    { field: 'text', label: '文字', value: span.text || '', json: false },
    { field: 'bbox_px', label: 'bbox（JSON）', value: span.bbox_px, json: true },
  ]);
}
function editCard(card) {
  const fields = [
    { field: 'question_canonical', label: '标准问法', value: card.question_canonical || '', json: false },
    { field: 'variants', label: '变体（JSON 数组）', value: card.variants || [], json: true },
  ];
  for (const lang of Object.keys(card.answers || {})) {
    for (const tier of ['strong', 'weak', 'guide']) {
      fields.push({ field: `answers.${lang}.${tier}`, label: `${lang} / ${tier}`, value: card.answers?.[lang]?.[tier] || '', json: false });
    }
  }
  startEdit('qa_card', card.card_id, `问答卡：${card.question_canonical}`, fields);
}
function startEdit(targetType, targetId, label, fields) {
  editing = { targetType, targetId, fields };
  $('reviewEditor').hidden = false; $('reviewTarget').textContent = label;
  $('reviewField').replaceChildren(...fields.map((item, i) => new Option(item.label, String(i))));
  $('reviewField').value = '0'; showField();
}
function showField() {
  if (!editing) return;
  const item = editing.fields[Number($('reviewField').value)];
  $('reviewCurrent').value = item.json ? JSON.stringify(item.value, null, 2) : String(item.value ?? '');
  $('reviewValue').value = $('reviewCurrent').value;
}
async function saveReview() {
  if (!editing || !book) return;
  const item = editing.fields[Number($('reviewField').value)];
  let value;
  try { value = item.json ? JSON.parse($('reviewValue').value) : $('reviewValue').value; }
  catch (error) { notify('新值不是合法 JSON：' + error.message); return; }
  const payload = { target_type: editing.targetType, target_id: editing.targetId, field: item.field, value, reviewer: $('reviewReviewer').value.trim() || 'B', reason: $('reviewReason').value.trim() || null, old_value: item.value };
  try {
    const saved = await api(`/api/books/${encodeURIComponent(book.book_id)}/annotations`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    notify(saved.conflict ? '已写入；auto 值与旧值不一致，已进入冲突队列。' : '已写入人工修正，下一次交互立即生效。');
    await Promise.allSettled([loadAnnotations(), loadReviews()]);
  } catch (error) { notify('保存失败：' + error.message); }
}
async function loadAnnotations() {
  if (!book) return;
  const list = await api(`/api/books/${encodeURIComponent(book.book_id)}/annotations`).catch(() => []);
  $('annotationList').replaceChildren(list.length ? table(['目标', '字段', '值', '审核人'], list.map(item => [`${item.target_type}:${item.target_id}`, item.field, JSON.stringify(item.value), item.reviewer || ''])) : '还没有人工修正。');
}
async function loadReviews() {
  if (!book) return;
  const list = await api(`/api/books/${encodeURIComponent(book.book_id)}/review-items`).catch(() => []);
  $('reviewList').replaceChildren(list.length ? table(['目标', '原因', '说明'], list.map(item => [`${item.target_type}:${item.target_id}`, item.reason, item.notes || ''])) : '没有待审核项。');
}
async function batchSave() {
  if (!book) { notify('请先选择绘本'); return; }
  let items;
  try { items = JSON.parse($('reviewBatch').value); if (!Array.isArray(items)) throw Error('必须是数组'); }
  catch (error) { notify('JSON 解析失败：' + error.message); return; }
  let ok = 0;
  for (const item of items) {
    try { await api(`/api/books/${encodeURIComponent(book.book_id)}/annotations`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reviewer: 'B', ...item }) }); ok += 1; }
    catch (error) { notify(`第 ${ok + 1} 条失败：${error.message}`); break; }
  }
  notify(`已提交 ${ok}/${items.length} 条修正。`);
  await Promise.allSettled([loadAnnotations(), loadReviews()]);
}
async function loadReview() {
  if (!book) return;
  renderReview();
  await Promise.allSettled([loadQaCards().then(renderReview), loadAnnotations(), loadReviews()]);
}
$('reviewField').onchange = showField;
$('reviewSave').onclick = saveReview;
$('reviewCancel').onclick = () => { editing = null; $('reviewEditor').hidden = true; };
$('reviewBatchSave').onclick = batchSave;

/* --- trace / manifest --- */
function renderTraceList(traces) {
  const wrap = $('traceList');
  if (!traces.length) { wrap.textContent = '还没有在线调用记录，先问一个问题。'; return; }
  wrap.replaceChildren(...traces.map(trace => {
    const card = document.createElement('div'); card.className = 'traceCard';
    const line = document.createElement('div'); line.className = 'line';
    const status = document.createElement('span'); status.className = 'badge' + (trace.result?.status === 'ok' ? ' ok' : ' warn'); status.textContent = trace.result?.status || 'unknown'; line.append(status);
    if (trace.result?.tier) { const tier = document.createElement('span'); tier.className = 'badge'; tier.textContent = TIER_LABEL[trace.result.tier] || trace.result.tier; line.append(tier); }
    const kind = document.createElement('span'); kind.textContent = trace.result?.kind || trace.kind; line.append(kind);
    const ms = document.createElement('span'); ms.textContent = `${trace.latency_ms} ms`; line.append(ms);
    const time = document.createElement('span'); time.textContent = new Date(trace.created_at).toLocaleTimeString(); line.append(time);
    card.append(line);
    const stages = document.createElement('div'); stages.className = 'stages';
    (trace.stages || []).forEach(stage => { const pill = document.createElement('span'); pill.className = 'stagePill'; pill.textContent = `${stage.name} ${stage.ms}ms`; stages.append(pill); });
    card.append(stages);
    const intents = (trace.input?.intents || []).map(item => `${item.kind}: ${item.text}`).join('；');
    if (intents) { const item = document.createElement('div'); item.className = 'answer'; item.textContent = intents; card.append(item); }
    if (trace.result?.answer) { const answer = document.createElement('div'); answer.className = 'answer'; answer.textContent = trace.result.answer.slice(0, 180); card.append(answer); }
    return card;
  }));
}
async function loadTools() {
  if (toolsLoaded) return; toolsLoaded = true;
  const [tools, providers] = await Promise.all([
    api('/api/tools').catch(() => []),
    api('/api/providers').catch(() => []),
  ]);
  $('toolList').replaceChildren(tools.length ? table(['工具', '类型', '说明'], tools.map(tool => [tool.name, tool.kind, tool.description])) : '工具注册表不可用。');
  $('providerList').replaceChildren(providers.length ? table(['能力', 'Provider', '模型', '状态'], providers.map(item => [item.kind, item.provider, item.model || '—', item.available ? '可用' : (item.detail || '不可用')])) : '模型配置不可用。');
}
async function loadManifest() {
  if (!book) return;
  const text = await fetch(asset('derived/manifest.json')).then(r => r.ok ? r.text() : '').catch(() => '');
  if (!text) { $('manifestList').textContent = '还没有全链 manifest；可以运行 python -m pipeline run --book ' + book.book_id; return; }
  let manifest;
  try { manifest = JSON.parse(text); } catch { $('manifestList').textContent = 'manifest 解析失败。'; return; }
  $('manifestList').replaceChildren(table(['阶段', 'provider / model', '耗时', '状态'], (manifest.stages || []).map(stage => [stage.name, `${stage.provider || ''} / ${stage.model || ''}`, `${stage.duration_ms || 0} ms`, stage.status + (stage.degraded ? ' · degraded' : '')])));
}
async function loadCritic() {
  if (!book) return;
  const text = await fetch(asset('derived/critic/report.json')).then(r => r.ok ? r.text() : '').catch(() => '');
  if (!text) { $('criticList').textContent = '还没有 Critic 报告；运行 --from critic 生成。'; return; }
  let report;
  try { report = JSON.parse(text); } catch { $('criticList').textContent = 'Critic 报告解析失败。'; return; }
  const warnings = report.warnings || [];
  const head = document.createElement('p');
  head.textContent = report.ok ? `通过 · ${warnings.length} 条提醒` : `未通过 · ${warnings.length} 条问题`;
  const wrap = document.createElement('div');
  wrap.append(head);
  if (warnings.length) wrap.append(table(['类型', '说明', '页'], warnings.slice(0, 20).map(item => [item.code, item.message, item.page_index ?? '—'])));
  $('criticList').replaceChildren(wrap);
}
async function loadTracePanel() {
  if (!book) return;
  await Promise.allSettled([loadTools(), loadManifest(), loadCritic()]);
  const traces = await api(`/api/books/${encodeURIComponent(book.book_id)}/traces?session_id=${encodeURIComponent(session)}&limit=5`).catch(() => []);
  renderTraceList(traces);
}

/* --- evaluation --- */
function kvGrid(items) {
  const grid = document.createElement('div'); grid.className = 'kv';
  for (const [label, value] of items) {
    const cell = document.createElement('div'); const b = document.createElement('b'); b.textContent = value; const span = document.createElement('span'); span.textContent = label; cell.append(b, span); grid.append(cell);
  }
  return grid;
}
async function loadEvalPanel() {
  if (!book) return;
  const cap = await api(`/api/books/${encodeURIComponent(book.book_id)}/capability`).catch(() => null);
  if (cap) {
    const coverage = cap.coverage || {};
    const percent = value => `${Math.round((value || 0) * 100)}%`;
    const wrap = document.createElement('div');
    wrap.append(kvGrid([['页数', cap.pages_total], ['文字页', cap.pages_with_text], ['热区', cap.hotspots], ['场景', cap.scenes], ['问答卡', cap.qa_cards], ['文字覆盖', percent(coverage.text_search)], ['视频覆盖', percent(coverage.video)], ['问答覆盖', percent(coverage.qa)]]));
    if (cap.limitations?.length) { const list = document.createElement('ul'); cap.limitations.slice(0, 6).forEach(text => { const li = document.createElement('li'); li.textContent = text; list.append(li); }); wrap.append(list); }
    if (cap.needs_review?.length) { const p = document.createElement('p'); p.textContent = `待审核 ${cap.needs_review.length} 项；在“审核修正”里处理。`; wrap.append(p); }
    $('capability').replaceChildren(wrap);
  } else { $('capability').textContent = '能力报告不可用。'; }
  const run = await api('/api/eval/latest').catch(() => ({}));
  if (!run.run_id) { $('evalRun').textContent = '还没有评测结果；可以运行 python -m pipeline eval --book ' + book.book_id; return; }
  const metrics = run.metrics || {};
  $('evalRun').replaceChildren(
    kvGrid([['用例', metrics.total ?? '-'], ['通过', metrics.ok ?? '-'], ['问答正确', `${metrics.qa_correct ?? '-'} / ${metrics.qa_total ?? '-'}`], ['回退率', metrics.fallback_rate != null ? `${Math.round(metrics.fallback_rate * 100)}%` : '-'], ['证据率', metrics.evidence_rate != null ? `${Math.round(metrics.evidence_rate * 100)}%` : '-']]),
    Object.assign(document.createElement('p'), { textContent: `${run.run_id} · ${run.status} · ${run.book_ids?.join(', ') || ''}` }),
  );
}

window.addEventListener('pagehide', () => {
  clearAudio(); stream?.getTracks().forEach(t => t.stop()); speechSynthesis.cancel();
});
refresh().catch(e => notify(`连接失败：${e.message}。请通过联调服务打开页面。`));

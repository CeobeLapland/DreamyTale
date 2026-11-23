const $=id=>document.getElementById(id);
let book=null,result=null,plan=null,index=0,busy=false,recorder=null,stream=null,wasPlaying=false,turns=[],session=crypto.randomUUID();
const video=$('video'),reply=$('reply');
const notify=t=>$('notice').textContent=t;
async function api(path, options={}){const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),120000);try{const r=await fetch(path,{...options,signal:controller.signal});const data=await r.json();if(!r.ok)throw Error(data.error?.message||data.detail||`HTTP ${r.status}`);return data;}finally{clearTimeout(timer);}}
const asset=path=>`/api/books/${encodeURIComponent(book.book_id)}/assets/${path.split('/').map(encodeURIComponent).join('/')}`;
const audioUrls=[];
function audioMessage(file){
  const bubble=document.createElement('div');bubble.className='bubble user voiceBubble';bubble.title=file.name;
  const player=document.createElement('audio');player.preload='metadata';player.hidden=true;
  const url=URL.createObjectURL(file);audioUrls.push(url);player.src=url;
  const play=document.createElement('button');play.type='button';play.className='voicePlay';play.textContent='▶ 语音消息';play.setAttribute('aria-label','播放语音消息');
  const time=document.createElement('span');time.className='voiceTime';time.textContent='0:00';
  const volume=document.createElement('input');volume.type='range';volume.min='0';volume.max='1';volume.step='0.05';volume.value='1';volume.className='voiceVolume';volume.setAttribute('aria-label','语音音量');volume.title='调整音量';volume.oninput=()=>{player.volume=Number(volume.value);};
  const clock=value=>{if(!Number.isFinite(value))return '0:00';return `${Math.floor(value/60)}:${String(Math.floor(value%60)).padStart(2,'0')}`;};
  const update=()=>{time.textContent=Number.isFinite(player.duration)?`${clock(player.currentTime)} / ${clock(player.duration)}`:clock(player.currentTime);};
  play.onclick=async()=>{if(player.paused){try{await player.play();}catch{notify('这段音频暂时无法播放，请检查文件格式。');}}else player.pause();};
  player.onplay=()=>{video.pause();reply.pause();speechSynthesis.cancel();document.querySelectorAll('#messages audio').forEach(a=>{if(a!==player)a.pause();});play.textContent='Ⅱ 语音消息';play.setAttribute('aria-label','暂停语音消息');};
  player.onpause=player.onended=()=>{play.textContent='▶ 语音消息';play.setAttribute('aria-label','播放语音消息');update();};
  player.onloadedmetadata=player.ontimeupdate=update;
  player.onerror=()=>{time.textContent='无法播放';notify('音频无法解码，请尝试 WAV 或 MP3 文件。');};
  bubble.append(play,time,volume,player);$('messages').append(bubble);bubble.scrollIntoView({block:'nearest'});
}
function clearAudio(){document.querySelectorAll('#messages audio').forEach(a=>a.pause());audioUrls.splice(0).forEach(URL.revokeObjectURL);}
function message(text,user=false){const el=document.createElement('div');el.className='bubble'+(user?' user':'');el.textContent=text;$('messages').append(el);el.scrollIntoView({block:'nearest'});}
function pause(){document.querySelectorAll('#messages audio').forEach(a=>a.pause());wasPlaying=!video.paused;video.pause();reply.pause();speechSynthesis.cancel();}
async function resume(){document.querySelectorAll('#messages audio').forEach(a=>a.pause());reply.pause();speechSynthesis.cancel();if(video.hasAttribute('src'))try{await video.play();}catch{notify('请点击视频播放按钮继续。');}}
function currentMs(){return Math.round(video.currentTime*1000)+(result?.full_video_path?0:(result?.pages?.find(p=>p.page_index===book?.pages[index]?.index)?.start_ms||0));}
function showPage(){const p=book.pages[index];$('pageNumber').textContent=`第 ${index+1} / ${book.pages.length} 页`;$('page').src=asset(p.image_path);const path=result?.full_video_path||result?.pages?.find(x=>x.page_index===p.index)?.video_path;video.hidden=!path;$('page').hidden=!!path;$('empty').hidden=true;if(path){const url=asset(path);if(video.getAttribute('src')!==url){video.src=url;video.load();}}else{video.removeAttribute('src');video.load();} $('subtitle').textContent='';}
async function selectBook(id){if(recorder?.state==='recording')return;pause();book=await api(`/api/books/${encodeURIComponent(id)}`);index=0;session=crypto.randomUUID();turns=[];clearAudio();$('messages').replaceChildren();result=null;plan=null;const responses=await Promise.allSettled(['generation-result','scene-plan'].map(p=>api(`/api/books/${encodeURIComponent(id)}/${p}`)));if(responses[0].status==='fulfilled')result=responses[0].value;if(responses[1].status==='fulfilled')plan=responses[1].value;$('title').textContent=book.title;showPage();notify(result?'已载入生成产物；点击播放开始阅读。':'绘本已载入，目前还没有可播放的生成视频。');}
async function refresh(){const list=await api('/api/books');$('books').replaceChildren(new Option('请选择绘本',''),...list.map(b=>new Option(b.title,b.book_id)));if(book)$('books').value=book.book_id;notify(`已连接后端，书架共 ${list.length} 本绘本。`);}
async function jobWait(job){for(let n=0;n<900;n++){ $('job').textContent=`${job.stage} · ${job.status} · ${Math.round(job.progress*100)}%`;if(['completed','degraded'].includes(job.status))return job;if(['failed','cancelled'].includes(job.status))throw Error(job.error||'任务未完成');await new Promise(r=>setTimeout(r,2000));job=await api(`/api/jobs/${encodeURIComponent(job.job_id)}`);}throw Error('等待超时，任务可能仍在后台运行。');}
async function lock(fn){if(busy)return;busy=true;document.querySelectorAll('button,select').forEach(x=>x.disabled=true);try{await fn();}catch(e){notify(e.name==='AbortError'?'请求超时，请检查后台任务状态。':e.message);}finally{busy=false;document.querySelectorAll('button,select').forEach(x=>x.disabled=false);}}
function request(kind,input){return {book_id:book.book_id,session_id:session,kind,input:{page_index:book.pages[index].index,current_time_ms:currentMs(),language:book.language,...input},context:{last_page_index:book.pages[index].index,history_turn_ids:turns.map(t=>t.request_id)}};}
async function answer(payload,audioFile=null,alreadyPaused=false){if(!book)throw Error('请先选择绘本');if(!alreadyPaused)pause();let response;const started=performance.now();if(audioFile){const form=new FormData();form.append('audio',audioFile,audioFile.name||'recording.webm');form.append('request',JSON.stringify(payload));response=await api('/api/interact/audio',{method:'POST',body:form});}else response=await api('/api/interact',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});turns.push({...response,client_elapsed_ms:Math.round(performance.now()-started)});const text=response.answer?.text||response.error?.message||'没有返回回答';message((response.status==='ok'?'':'[能力受限] ')+text);const a=response.action||{};if(a.type==='seek'&&a.time_ms!=null){const page=result?.pages?.find(p=>a.time_ms>=p.start_ms&&a.time_ms<p.end_ms);if(page){index=book.pages.findIndex(p=>p.index===page.page_index);showPage();video.currentTime=(a.time_ms-(result.full_video_path?0:page.start_ms))/1000;}}if(['play','resume'].includes(a.type)){await resume();return;}if(['pause','stop'].includes(a.type)){wasPlaying=false;return;}if(response.status!=='ok'){notify(response.error?.message||'后端当前能力不足，故事保持暂停。');return;}const finish=()=>{if(wasPlaying)resume();};if(response.answer?.audio_path){reply.src=asset(response.answer.audio_path);reply.hidden=false;reply.onended=finish;try{await reply.play();}catch{notify('点击回答音频播放，或点击继续故事。');}}else if($('speak').checked&&text){const speech=new SpeechSynthesisUtterance(text);speech.lang=book.language;speech.onend=finish;speech.onerror=()=>notify('朗读不可用，可点击继续故事。');speechSynthesis.speak(speech);}else finish();}
$('refresh').onclick=()=>lock(refresh);$('books').onchange=()=>{if($('books').value)lock(()=>selectBook($('books').value));};
// selectBook is also called inside locked operations; only the caller controls concurrency.
$('books').onchange=()=>lock(async()=>{const id=$('books').value;if(id){busy=false;try{await selectBook(id);}finally{busy=true;}}});
let preparedUpload=null;
async function importSelected(key){
  const job=await api('/api/reader/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({upload_id:preparedUpload.upload_id,key})});
  $('uploadDialog').close();notify('正在解析绘本，请稍候…');
  const completed=await jobWait(job);await refresh();await selectBook(completed.book_id);$('books').value=completed.book_id;
}
$('upload').onclick=()=>{if(busy||recorder?.state==='recording'){notify('请先结束当前操作。');return;}$('archive').value='';$('archive').click();};
$('archive').onchange=()=>lock(async()=>{
  const file=$('archive').files[0];if(!file)return;
  if(!/\.(pdf|zip)$/i.test(file.name))throw Error('请选择 PDF 或 ZIP');
  if(file.size>300*1024*1024)throw Error('上传文件不得超过 300 MB');
  const form=new FormData();form.append('file',file);notify('正在上传并检查绘本…');
  preparedUpload=await api('/api/reader/uploads',{method:'POST',body:form});
  if(preparedUpload.books.length===1){await importSelected(preparedUpload.books[0].key);return;}
  $('selectedArchive').textContent=`${file.name} · 检测到 ${preparedUpload.books.length} 本绘本`;
  $('key').replaceChildren(...preparedUpload.books.map(b=>new Option(b.title,b.key)));
  $('uploadDialog').showModal();
});
$('cancelUpload').onclick=()=>$('uploadDialog').close();
$('confirmUpload').onclick=()=>lock(()=>importSelected($('key').value));
$('uploadAudio').onclick=()=>{if(busy||recorder?.state==='recording')return;if(!book){notify('请先选择绘本');return;}$('audioFile').click();};
$('generate').onclick=()=>lock(async()=>{if(!book)throw Error('请先选择绘本');await jobWait(await api(`/api/books/${encodeURIComponent(book.book_id)}/generate`,{method:'POST'}));busy=false;try{await selectBook(book.book_id);}finally{busy=true;}});
$('question').onsubmit=e=>{e.preventDefault();if(recorder?.state==='recording')return;lock(async()=>{if(!book)throw Error('请先选择绘本');const text=$('text').value.trim();if(!text)return;message(text,true);$('text').value='';await answer(request('auto',{text}));});};
$('audioFile').onchange=()=>{const f=$('audioFile').files[0];if(!f||recorder?.state==='recording')return;lock(async()=>{if(!book)throw Error('请先选择绘本');audioMessage(f);await answer(request('qa',{}),f);});$('audioFile').value='';};
$('record').onclick=async()=>{if(recorder?.state==='recording'){recorder.stop();return;}if(!book){notify('请先选择绘本');return;}try{if(!navigator.mediaDevices?.getUserMedia)throw Error('录音需要 localhost 或 HTTPS');stream=await navigator.mediaDevices.getUserMedia({audio:true});pause();const chunks=[];recorder=new MediaRecorder(stream);recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};const timer=setTimeout(()=>{if(recorder.state==='recording')recorder.stop();},60000);recorder.onstop=()=>{clearTimeout(timer);stream.getTracks().forEach(t=>t.stop());$('record').textContent='开始录音';const blob=new Blob(chunks,{type:recorder.mimeType});const extension=recorder.mimeType.includes('mp4')?'m4a':recorder.mimeType.includes('ogg')?'ogg':'webm';lock(async()=>{const file=new File([blob],`recording.${extension}`,{type:blob.type});audioMessage(file);await answer(request('qa',{}),file,true);});};recorder.start();$('record').textContent='停止录音并发送';notify('正在录音，最长 60 秒。');}catch(e){stream?.getTracks().forEach(t=>t.stop());notify(e.message);}};
for(const [id,delta] of [['prev',-1],['next',1]])$(id).onclick=()=>{if(!book||busy||recorder?.state==='recording')return;pause();index=Math.max(0,Math.min(book.pages.length-1,index+delta));showPage();if(result?.full_video_path)video.currentTime=(result.pages.find(p=>p.page_index===book.pages[index].index)?.start_ms||0)/1000;};
$('resume').onclick=()=>{if(recorder?.state!=='recording')resume();};
$('page').onclick=e=>lock(async()=>{if(!book||recorder?.state==='recording')return;const img=$('page'),r=img.getBoundingClientRect();const scale=Math.min(r.width/img.naturalWidth,r.height/img.naturalHeight),w=img.naturalWidth*scale,h=img.naturalHeight*scale;const x=(e.clientX-r.left-(r.width-w)/2)/w,y=(e.clientY-r.top-(r.height-h)/2)/h;if(x<0||x>1||y<0||y>1)return;await answer(request('click',{text:'识别点击对象',click:{x_norm:x,y_norm:y}}));});
video.ontimeupdate=()=>{if(!book)return;const ms=currentMs();if(result?.full_video_path){const p=result.pages.find(p=>ms>=p.start_ms&&ms<p.end_ms);if(p){index=book.pages.findIndex(x=>x.index===p.page_index);$('pageNumber').textContent=`第 ${index+1} / ${book.pages.length} 页`;}}const page=result?.pages?.find(p=>p.page_index===book.pages[index]?.index);const local=ms-(page?.start_ms||0);$('subtitle').textContent=(plan?.scenes||[]).filter(s=>s.page_index===book.pages[index]?.index).flatMap(s=>s.subtitles||[]).find(s=>local>=s.start_ms&&local<s.end_ms)?.text||'';};
video.onerror=()=>notify('视频加载失败，请检查后端产物文件与媒体路径。');
$('export').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(turns,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='interaction-results.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
window.addEventListener('pagehide',()=>{clearAudio();stream?.getTracks().forEach(t=>t.stop());speechSynthesis.cancel();});
refresh().catch(e=>notify(`连接失败：${e.message}。请通过联调服务打开页面。`));

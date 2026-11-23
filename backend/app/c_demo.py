"""C 前端联调入口；复用现有 API，不修改 A/B 的实现。"""
import json
from pathlib import Path
from fastapi import UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from backend.app.api import app, books
from backend.app.models import InteractionRequest
from backend.app.interaction import handle_interaction

@app.post('/api/interact/audio')
async def audio_interaction(audio: UploadFile = File(...), request: str = Form(...)):
    try:
        raw = json.loads(request)
        raw.setdefault("input", {})["audio_path"] = "upload://current-audio"
        payload = InteractionRequest.model_validate(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, 'request 必须是合法的 InteractionRequest') from exc
    package = books.load(payload.book_id)
    suffix = Path(audio.filename or '').suffix.lower()
    if suffix not in {'.wav', '.mp3', '.webm', '.m4a', '.ogg', '.mp4', '.flac'}:
        raise HTTPException(415, '不支持的音频格式')
    size = 0
    try:
        while chunk := await audio.read(1024 * 1024):
            size += len(chunk)
            if size > 20 * 1024 * 1024:
                raise HTTPException(413, '音频不得超过 20 MB')
    finally:
        await audio.close()
    if not size:
        raise HTTPException(422, '音频文件为空')
    # 目前只验证传输。不要把文件名或测试脚本当作 ASR 转录结果。
    # A/B 后续在此调用服务端 ASR，把转录写入 payload.input.text 后走统一问答。
    payload.input.text = None
    response = handle_interaction(payload, package, books.package_root(payload.book_id))
    response.status = 'fallback'
    if response.answer:
        response.answer.text = '音频已传到后端，但 ASR、生成式问答和 TTS 尚未配置，当前无法识别并回答。请使用文字提问验证已有检索能力。'
    return response

app.mount('/reader', StaticFiles(directory=Path(__file__).resolve().parents[2] / 'frontend', html=True), name='reader')

from backend.app import reader_upload  # Register PDF and ZIP reader upload routes.

@app.get('/favicon.ico', include_in_schema=False)
def favicon():
    from fastapi.responses import FileResponse
    return FileResponse(Path(__file__).resolve().parents[2] / 'frontend/favicon.svg', media_type='image/svg+xml')

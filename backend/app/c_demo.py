"""C 前端联调入口；复用现有 API，不修改 A/B 的实现。"""
import json
import os
import tempfile
from pathlib import Path
from fastapi import UploadFile, File, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from backend.app.api import app, books
from backend.app.asr_runtime import answer_language, is_low_confidence, recognize
from backend.app.conductor import run_interaction, run_low_confidence
from backend.app.models import InteractionKind, InteractionRequest

@app.post('/api/interact/audio')
async def audio_interaction(audio: UploadFile = File(...), request: str = Form(...)):
    try:
        raw = json.loads(request)
        raw.setdefault("input", {})["audio_path"] = "upload://current-audio"
        payload = InteractionRequest.model_validate(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, 'request 必须是合法的 InteractionRequest') from exc
    package = books.load(payload.book_id)
    package_root = books.package_root(payload.book_id)
    suffix = Path(audio.filename or '').suffix.lower()
    if suffix not in {'.wav', '.mp3', '.webm', '.m4a', '.ogg', '.mp4', '.flac'}:
        raise HTTPException(415, '不支持的音频格式')

    handle, temp_name = tempfile.mkstemp(prefix='dreamytale-asr-', suffix=suffix)
    size = 0
    try:
        with os.fdopen(handle, 'wb') as target:
            while chunk := await audio.read(1024 * 1024):
                size += len(chunk)
                if size > 20 * 1024 * 1024:
                    raise HTTPException(413, '音频不得超过 20 MB')
                target.write(chunk)
    finally:
        await audio.close()

    try:
        if not size:
            raise HTTPException(422, '音频文件为空')

        result, reason = await run_in_threadpool(
            recognize, Path(temp_name), package, package_root
        )
        if result is None or not result.text:
            # 能力没就绪就明确说，不拿识别失败冒充回答。
            payload.input.text = ''
            payload.kind = InteractionKind.qa
            response = await run_in_threadpool(
                run_interaction,
                payload,
                package,
                package_root,
                data_root=books.root.parent,
                input_audio='upload://current-audio',
                answer_audio=False,
            )
            response.status = 'fallback'
            response.transcript = result.text if result is not None else None
            detail = reason or '没有识别到语音内容，请再说一次'
            message = f'语音已收到，但本机语音识别没有给出结果（{detail}）。可以再说一次，或先用文字提问。'
            if response.answer is not None:
                response.answer.text = message
            if response.error is not None:
                response.error.message = message
            return response

        if is_low_confidence(result):
            # Whisper itself is unsure. Never route a guess into the book.
            return await run_in_threadpool(
                run_low_confidence,
                payload,
                package,
                package_root,
                transcript=result.text,
                confidence=result.confidence,
                asr_ms=result.latency_ms,
                data_root=books.root.parent,
            )

        # 语音输入必须重新路由：前端把音频请求固定标成 qa，
        # 但"播放/暂停/找到……"是 control/seek，不能被当成问答。
        payload.input.text = result.text
        payload.input.audio_path = None
        payload.input.language = answer_language(result.language, payload.input.language)
        payload.kind = InteractionKind.auto
        response = await run_in_threadpool(
            run_interaction,
            payload,
            package,
            package_root,
            data_root=books.root.parent,
            input_text=result.text,
            input_audio='upload://current-audio',
            asr_ms=result.latency_ms,
        )
        response.transcript = result.text
        return response
    finally:
        Path(temp_name).unlink(missing_ok=True)

app.mount('/reader', StaticFiles(directory=Path(__file__).resolve().parents[2] / 'frontend', html=True), name='reader')

@app.get('/review', include_in_schema=False)
def review_page():
    # The standalone review page is gone; review is a tab of the reader now.
    return RedirectResponse('/reader/#review')

from backend.app import reader_upload  # Register PDF and ZIP reader upload routes.

@app.get('/favicon.ico', include_in_schema=False)
def favicon():
    from fastapi.responses import FileResponse
    return FileResponse(Path(__file__).resolve().parents[2] / 'frontend/favicon.svg', media_type='image/svg+xml')

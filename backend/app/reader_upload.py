"""阅读素材上传：PDF 或 ZIP 内的 PDF，不依赖测试题音频。"""
import io
import json
import uuid
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import pypdfium2 as pdfium
from pypdf import PdfReader
from fastapi import UploadFile, File, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from backend.app.api import app, books, UPLOAD_ROOT, job_store
from backend.app.archive import decode_zip_name, is_ignored_member
from backend.app.ingest import _extract_lines, _build_page, _sha256_bytes
from backend.app.models import BookPackage, Page, Job

ROOT = UPLOAD_ROOT / 'reader'
LIMIT = 300 * 1024 * 1024

def candidates(path):
    if path.suffix == '.pdf':
        return [{'key': 'pdf', 'title': 'PDF'}]
    try:
        with zipfile.ZipFile(path) as archive:
            found=[]
            for i, item in enumerate(archive.infolist()):
                if not item.is_dir() and not is_ignored_member(item.filename) and item.filename.lower().endswith('.pdf'):
                    if item.file_size > 100*1024*1024:
                        raise ValueError('ZIP 中单个 PDF 不得超过 100 MB')
                    found.append({'key':str(i),'title':decode_zip_name(item.filename)})
            if not found:
                raise ValueError('ZIP 中没有 PDF 绘本')
            return found
    except zipfile.BadZipFile as exc:
        raise ValueError('ZIP 文件损坏或格式不正确') from exc

@app.post('/api/reader/uploads')
async def prepare_upload(file: UploadFile = File(...)):
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in {'.pdf','.zip'}:
        raise HTTPException(415,'请选择 PDF 或 ZIP')
    ROOT.mkdir(parents=True,exist_ok=True)
    token=uuid.uuid4().hex
    path=ROOT / (token+suffix)
    try:
        size=0
        with path.open('wb') as out:
            while chunk:=await file.read(1024*1024):
                size+=len(chunk)
                if size>LIMIT: raise HTTPException(413,'上传文件不得超过 300 MB')
                out.write(chunk)
        if not size: raise ValueError('文件为空')
        entries=await run_in_threadpool(candidates,path)
        if suffix=='.pdf': entries[0]['title']=Path(file.filename).stem
        meta={'suffix':suffix,'entries':entries}
        (ROOT/(token+'.json')).write_text(json.dumps(meta),encoding='utf-8')
        return {'upload_id':token,'books':entries}
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

class Selection(BaseModel):
    upload_id: str
    key: str

def import_pdf(pdf_bytes, title, package_id):
    package_root=books.root/package_id
    package_root.mkdir(parents=True,exist_ok=False)
    (package_root/'source').mkdir()
    (package_root/'source/book.pdf').write_bytes(pdf_bytes)
    language='en' if '英文' in title else 'zh-CN'
    render_scale=1.5
    try:
        reader=PdfReader(io.BytesIO(pdf_bytes))
        if not 0<len(reader.pages)<=200: raise ValueError('PDF 页数必须为 1～200 页')
        for p in reader.pages:
            if float(p.mediabox.width)*float(p.mediabox.height)*render_scale**2>16000000:
                raise ValueError('PDF 页面尺寸过大')
    except Exception as exc:
        raise ValueError(f'无法读取 PDF：{exc}') from exc
    reader = PdfReader(io.BytesIO(pdf_bytes))
    document = pdfium.PdfDocument(pdf_bytes)
    dpi = max(36, min(600, round(72 * render_scale)))
    pages: list[Page] = []
    try:
        for index, source_page in enumerate(reader.pages, start=1):
            # 文本层用 pypdf 抽（行切分能正确处理斜排水印），坐标用 pdfium 的字符框。
            text_lines = [
                line.strip()
                for line in (source_page.extract_text() or "").splitlines()
                if line.strip()
            ]
            width_pt = float(source_page.mediabox.width)
            height_pt = float(source_page.mediabox.height)
            image_path = f"pages/{index:03d}.png"
            rendered = document[index - 1].render(scale=render_scale)
            image = rendered.to_pil()
            image_file = package_root / image_path
            image_file.parent.mkdir(parents=True, exist_ok=True)
            image.save(image_file, format="PNG", optimize=True)
            lines = _extract_lines(
                document[index - 1],
                text_lines=text_lines,
                width_px=image.width,
                height_px=image.height,
                width_pt=width_pt,
                height_pt=height_pt,
            )
            pages.append(
                _build_page(
                    book_id=package_id,
                    language=language,
                    index=index,
                    image_path=image_path,
                    sha256=_sha256_bytes(image_file),
                    width_px=image.width,
                    height_px=image.height,
                    width_pt=width_pt,
                    height_pt=height_pt,
                    lines=lines,
                    dpi=dpi,
                )
            )
    finally:
        document.close()

    package=BookPackage(schema_version='2.0.0',book_id=package_id,source_name=title,title=title,
        language=language,languages=[language],content_type='narrative',source_type='pdf',source_path='source/book.pdf',
        page_count=len(pages),pages=pages,status='ingested',query_set_ids=[],rights=None,
        created_at=datetime.now(timezone.utc),updated_at=datetime.now(timezone.utc))
    (package_root/'derived').mkdir(exist_ok=True)
    (package_root/'book.json').write_text(package.model_dump_json(indent=2),encoding='utf-8')

@app.post('/api/reader/import',status_code=202)
def submit_import(selection: Selection):
    if len(selection.upload_id)!=32 or any(c not in '0123456789abcdef' for c in selection.upload_id):
        raise ValueError('无效上传编号')
    meta_path=ROOT/(selection.upload_id+'.json')
    meta=json.loads(meta_path.read_text(encoding='utf-8'))
    selected=next((e for e in meta['entries'] if e['key']==selection.key),None)
    if not selected: raise ValueError('所选 PDF 不在上传文件中')
    path=ROOT/(selection.upload_id+meta['suffix'])
    package_id='book-'+uuid.uuid4().hex[:16]
    now=datetime.now(timezone.utc)
    job=Job(job_id='job-'+uuid.uuid4().hex,book_id=package_id,status='queued',stage='ingest',progress=0,created_at=now,updated_at=now)
    job_store.create(job)
    def execute():
        try:
            job_store.update(job.job_id,status='running',progress=0.05)
            if path.suffix=='.pdf': data=path.read_bytes()
            else:
                with zipfile.ZipFile(path) as archive: data=archive.read(archive.infolist()[int(selection.key)])
            import_pdf(data,Path(selected['title']).stem,package_id)
            job_store.update(job.job_id,status='completed',progress=1.0)
        except Exception as exc:
            job_store.update(job.job_id,status='failed',error=str(exc),error_code='INGEST_RENDER_FAILED')
        finally:
            path.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
    threading.Thread(target=execute,daemon=True).start()
    return job.model_dump(mode='json')

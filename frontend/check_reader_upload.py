import io,json,tempfile,time,zipfile
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from backend.app.c_demo import app
from backend.app import reader_upload as upload
from backend.app.store import BookStore
from backend.app.jobs import JobStore
writer=PdfWriter();writer.add_blank_page(width=200,height=200);out=io.BytesIO();writer.write(out);pdf=out.getvalue()
with tempfile.TemporaryDirectory() as d:
 root=Path(d)
 with patch.object(upload,'ROOT',root/'uploads'),patch.object(upload,'books',BookStore(root/'books')),patch.object(upload,'job_store',JobStore(root/'jobs.json')):
  client=TestClient(app)
  def check(data,name,count):
   r=client.post('/api/reader/uploads',files={'file':(name,data)});assert r.status_code==200,r.text
   body=r.json();assert len(body['books'])==count
   r=client.post('/api/reader/import',json={'upload_id':body['upload_id'],'key':body['books'][0]['key']});assert r.status_code==202,r.text
   for _ in range(100):
    job=upload.job_store.get(r.json()['job_id'])
    if job.status.value in ('failed','completed'):break
    time.sleep(.05)
   assert job.status.value=='completed',job.error
   package=upload.books.load(job.book_id);assert package.page_count==1
   assert (root/'books'/job.book_id/'source/book.pdf').exists()
  check(pdf,'single.pdf',1)
  for count in (1,2):
   z=io.BytesIO()
   with zipfile.ZipFile(z,'w') as archive:
    for i in range(count):archive.writestr(f'folder/book{i}.pdf',pdf)
   check(z.getvalue(),'books.zip',count)
  assert client.post('/api/reader/uploads',files={'file':('bad.zip',b'bad')}).status_code==422
  assert client.post('/api/reader/uploads',files={'file':('bad.exe',b'bad')}).status_code==415
print('PASS PDF import, one/multiple PDF ZIPs without audio, stored book contract, invalid uploads')

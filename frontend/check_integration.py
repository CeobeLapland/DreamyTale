import tempfile,json
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app import api
from backend.app.c_demo import app
from backend.app.store import BookStore
from backend.tests.fixtures import write_package
with tempfile.TemporaryDirectory() as d:
 write_package(Path(d))
 with patch.object(api,'books',BookStore(Path(d))):
  import backend.app.c_demo as demo
  with patch.object(demo,'books',BookStore(Path(d))):
   c=TestClient(app)
   assert c.get('/reader/').status_code==200
   req={'book_id':'zh-99','session_id':'test','kind':'qa','input':{}}
   r=c.post('/api/interact/audio',data={'request':json.dumps(req)},files={'audio':('a.wav',b'RIFF-test','audio/wav')})
   assert r.status_code==200,r.text
   assert r.json()['status']=='fallback'
   assert c.post('/api/interact/audio',data={'request':json.dumps(req)},files={'audio':('a.wav',b'')}).status_code==422
   assert c.post('/api/interact/audio',data={'request':json.dumps(req)},files={'audio':('a.exe',b'bad')}).status_code==415
   print('PASS: reader, audio transport fallback, empty and unsupported uploads')

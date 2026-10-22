"""可选真实 Chromium 验收：RUN_BROWSER_TESTS=1 时启用。"""
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from app.core import parse_workbook
from app.runner import run_plan
from app.ui import DEMO
from tests.test_core import book
from tools.make_sample import sample_rows

class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        data=DEMO.encode('utf8')
        self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self,*a): pass

@unittest.skipUnless(os.environ.get('RUN_BROWSER_TESTS')=='1','需安装 Chromium 并显式启用')
class BrowserTests(unittest.TestCase):
    def test_real_browser(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            base=f'http://127.0.0.1:{server.server_address[1]}'
            plan=parse_workbook(book(sample_rows()),base)
            with tempfile.TemporaryDirectory() as tmp:
                result=run_plan(plan,'e2e',tmp)
                self.assertEqual(result['status'],'COMPLETED',result.get('error'))
                self.assertEqual([c['status'] for c in result['cases']],['PASS','FAIL','ERROR'])
                self.assertEqual(result['cases'][2]['steps'][2]['status'],'BLOCKED')
                self.assertTrue(result['cases'][1]['steps'][3].get('screenshot'))
        finally:
            server.shutdown(); server.server_close(); thread.join()

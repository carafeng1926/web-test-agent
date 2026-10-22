"""仅本机单用户 HTTP 服务。不是可直接暴露公网的生产 Web 服务。"""
import html
import json
import mimetypes
import os
import re
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from app.core import Invalid, MAX_UPLOAD, origin, parse_workbook
from app.reports import build_reports
from app.runner import run_plan
from app.store import Store
from app.ui import PAGE, DEMO

ID = r'[0-9a-f]{32}'
FILES = r'(report\.(?:json|html|xlsx)|case-[1-9][0-9]*-step-[1-9][0-9]*\.png)'

class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, port, base, root):
        super().__init__(('127.0.0.1', port), Handler)
        self.ui_origin = f'http://127.0.0.1:{port}'
        self.base = base
        self.token = secrets.token_urlsafe(32)
        self.store = Store(root)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='browser')
        self.upload_lock = threading.BoundedSemaphore(1)
        self.timeout = 1

    def job(self, rid, plan):
        folder = self.store.root / rid
        try:
            self.store.update(rid, 'RUNNING')
            result = run_plan(plan, rid, folder)
            self.store.update(rid, result['status'], result)
        except Exception:
            result = {'run_id':rid, 'plan_hash':'', 'status':'ERROR',
                      'cases':[], 'error':'任务存储或报告生成异常；请检查磁盘及权限'}
            try:
                build_reports(folder, result)
            except Exception:
                pass
            self.store.update(rid, 'ERROR', result)

class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *_):
        # 不记录 URL、表格内容或输入值。
        pass

    def respond(self, status, body, content='application/json; charset=utf-8', filename=None):
        if isinstance(body, (dict,list)):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Connection', 'close')
        if filename:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def trusted_host(self):
        return self.headers.get('Host') == urlsplit(self.server.ui_origin).netloc

    def authorized(self):
        supplied = self.headers.get('X-Local-Token', '')
        source = self.headers.get('Origin')
        return (self.trusted_host() and
                secrets.compare_digest(supplied, self.server.token) and
                (source is None or source == self.server.ui_origin))

    def body(self, limit):
        if self.headers.get('Transfer-Encoding'):
            raise Invalid('不支持分块上传')
        raw_length = self.headers.get('Content-Length', '')
        if not raw_length.isdecimal():
            raise Invalid('缺少有效的 Content-Length')
        length = int(raw_length)
        if not 0 < length <= limit:
            raise Invalid('请求内容过大或为空')
        data = self.rfile.read(length)
        if len(data) != length:
            raise Invalid('上传不完整')
        return data

    def do_GET(self):
        if not self.trusted_host():
            return self.respond(403, {'error':'只允许本机来源'})
        path = urlsplit(self.path).path
        if path == '/':
            # URL 地址被 JSON 编码再替换为 JS 字符串的内容，防止脚本注入。
            base = json.dumps(self.server.base, ensure_ascii=True)[1:-1]
            base = base.replace('<', '\\u003c').replace('>', '\\u003e')
            page = PAGE.replace('__LOCAL_TOKEN__', self.server.token).replace('__BASE_TEXT__', base)
            return self.respond(200, page, 'text/html; charset=utf-8')
        if path == '/demo':
            return self.respond(200, DEMO, 'text/html; charset=utf-8')
        if not self.authorized():
            return self.respond(403, {'error':'会话失效，请刷新页面'})
        match = re.fullmatch('/api/runs/(' + ID + ')', path)
        if match:
            state = self.server.store.get(match[1])
            return self.respond(200 if state else 404, state or {'error':'任务不存在'})
        match = re.fullmatch('/files/(' + ID + ')/' + FILES, path)
        if match:
            rid, name = match[1], match[2]
            state = self.server.store.get(rid)
            if not state or state['status'] in ('QUEUED','RUNNING'):
                return self.respond(409, {'error':'任务未完成'})
            file = self.server.store.root / rid / name
            if not file.is_file():
                return self.respond(404, {'error':'证据或报告未生成'})
            content = mimetypes.guess_type(name)[0] or 'application/octet-stream'
            return self.respond(200, file.read_bytes(), content, filename=name)
        self.respond(404, {'error':'地址不存在'})

    def do_POST(self):
        if not self.authorized():
            return self.respond(403, {'error':'来源或令牌无效，请刷新页面'})
        try:
            path = urlsplit(self.path).path
            if path == '/api/plans':
                if not self.server.upload_lock.acquire(blocking=False):
                    return self.respond(429, {'error':'正在解析其他表格，请稍后重试'})
                try:
                    plan = parse_workbook(self.body(MAX_UPLOAD), self.server.base)
                    return self.respond(201, self.server.store.plan(plan))
                finally:
                    self.server.upload_lock.release()
            if path == '/api/runs':
                value = json.loads(self.body(4096))
                if not isinstance(value,dict) or set(value) != {'plan_id','hash'}:
                    raise Invalid('必须提供计划编号与哈希')
                if not all(isinstance(v,str) for v in value.values()):
                    raise Invalid('计划参数须为文本')
                rid, plan = self.server.store.start(value['plan_id'], value['hash'], self.server.base)
                if plan is not None:
                    self.server.pool.submit(self.server.job, rid, plan)
                return self.respond(202, {'run_id':rid})
            self.respond(404, {'error':'地址不存在'})
        except Invalid as exc:
            self.respond(400, {'error':str(exc)})
        except (ValueError, TypeError):
            self.respond(400, {'error':'请求格式无效'})
        except Exception:
            self.respond(500, {'error':'服务内部错误，请检查本机磁盘与配置'})

def main():
    port = int(os.environ.get('PORT', '8765'))
    if not 1 <= port <= 65535:
        raise SystemExit('PORT 不合法')
    base = os.environ.get('TEST_BASE_URL', f'http://127.0.0.1:{port}')
    p = urlsplit(base)
    origin(base)
    if p.query or p.fragment:
        raise SystemExit('TEST_BASE_URL 不能带 query/fragment')
    root = Path(os.environ.get('AGENT_DATA_DIR', '.agent-data')).resolve()
    server = Server(port, base, root)
    print('上传界面：' + server.ui_origin, flush=True)
    print('仅限本机单用户；不得将本服务直接暴露公网。', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.pool.shutdown(wait=True)

if __name__ == '__main__':
    main()

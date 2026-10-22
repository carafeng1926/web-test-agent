"""GitHub runner entry point; no venv or persistent upload server needed."""
import argparse
import hashlib
import http.server
import json
import os
import re
import shutil
import threading
import uuid
from pathlib import Path
from contextlib import contextmanager
PLAN_DIR = Path('cloud-plan')
RESULT_DIR = Path('cloud-results')
DEMO_BASE = 'http://127.0.0.1:8877'

def approval_digest(payload):
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(data).hexdigest()

def approved_source(value, root=None):
    root = Path(root or Path.cwd()).resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root / 'examples') or path.suffix.lower() != '.xlsx':
        raise ValueError('Case file must resolve under examples/ and end with .xlsx')
    if not path.is_file():
        raise ValueError('Case file not found; commit the approved XLSX under examples/')
    return path

def prepare():
    from openpyxl import Workbook
    from app.core import HEADERS, parse_workbook, MAX_UPLOAD
    from tools.make_sample import sample_rows
    mode = os.environ.get('TEST_MODE', 'demo')
    if mode not in ('demo', 'custom'):
        raise ValueError('Unsupported mode')
    PLAN_DIR.mkdir(exist_ok=True)
    if mode == 'demo':
        wb = Workbook(); ws = wb.active; ws.append(HEADERS)
        for row in sample_rows()[:4]:
            ws.append(row)
        wb.save(PLAN_DIR / 'source.xlsx')
        base = DEMO_BASE
    else:
        base = os.environ.get('TEST_BASE_URL', '').strip()
        if not base:
            raise ValueError('Set repository variable TEST_BASE_URL before custom mode')
        source = approved_source(os.environ.get('CASE_FILE', 'examples/custom.xlsx'))
        if source.stat().st_size > MAX_UPLOAD:
            raise ValueError('XLSX exceeds upload size limit')
        shutil.copyfile(source, PLAN_DIR / 'source.xlsx')
    plan = parse_workbook((PLAN_DIR / 'source.xlsx').read_bytes(), base)
    payload = {'mode': mode, 'revision': os.environ.get('GITHUB_SHA', 'local'), 'plan': plan}
    token = approval_digest(payload)
    envelope = dict(payload=payload, approval_hash=token)
    (PLAN_DIR / 'plan.json').write_text(json.dumps(envelope, ensure_ascii=False, indent=2),
                                        encoding='utf-8')
    (PLAN_DIR / 'APPROVAL.txt').write_text(
        'Review plan.json and source.xlsx first.\nApproval hash: ' + token + '\n', encoding='utf-8')
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output, 'a', encoding='utf-8') as f:
            f.write('approval_hash=' + token + '\n')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as f:
            f.write('## Plan ready for review\n\n')
            f.write('Download reviewed-plan; inspect plan.json and source.xlsx.\n\n')
            f.write('Approval hash: `' + token + '`\n\n')
            f.write('Run manually again with execute=true and this exact hash.\n')
    print('Approval hash: ' + token)
    return envelope

def verify():
    # stdlib-only: no dependency install required to reject bad approval.
    envelope = json.loads((PLAN_DIR / 'plan.json').read_text(encoding='utf-8'))
    payload = envelope['payload']
    token = approval_digest(payload)
    approved = os.environ.get('APPROVED_PLAN_HASH', '').strip()
    expected = os.environ.get('EXPECTED_PLAN_HASH', '').strip()
    if not re.fullmatch(r'[0-9a-f]{64}', approved):
        raise ValueError('Paste the 64-character hash from the reviewed preview')
    if not token == approved == expected == envelope['approval_hash']:
        raise ValueError('Plan changed or hash mismatch; preview and review again')
    if payload['revision'] != os.environ.get('GITHUB_SHA', 'local'):
        raise ValueError('Source commit changed; review a new plan')
    if payload['mode'] == 'custom':
        if payload['plan']['base_url'] != os.environ.get('TEST_BASE_URL', '').strip():
            raise ValueError('Target differs from repository/environment configuration')
    elif payload['mode'] != 'demo' or payload['plan']['base_url'] != DEMO_BASE:
        raise ValueError('Invalid demo configuration')
    return payload

@contextmanager
def fixture(enabled):
    if not enabled:
        yield
        return
    from app.ui import DEMO
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != '/demo':
                self.send_error(404)
                return
            body = DEMO.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *_):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 8877), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield
    finally:
        server.shutdown(); server.server_close(); thread.join()

def execute():
    payload = verify()
    from app.core import parse_workbook
    from app.runner import run_plan
    plan = payload['plan']
    reparsed = parse_workbook((PLAN_DIR / 'source.xlsx').read_bytes(), plan['base_url'])
    if reparsed != plan:
        raise ValueError('Workbook differs from reviewed plan')
    RESULT_DIR.mkdir(exist_ok=True)
    (RESULT_DIR / 'approval.json').write_text(json.dumps({
        'approval_hash': approval_digest(payload), 'revision': payload['revision'],
        'mode': payload['mode']}, indent=2), encoding='utf-8')
    with fixture(payload['mode'] == 'demo'):
        result = run_plan(plan, uuid.uuid4().hex, RESULT_DIR)
    print('Run status:', result['status'])
    print('Case summary:', json.dumps(result['summary']))
    return 0 if (result['status'] == 'COMPLETED' and result['cases'] and
                 all(c['status'] == 'PASS' for c in result['cases'])) else 1

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['plan', 'verify', 'execute'])
    phase = parser.parse_args().phase
    if phase == 'plan':
        prepare()
        return 0
    if phase == 'verify':
        verify()
        print('Approval verified')
        return 0
    return execute()

if __name__ == '__main__':
    raise SystemExit(main())

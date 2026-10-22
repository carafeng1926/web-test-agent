import json
import sqlite3
import time
import uuid
from pathlib import Path
from app.core import Invalid, digest, require

class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'state.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS plans '
                       '(id TEXT PRIMARY KEY, body TEXT NOT NULL, hash TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS runs '
                       '(id TEXT PRIMARY KEY, plan_id TEXT UNIQUE NOT NULL, '
                       'status TEXT NOT NULL, created REAL NOT NULL, result TEXT)')
            db.execute("UPDATE runs SET status='ERROR', result=? "
                       "WHERE status IN ('QUEUED','RUNNING')",
                       (json.dumps({'status': 'ERROR', 'error': '服务重启，任务中断；请重新上传后运行'}),))

    def connect(self):
        return sqlite3.connect(self.db, timeout=10)

    def plan(self, plan):
        pid, h = uuid.uuid4().hex, digest(plan)
        with self.connect() as db:
            db.execute('INSERT INTO plans VALUES (?,?,?)',
                       (pid, json.dumps(plan, ensure_ascii=False), h))
        return {'plan_id': pid, 'hash': h, 'plan': plan}

    def start(self, pid, h, base):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body, hash FROM plans WHERE id=?', (pid,)).fetchone()
            require(row is not None, '计划不存在')
            require(row[1] == h, '计划哈希不匹配，请重新预览')
            plan = json.loads(row[0])
            require(plan['base_url'] == base, '测试环境已更改，请重新上传')
            old = db.execute('SELECT id FROM runs WHERE plan_id=?', (pid,)).fetchone()
            if old:
                return old[0], None
            count = db.execute("SELECT COUNT(*) FROM runs WHERE status IN ('QUEUED','RUNNING')").fetchone()[0]
            require(count < 5, '队列已满，请等待已有任务完成')
            rid = uuid.uuid4().hex
            db.execute('INSERT INTO runs VALUES (?,?,?,?,?)',
                       (rid, pid, 'QUEUED', time.time(), None))
        return rid, plan

    def update(self, rid, status, result=None):
        with self.connect() as db:
            db.execute('UPDATE runs SET status=?, result=? WHERE id=?',
                       (status, json.dumps(result, ensure_ascii=False) if result else None, rid))

    def get(self, rid):
        with self.connect() as db:
            row = db.execute('SELECT status,result FROM runs WHERE id=?', (rid,)).fetchone()
        if not row:
            return None
        return {'run_id': rid, 'status': row[0],
                'result': json.loads(row[1]) if row[1] else None}

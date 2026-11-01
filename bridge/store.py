import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class Denied(Exception):
    pass


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS probes (
                    id TEXT PRIMARY KEY, expires REAL NOT NULL,
                    question TEXT, answer TEXT, completed INTEGER DEFAULT 0,
                    visited INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS grants (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, question TEXT NOT NULL,
                    scope TEXT NOT NULL, expires REAL NOT NULL, revoked INTEGER DEFAULT 0,
                    request_id TEXT);
                CREATE TABLE IF NOT EXISTS questions (
                    id TEXT PRIMARY KEY, client_id TEXT UNIQUE NOT NULL,
                    grant_id TEXT NOT NULL, task_id TEXT NOT NULL,
                    question TEXT NOT NULL, status TEXT NOT NULL,
                    answer TEXT);
                CREATE TABLE IF NOT EXISTS rules (
                    id TEXT PRIMARY KEY, kind TEXT UNIQUE NOT NULL,
                    instruction TEXT NOT NULL, source TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, client_id TEXT UNIQUE NOT NULL,
                    rule_id TEXT NOT NULL, instruction TEXT NOT NULL,
                    status TEXT NOT NULL, result TEXT);
                CREATE TABLE IF NOT EXISTS probe_deliveries (
                    probe_id TEXT PRIMARY KEY, status TEXT NOT NULL, message_id INTEGER);
                CREATE TABLE IF NOT EXISTS poll_trials (
                    id TEXT PRIMARY KEY, expires REAL NOT NULL,
                    check_count INTEGER NOT NULL DEFAULT 0, last_check REAL,
                    task_code TEXT, result TEXT);
                CREATE TABLE IF NOT EXISTS poll_trial_events (
                    trial_id TEXT, event TEXT, at REAL);
            ''')
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_probe(self, ttl=86400):
        pid = secrets.token_urlsafe(24)
        with self.db() as db:
            db.execute('INSERT INTO probes(id,expires) VALUES (?,?)', (pid, time.time()+ttl))
        return pid

    def probe(self, pid, visit=False):
        with self.db() as db:
            row = db.execute('SELECT * FROM probes WHERE id=?', (pid,)).fetchone()
            if row is None or row['expires'] <= time.time():
                raise Denied('probe_not_available')
            if visit:
                db.execute('UPDATE probes SET visited=visited+1 WHERE id=?', (pid,))
            return dict(row)

    def ask_probe(self, pid, question):
        # A retry returns the same synthetic answer. This route never reads files.
        self.probe(pid)
        with self.db() as db:
            answer = '가상 선호는 실내 과학관입니다. 확인코드: ' + secrets.token_hex(5)
            db.execute('UPDATE probes SET question=?,answer=? WHERE id=? AND answer IS NULL',
                       (question, answer, pid))
        return self.probe(pid)

    def confirm_probe(self, pid, answer):
        row = self.probe(pid)
        if row['answer'] is None or not secrets.compare_digest(row['answer'].encode(), answer.encode()):
            raise Denied('answer_does_not_match')
        with self.db() as db:
            db.execute('UPDATE probes SET completed=1 WHERE id=?', (pid,))
        return self.probe(pid)

    def grant(self, task_id, question, scope, ttl=900):
        gid = secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute('INSERT INTO grants(id,task_id,question,scope,expires) VALUES (?,?,?,?,?)',
                       (gid, task_id, question, scope, time.time()+ttl))
        return gid

    @staticmethod
    def valid_grant(db, gid):
        grant = db.execute('SELECT * FROM grants WHERE id=?', (gid,)).fetchone()
        if grant is None or grant['revoked'] or grant['expires'] <= time.time():
            raise Denied('user_grant_required')
        return grant

    def ask(self, payload):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            grant = self.valid_grant(db, payload['grant_id'])
            if grant['task_id'] != payload['task_id'] or grant['question'] != payload['question']:
                raise Denied('question_outside_grant')
            old = db.execute('SELECT * FROM questions WHERE client_id=?',
                             (payload['client_request_id'],)).fetchone()
            if old:
                if any(old[k] != payload[k] for k in ['grant_id','task_id','question']):
                    raise Denied('idempotency_conflict')
                return dict(old)
            if grant['request_id']:
                raise Denied('grant_already_used')
            rid = secrets.token_urlsafe(24)
            db.execute('INSERT INTO questions VALUES (?,?,?,?,?,?,?)',
                       (rid, payload['client_request_id'], grant['id'], grant['task_id'],
                        grant['question'], 'queued', None))
            db.execute('UPDATE grants SET request_id=? WHERE id=?', (rid, grant['id']))
            return dict(db.execute('SELECT * FROM questions WHERE id=?', (rid,)).fetchone())

    def result(self, rid):
        with self.db() as db:
            row = db.execute('SELECT * FROM questions WHERE id=?', (rid,)).fetchone()
            if not row:
                raise Denied('question_not_available')
            self.valid_grant(db, row['grant_id'])
            return dict(row)

    def answer(self, rid, text):
        # Only the local operator can submit an answer in this first version.
        # No gateway/API/vault access is attempted in the background.
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM questions WHERE id=?', (rid,)).fetchone()
            if row is None:
                raise Denied('question_not_available')
            self.valid_grant(db, row['grant_id'])
            if row['status'] != 'queued':
                raise Denied('question_not_pending')
            db.execute("UPDATE questions SET status='completed',answer=? WHERE id=?", (text,rid))

    def revoke(self, gid):
        with self.db() as db:
            db.execute('UPDATE grants SET revoked=1 WHERE id=?', (gid,))

    def rule(self, kind, instruction, source):
        with self.db() as db:
            old = db.execute('SELECT id FROM rules WHERE kind=?', (kind,)).fetchone()
            rid = old['id'] if old else secrets.token_urlsafe(16)
            db.execute('INSERT OR REPLACE INTO rules VALUES (?,?,?,?,1)',
                       (rid,kind,instruction,source))
        return rid

    def disable_rule(self, rid):
        with self.db() as db:
            db.execute('UPDATE rules SET enabled=0 WHERE id=?', (rid,))

    def task(self, client_id, rule_id, instruction):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            rule = db.execute('SELECT * FROM rules WHERE id=? AND enabled=1', (rule_id,)).fetchone()
            if rule is None:
                raise Denied('active_delegation_rule_required')
            old = db.execute('SELECT * FROM tasks WHERE client_id=?', (client_id,)).fetchone()
            if old:
                if old['rule_id'] != rule_id or old['instruction'] != instruction:
                    raise Denied('idempotency_conflict')
                return dict(old)
            tid = secrets.token_urlsafe(24)
            db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,NULL)',
                       (tid,client_id,rule_id,instruction,'queued'))
            return dict(db.execute('SELECT * FROM tasks WHERE id=?', (tid,)).fetchone())

    def tasks(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM tasks WHERE status IN ('queued','accepted')")]

    def task_update(self, tid, status, result=None):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
            if row is None:
                raise Denied('task_not_available')
            if row['status']==status and row['result']==result:
                return dict(row)
            allowed = {'queued': {'accepted'}, 'accepted': {'completed','needs_user','failed'}}
            if status not in allowed.get(row['status'], set()):
                raise Denied('invalid_task_transition')
            db.execute('UPDATE tasks SET status=?,result=? WHERE id=?',(status,result,tid))
            return dict(db.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone())

    def summary(self):
        with self.db() as db:
            probes=[dict(r) for r in db.execute('SELECT id,expires,visited,completed FROM probes')]
            return {'mode':'synthetic_probe_and_manual_queue', 'probes':probes,
                    'questions':db.execute('SELECT count(*) FROM questions').fetchone()[0],
                    'tasks':db.execute('SELECT count(*) FROM tasks').fetchone()[0]}

    def deliver_probe(self, pid, deliver):
        row=self.probe(pid)
        if row['answer'] is None:raise Denied('probe_answer_required')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM probe_deliveries WHERE probe_id=?',(pid,)).fetchone()
            if old:return dict(old)
            db.execute("INSERT INTO probe_deliveries VALUES (?,'sending',NULL)",(pid,))
        try:
            message_id=deliver(row['answer'])
        except Exception:
            with self.db() as db:
                db.execute("UPDATE probe_deliveries SET status='unknown' WHERE probe_id=?",(pid,))
            raise Denied('delivery_unknown_no_automatic_retry') from None
        with self.db() as db:
            db.execute("UPDATE probe_deliveries SET status='sent',message_id=? WHERE probe_id=?",(message_id,pid))
            return dict(db.execute('SELECT * FROM probe_deliveries WHERE probe_id=?',(pid,)).fetchone())

    def create_poll_trial(self,ttl=1800):
        trial=secrets.token_urlsafe(24)
        with self.db() as db:
            db.execute('INSERT INTO poll_trials(id,expires) VALUES (?,?)',(trial,time.time()+ttl))
        return trial

    def queue_trial_task(self,trial):
        code='PICKLE_BRIDGE_TEST_'+secrets.token_hex(5)
        with self.db() as db:
            db.execute('UPDATE poll_trials SET task_code=? WHERE id=? AND task_code IS NULL',(code,trial))
        return code

    def poll_trial(self,trial,check=False,result=None):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM poll_trials WHERE id=?',(trial,)).fetchone()
            if row is None or row['expires']<=time.time():raise Denied('trial_expired')
            now=time.time()
            if check:
                # A network retry within 60s is not a second scheduled invocation.
                if row['last_check'] is None or now-row['last_check']>=60:
                    db.execute('UPDATE poll_trials SET check_count=check_count+1,last_check=? WHERE id=?',(now,trial))
                db.execute("INSERT INTO poll_trial_events VALUES (?,'poll',?)",(trial,now))
            if result is not None:
                if row['task_code'] is None or not secrets.compare_digest(row['task_code'].encode(),result.encode()):
                    raise Denied('invalid_trial_result')
                db.execute('UPDATE poll_trials SET result=? WHERE id=?',(result,trial))
                db.execute("INSERT INTO poll_trial_events VALUES (?,'result',?)",(trial,now))
            return dict(db.execute('SELECT * FROM poll_trials WHERE id=?',(trial,)).fetchone())

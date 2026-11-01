"""Capability-bound, operator-configured file catalog and at-most-once queue.

Private policy lives in state/attachment_policy.json; no folders are implicit.
No HTTP route serves file contents or accepts filesystem paths.
"""
import hashlib
import fcntl
import os
import json
import re
import secrets
import time
import unicodedata
from pathlib import Path
from .inbox import Inbox
from .store import Denied


def normalized(value):
    return unicodedata.normalize('NFC', str(value))


class Attachments:
    def __init__(self, store):
        self.store = store
        self.inbox = Inbox(store)
        self.policy_path = store.path.parent / 'attachment_policy.json'
        self.favorites_path = store.path.parent / 'file_picker_favorites.json'
        with store.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS attachment_requests (
                id TEXT PRIMARY KEY, channel TEXT NOT NULL, client_id TEXT NOT NULL,
                file_id TEXT NOT NULL, created REAL NOT NULL, status TEXT NOT NULL,
                error TEXT, UNIQUE(channel,client_id))''')

    def catalog(self, channel):
        try:
            policy = json.loads(self.policy_path.read_text())
        except (OSError, ValueError):
            raise Denied('file_sharing_not_configured')
        if (policy.get('enabled') is not True or policy.get('channel_digest') != channel
                or policy.get('destination') != 'pickle_own_chat'):
            raise Denied('file_sharing_not_authorized')
        result = {}
        for rule in policy.get('collections', []):
            configured = Path(rule['root'])
            root = configured.resolve(strict=True)
            if configured != root:
                raise Denied('catalog_root_symlink_not_allowed')
            if not root.is_dir():
                continue
            pattern = re.compile(rule['filename_pattern'])
            extensions = set(rule['extensions'])
            # Explicit relative names avoid requiring directory enumeration in
            # service contexts that may read known files but not list a folder.
            # Every such item still passes realpath/type/content checks below.
            paths = (root / rel for rel in rule['files']) if 'files' in rule else (
                root.rglob('*') if rule.get('recursive') is True else root.iterdir())
            for path in paths:
                if path.is_symlink() or not path.is_file():
                    continue
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(root) or any(p.startswith('.') for p in path.relative_to(root).parts):
                    continue
                if path.suffix.casefold() not in extensions or not pattern.fullmatch(normalized(path.name)):
                    continue
                if not 0 < path.stat().st_size <= policy.get('max_file_bytes',20*1024*1024):
                    continue
                file_id = hashlib.sha256((rule['id']+'\0'+normalized(str(path.relative_to(root)))).encode()).hexdigest()[:24]
                if file_id in result:
                    raise Denied('ambiguous_file_catalog')
                result[file_id] = {'id': file_id, 'name': normalized(path.name),
                                   'collection': rule['id'], 'path': str(resolved)}
        return result

    def listed(self, cap):
        with self.store.db() as db:
            channel = self.inbox.channel(db, cap)['digest']
        return [{k: v for k, v in item.items() if k != 'path'}
                for item in self.catalog(channel).values()]

    def submit(self, cap, client_id, file_id):
        if not isinstance(client_id, str) or not client_id.strip() or len(client_id) > 100:
            raise ValueError('invalid_client_id')
        if not isinstance(file_id, str) or not re.fullmatch('[a-f0-9]{24}', file_id):
            raise ValueError('invalid_file_id')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            channel = self.inbox.channel(db, cap)['digest']
            if file_id not in self.catalog(channel):
                raise Denied('file_not_authorized')
            old = db.execute('SELECT * FROM attachment_requests WHERE channel=? AND client_id=?', (channel, client_id)).fetchone()
            if old:
                if old['file_id'] != file_id:
                    raise Denied('idempotency_conflict')
                return old['id']
            db.execute("UPDATE attachment_requests SET status='expired' WHERE status IN ('draft','queued') AND created<=?", (time.time()-900,))
            if db.execute("SELECT count(*) FROM attachment_requests WHERE channel=? AND created>?", (channel,time.time()-900)).fetchone()[0] >= 10:
                raise Denied('file_request_rate_limit')
            # A second id must not duplicate an unfinished/uncertain delivery.
            if db.execute("SELECT 1 FROM attachment_requests WHERE channel=? AND file_id=? AND status NOT IN ('confirmed','failed','denied','expired')", (channel,file_id)).fetchone():
                raise Denied('file_delivery_already_pending_or_uncertain')
            qid = secrets.token_urlsafe(18)
            db.execute('INSERT INTO attachment_requests VALUES (?,?,?,?,?,?,NULL)',
                       (qid,channel,client_id,file_id,time.time(),'draft'))
            return qid

    def get(self, qid, cap=None):
        with self.store.db() as db:
            row = db.execute('SELECT * FROM attachment_requests WHERE id=?', (qid,)).fetchone()
            if row is None:
                raise Denied('file_request_unavailable')
            self.inbox.channel(db, cap=cap, digest=None if cap else row['channel'])
            if cap and row['channel'] != self.inbox.digest(cap):
                raise Denied('file_request_unavailable')
        return dict(row)

    def resolve(self, qid):
        q = self.get(qid)
        if q['created']+900 <= time.time():
            raise Denied('file_request_expired')
        item = self.catalog(q['channel']).get(q['file_id'])
        if item is None:
            raise Denied('file_permission_revoked_or_missing')
        return item

    def activate(self, cap, qid):
        q = self.get(qid, cap)
        self.resolve(qid)
        with self.store.db() as db:
            db.execute("UPDATE attachment_requests SET status='queued' WHERE id=? AND status='draft'", (qid,))

    def pending(self):
        with self.store.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM attachment_requests WHERE status='queued'")]

    def status(self, qid, status, error=None):
        with self.store.db() as db:
            db.execute('UPDATE attachment_requests SET status=?,error=? WHERE id=?', (status,error,qid))

    def process(self, q, hermes):
        fd=os.open(self.store.path.parent/'delivery.lock',os.O_CREAT|os.O_RDWR,0o600)
        try:
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return False  # No AI or claim while another delivery runs.
            return self._process_locked(q,hermes,fd)
        finally:os.close(fd)

    def _process_locked(self, q, hermes, fd):
        with self.store.db() as db:
            if not db.execute("UPDATE attachment_requests SET status='verifying' WHERE id=? AND status='queued'", (q['id'],)).rowcount:
                return False
        previous=getattr(hermes,'attachment_lock_fd',None)
        hermes.attachment_lock_fd=fd
        try:
            item = self.resolve(q['id'])
            if not hermes.verify_attachment(item['name'], q['id']):
                self.status(q['id'],'denied')
                return True
            self.resolve(q['id'])
            hermes.attach(q['id'])
        except Exception as error:
            with self.store.db() as db:
                current = db.execute('SELECT status FROM attachment_requests WHERE id=?',(q['id'],)).fetchone()[0]
            # An interrupted write is never retried or misreported as a denial.
            if current not in {'opening','attached','sending','sent_unconfirmed','confirmed'}:
                self.status(q['id'],'failed',type(error).__name__)
        finally:hermes.attachment_lock_fd=previous
        return True

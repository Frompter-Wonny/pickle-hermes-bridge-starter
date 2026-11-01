"""Receive-only question channels. Approval is a separate trusted-local action."""
import argparse
import hashlib
import json
import secrets
import time
from pathlib import Path
from .store import Store, Denied


class Inbox:
    def __init__(self, store):
        self.store=store
        with store.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS inbox_channels (
                    digest TEXT PRIMARY KEY, expires REAL NOT NULL, revoked INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS inbox_requests (
                    id TEXT PRIMARY KEY, channel TEXT NOT NULL, client_id TEXT NOT NULL,
                    question TEXT NOT NULL, created REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    request_id TEXT, grant_id TEXT, proof TEXT,
                    UNIQUE(channel,client_id));
                CREATE TABLE IF NOT EXISTS inbox_direct_consents (
                    evidence TEXT PRIMARY KEY, question_id TEXT NOT NULL);
            ''')

    @staticmethod
    def digest(cap):return hashlib.sha256(cap.encode()).hexdigest()

    def create_channel(self, ttl=86400):
        if ttl is not None and not 0<ttl<=604800:raise ValueError('invalid_channel_ttl')
        cap=secrets.token_urlsafe(24)
        with self.store.db() as db:
            db.execute('INSERT INTO inbox_channels(digest,expires) VALUES (?,?)',(self.digest(cap),time.time()+ttl if ttl is not None else 0))
        return cap

    def channel(self, db, cap=None, digest=None):
        row=db.execute('SELECT * FROM inbox_channels WHERE digest=?',(digest or self.digest(cap),)).fetchone()
        if row is None or row['revoked'] or (row['expires']!=0 and row['expires']<=time.time()):raise Denied('channel_not_available')
        return row

    def submit(self, cap, client_id, question, staged=False):
        if not isinstance(client_id,str) or not client_id.strip() or len(client_id)>100:
            raise ValueError('invalid_client_id')
        if not isinstance(question,str) or not question.strip() or len(question)>1200:
            raise ValueError('invalid_question')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE');channel=self.channel(db,cap)
            old=db.execute('SELECT * FROM inbox_requests WHERE channel=? AND client_id=?',(channel['digest'],client_id)).fetchone()
            if old:
                if old['question']!=question:raise Denied('idempotency_conflict')
                return old['id']
            pending=db.execute("SELECT count(*) FROM inbox_requests WHERE channel=? AND created>? AND (status IN ('draft','pending') OR (status='approved' AND request_id IN (SELECT id FROM questions WHERE status='queued')))",(channel['digest'],time.time()-900)).fetchone()[0]
            if pending>=3:raise Denied('too_many_pending_questions')
            qid=secrets.token_urlsafe(18)
            db.execute('INSERT INTO inbox_requests(id,channel,client_id,question,created) VALUES (?,?,?,?,?)',
                       (qid,channel['digest'],client_id,question,time.time()))
            if staged:db.execute("UPDATE inbox_requests SET status='draft' WHERE id=?",(qid,))
            return qid

    def activate(self,cap,qid):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE');channel=self.channel(db,cap)
            q=db.execute('SELECT * FROM inbox_requests WHERE id=? AND channel=?',(qid,channel['digest'])).fetchone()
            if q is None or q['created']+900<=time.time():raise Denied('question_expired')
            if q['status']=='pending':return
            if q['status']!='draft':raise Denied('question_not_draft')
            db.execute("UPDATE inbox_requests SET status='pending' WHERE id=?",(qid,))

    def approve(self, qid, proof, ttl=900,consent_key=None):
        if not proof.strip():raise ValueError('verified_user_proof_required')
        if not 0<ttl<=900:raise ValueError('question_grant_must_expire_within_15_minutes')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            q=db.execute('SELECT * FROM inbox_requests WHERE id=?',(qid,)).fetchone()
            if q is None or q['status']!='pending':raise Denied('question_not_pending')
            channel=self.channel(db,digest=q['channel'])
            if q['created']+900<=time.time():raise Denied('question_expired')
            if consent_key:
                if db.execute('SELECT 1 FROM inbox_direct_consents WHERE evidence=?',(consent_key,)).fetchone():
                    raise Denied('direct_user_command_already_consumed')
                db.execute('INSERT INTO inbox_direct_consents VALUES (?,?)',(consent_key,qid))
            gid=secrets.token_urlsafe(32);rid=secrets.token_urlsafe(24)
            expires=min(time.time()+ttl,channel['expires'] or time.time()+ttl)
            db.execute('INSERT INTO grants VALUES (?,?,?,?,?,0,?)',
                       (gid,qid,q['question'],'Answer only this question for Pickle. No raw notes or unrelated user information.',expires,rid))
            db.execute('INSERT INTO questions VALUES (?,?,?,?,?,?,NULL)',
                       (rid,'inbox:'+qid,gid,qid,q['question'],'queued'))
            db.execute("UPDATE inbox_requests SET status='approved',request_id=?,grant_id=?,proof=? WHERE id=?",(rid,gid,proof,qid))
            return rid

    def pending(self):
        with self.store.db() as db:
            return [dict(r) for r in db.execute("SELECT q.id,q.question,q.created FROM inbox_requests q JOIN inbox_channels c ON c.digest=q.channel WHERE q.status='pending' AND q.created>? AND c.revoked=0 AND (c.expires=0 OR c.expires>?)",(time.time()-900,time.time()))]

    def close_channel(self,cap):
        digest=self.digest(cap)
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE inbox_channels SET revoked=1 WHERE digest=?',(digest,))
            db.execute('UPDATE grants SET revoked=1 WHERE id IN (SELECT grant_id FROM inbox_requests WHERE channel=?)',(digest,))

    def result(self, cap, qid):
        with self.store.db() as db:
            channel=self.channel(db,cap)
            q=db.execute('SELECT * FROM inbox_requests WHERE id=? AND channel=?',(qid,channel['digest'])).fetchone()
            if q is None:raise Denied('question_not_available')
            if q['status'] in {'pending','draft'}:
                return {'status':'expired' if q['created']+900<=time.time() else 'awaiting_user_authorization'}
            if q['status']=='denied':return {'status':'denied'}
            self.store.valid_grant(db,q['grant_id'])
            answer=db.execute('SELECT status,answer FROM questions WHERE id=?',(q['request_id'],)).fetchone()
            return dict(answer)

    def deny(self, qid):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            q=db.execute('SELECT grant_id FROM inbox_requests WHERE id=?',(qid,)).fetchone()
            if q and q['grant_id']:db.execute('UPDATE grants SET revoked=1 WHERE id=?',(q['grant_id'],))
            db.execute("UPDATE inbox_requests SET status='denied' WHERE id=?",(qid,))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state',default=str(Path(__file__).resolve().parents[1]/'.runtime'))
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('create-channel');sub.add_parser('pending')
    approve=sub.add_parser('approve');approve.add_argument('id');approve.add_argument('--proof',required=True)
    deny=sub.add_parser('deny');deny.add_argument('id')
    close=sub.add_parser('close-channel');close.add_argument('capability')
    args=p.parse_args();state=Path(args.state);inbox=Inbox(Store(state/'bridge.sqlite3'))
    if args.command=='create-channel':
        active=json.loads((state/'active_probe.json').read_text())
        cap=inbox.create_channel();print(active['public_url'].split('/probe/')[0]+'/inbox/'+cap)
    elif args.command=='pending':print(json.dumps(inbox.pending(),ensure_ascii=False))
    elif args.command=='approve':print(inbox.approve(args.id,args.proof))
    elif args.command=='deny':inbox.deny(args.id);print('Denied.')
    elif args.command=='close-channel':inbox.close_channel(args.capability);print('Closed.')


if __name__=='__main__':main()

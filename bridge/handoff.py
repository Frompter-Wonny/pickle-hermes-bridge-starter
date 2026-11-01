"""Explicitly published, expiring task capabilities. No file or vault access."""
import argparse
import hashlib
import json
import secrets
import os
import time
from pathlib import Path
from urllib.request import urlopen
from .store import Denied, Store


class Handoffs:
    def __init__(self, store):
        self.store=store
        with store.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS handoffs (
                digest TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                instruction TEXT NOT NULL, source TEXT NOT NULL,
                expires REAL NOT NULL, revoked INTEGER DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending', result TEXT)''')

    @staticmethod
    def digest(cap):
        return hashlib.sha256(cap.encode()).hexdigest()

    def create(self, instruction, source, request_id, ttl=3600):
        if not instruction.strip() or not source.strip() or not request_id.strip():
            raise ValueError('instruction_source_and_request_id_required')
        if len(instruction)>6000 or not 0<ttl<=86400:
            raise ValueError('invalid_instruction_or_ttl')
        cap=secrets.token_urlsafe(24)
        with self.store.db() as db:
            # Reusing a request id must never create a duplicate executable task.
            if db.execute('SELECT 1 FROM handoffs WHERE request_id=?',(request_id,)).fetchone():
                raise Denied('request_id_already_published')
            db.execute('INSERT INTO handoffs(digest,request_id,instruction,source,expires) VALUES (?,?,?,?,?)',
                       (self.digest(cap),request_id,instruction,source,time.time()+ttl))
        return cap

    def get(self, cap):
        with self.store.db() as db:
            row=db.execute('SELECT * FROM handoffs WHERE digest=?',(self.digest(cap),)).fetchone()
            if row is None or row['revoked'] or row['expires']<=time.time():
                raise Denied('handoff_not_available')
            # Operator provenance and local IDs never leave the local store.
            return {k:row[k] for k in ['instruction','expires','status','result']}

    def complete(self, cap, status, result):
        if status not in {'completed','needs_user','failed'} or not isinstance(result,str) or not result.strip() or len(result)>6000:
            raise ValueError('invalid_result')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM handoffs WHERE digest=?',(self.digest(cap),)).fetchone()
            if row is None or row['revoked'] or row['expires']<=time.time():
                raise Denied('handoff_not_available')
            if row['status']==status and row['result']==result:
                return {'status':'recorded','duplicate':True}
            if row['status'] in {'completed','failed'}:
                raise Denied('result_already_recorded')
            db.execute('UPDATE handoffs SET status=?,result=? WHERE digest=?',(status,result,self.digest(cap)))
        return {'status':'recorded','duplicate':False}

    def revoke(self, cap):
        with self.store.db() as db:
            db.execute('UPDATE handoffs SET revoked=1 WHERE digest=?',(self.digest(cap),))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',default=str(Path(__file__).resolve().parents[1]/'.runtime'))
    sub=parser.add_subparsers(dest='command',required=True)
    create=sub.add_parser('create')
    create.add_argument('--instruction-file',required=True)
    create.add_argument('--source',required=True,help='Actual trusted user instruction provenance, not a Pickle claim.')
    create.add_argument('--request-id',required=True)
    create.add_argument('--ttl',type=int,default=3600)
    create.add_argument('--output-file',help='Save capability JSON in a new owner-only file instead of printing it.')
    for cmd in ['status','revoke']:
        p=sub.add_parser(cmd);p.add_argument('capability')
    args=parser.parse_args(); state=Path(args.state)
    h=Handoffs(Store(state/'bridge.sqlite3'))
    if args.command=='create':
        active=json.loads((state/'active_probe.json').read_text())
        expiry=active.get('session_expires_at',0)
        if expiry is not None and expiry<=time.time():
            raise SystemExit('No live session. Start the explicitly enabled handoff server first.')
        # A live capability listener is opt-in; a probe tunnel alone is insufficient.
        with urlopen('http://127.0.0.1:8766/health',timeout=3) as response:
            enabled=json.load(response).get('handoffs_enabled',False)
        if not enabled:
            raise SystemExit('Task handoff listener is not enabled.')
        output=Path(args.output_file) if args.output_file else None
        fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600) if output else None
        published=False
        try:
            cap=h.create(Path(args.instruction_file).read_text(),args.source,args.request_id,args.ttl);published=True
            origin=active['public_url'].split('/probe/')[0]
            payload={'url':origin+'/work/'+cap,'capability':cap}
            if fd is not None:
                with os.fdopen(fd,'w') as file:fd=None;json.dump(payload,file,ensure_ascii=False)
                print(json.dumps({'saved':str(output)}))
            else:print(json.dumps(payload,ensure_ascii=False))
        finally:
            if fd is not None:os.close(fd)
            if output and not published:output.unlink(missing_ok=True)
    elif args.command=='status':
        print(json.dumps(h.get(args.capability),ensure_ascii=False))
    elif args.command=='revoke':
        h.revoke(args.capability);print('Revoked.')


if __name__=='__main__':
    main()

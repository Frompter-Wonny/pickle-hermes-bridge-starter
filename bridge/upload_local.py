"""Trusted operator delivery of one already-authorized staged attachment.

No public route, permanent file grant, arbitrary click, or general tool access.
"""
import argparse
import fcntl
import hashlib
import json
import os
import stat
import time
from pathlib import Path
from .store import Store, Denied

ROOT=Path(__file__).resolve().parents[1]
STAGING=Path.home()/'PickleUploadStaging'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def private_json(path):
    path=Path(path).expanduser()
    info=path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid()
            or stat.S_IMODE(info.st_mode)&0o077):raise Denied('private_owner_file_required')
    return json.loads(path.read_text())


def receipt(path,root=STAGING):
    path=Path(path).expanduser()
    data=private_json(path);root=Path(root).resolve(strict=True)
    actual=path.resolve(strict=True)
    if (path!=actual or actual.name!='upload-receipt.json'
            or actual.parent.parent!=root or not actual.parent.name.startswith('upload-')):
        raise Denied('staging_receipt_outside_upload_root')
    target=Path(data['attachment_path'])
    if (data.get('status')!='staged_only' or target.resolve(strict=True)!=target
            or target.parent!=actual.parent or target==actual or not target.is_file()):
        raise Denied('exact_staged_attachment_required')
    info=target.stat()
    if (info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077
            or info.st_size!=data['bytes'] or sha(target)!=data['sha256']):
        raise Denied('staged_attachment_changed')
    return data


def prepare(receipt_file,request_id,source_file,output_file,root=STAGING,root_volume_label=None):
    # A local operator invokes this only after an actual user instruction.
    # A receipt or a file's contents cannot supply the authorization.
    if not isinstance(request_id,str) or not request_id.strip() or len(request_id)>200:
        raise ValueError('specific_request_id_required')
    if not isinstance(root_volume_label,str) or not root_volume_label.strip():
        raise ValueError('observed_root_volume_label_required')
    source_path=Path(source_file)
    info=source_path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid()
            or stat.S_IMODE(info.st_mode)&0o077):raise Denied('private_user_instruction_file_required')
    source=source_path.read_text().strip()
    if not source or len(source)>4000:raise ValueError('actual_user_instruction_source_required')
    data=receipt(receipt_file,root)
    task={'request_id':request_id,'destination':'pickle_own_chat','user_instruction_source':source,
          'receipt_path':str(Path(receipt_file).resolve()),'receipt_sha256':sha(receipt_file),
          'attachment_sha256':data['sha256'],'created':time.time(),'expires':time.time()+900,
          'root_volume_label':root_volume_label}
    fd=os.open(output_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump(task,f,ensure_ascii=False)
    return task


def lookup_receipt(store,receipt_file,root=STAGING):
    data=receipt(receipt_file,root)
    with store.db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='local_attachment_deliveries'").fetchone():
            return []
        return [dict(r) for r in db.execute('SELECT status,created FROM local_attachment_deliveries WHERE sha256=? ORDER BY created DESC LIMIT 3',(data['sha256'],))]


class LocalUpload:
    def __init__(self,store,task_file,root=STAGING):
        self.store=store;self.task_file=Path(task_file);self.root=Path(root)
        self.task=private_json(task_file)
        self.qid=hashlib.sha256(self.task['request_id'].encode()).hexdigest()
        self.favorites_path=store.path.parent/'file_picker_favorites.json'
        self.require_favorite=True
        with store.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS local_attachment_deliveries (
                id TEXT PRIMARY KEY,binding TEXT NOT NULL,sha256 TEXT NOT NULL,
                status TEXT NOT NULL,created REAL NOT NULL,error TEXT,proof TEXT)''')

    def resolve(self,qid):
        t=private_json(self.task_file)
        if t!=self.task or qid!=self.qid or t.get('destination')!='pickle_own_chat':
            raise Denied('local_upload_task_changed')
        if not isinstance(t.get('root_volume_label'),str) or not t['root_volume_label'].strip():
            raise Denied('observed_root_volume_label_required')
        if (not isinstance(t.get('user_instruction_source'),str) or not t['user_instruction_source'].strip()
                or not t['created']<=time.time()<t['expires']<=t['created']+901):
            raise Denied('local_upload_authorization_expired_or_missing')
        if sha(t['receipt_path'])!=t['receipt_sha256']:raise Denied('staging_receipt_changed')
        data=receipt(t['receipt_path'],self.root)
        if data['sha256']!=t['attachment_sha256']:raise Denied('authorized_file_changed')
        return {'path':data['attachment_path'],'name':Path(data['attachment_path']).name}

    def begin(self):
        self.resolve(self.qid)
        binding=hashlib.sha256(json.dumps(self.task,sort_keys=True).encode()).hexdigest()
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM local_attachment_deliveries WHERE id=?',(self.qid,)).fetchone()
            if old:raise Denied('local_upload_already_attempted_check_status')
            if db.execute("SELECT 1 FROM local_attachment_deliveries WHERE sha256=? AND status IN ('running','opening','attached','sending','sent_unconfirmed')",
                          (self.task['attachment_sha256'],)).fetchone():
                raise Denied('same_attachment_pending_or_uncertain')
            db.execute('INSERT INTO local_attachment_deliveries VALUES (?,?,?,?,?,NULL,NULL)',
                       (self.qid,binding,self.task['attachment_sha256'],'running',time.time()))

    def status(self,qid,status,error=None):
        if qid!=self.qid:raise Denied('wrong_local_upload_request')
        with self.store.db() as db:
            db.execute('UPDATE local_attachment_deliveries SET status=?,error=? WHERE id=?',(status,error,qid))

    def result(self):
        with self.store.db() as db:
            row=db.execute('SELECT status,error FROM local_attachment_deliveries WHERE id=?',(self.qid,)).fetchone()
        return dict(row) if row else {'status':'not_started','error':None}

    def confirm(self,proof_file):
        path=Path(proof_file);info=path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid()
                or stat.S_IMODE(info.st_mode)&0o077):raise Denied('private_receipt_observation_required')
        proof=path.read_text().strip()
        if not proof or len(proof)>2000:raise ValueError('actual_receipt_observation_required')
        with self.store.db() as db:
            cursor=db.execute("UPDATE local_attachment_deliveries SET status='confirmed',proof=? WHERE id=? AND status IN ('sending','sent_unconfirmed')",(proof,self.qid))
            if not cursor.rowcount:raise Denied('sent_attachment_required_before_confirmation')

    def send(self,backend,approve,front_pid):
        from .attachment_driver import Uploader
        self.begin()
        try:
            u=Uploader(backend,approve,front_pid,self,self.qid,root_volume_label=self.task['root_volume_label'])
            return u.run()
        except Exception as error:
            if self.result()['status'] not in {'opening','attached','sending','sent_unconfirmed','confirmed'}:
                self.status(self.qid,'failed_before_upload',type(error).__name__)
            raise


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state',default=str(ROOT/'.runtime'))
    sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('prepare')
    for key in ['receipt-file','request-id','source-file','output-file','root-volume-label']:a.add_argument('--'+key,required=True)
    for name in ['send','status']:
        a=sub.add_parser(name);a.add_argument('--task-file',required=True)
    a=sub.add_parser('confirm');a.add_argument('--task-file',required=True);a.add_argument('--proof-file',required=True)
    a=sub.add_parser('lookup');a.add_argument('--receipt-file',required=True)
    args=p.parse_args()
    if args.command=='prepare':
        prepare(args.receipt_file,args.request_id,args.source_file,args.output_file,root_volume_label=args.root_volume_label)
        print(json.dumps({'status':'authorized_task_prepared','transmitted':False}));return
    state=Path(args.state);store=Store(state/'bridge.sqlite3')
    if args.command=='lookup':print(json.dumps({'previous_deliveries':lookup_receipt(store,args.receipt_file)}));return
    delivery=LocalUpload(store,args.task_file)
    if args.command=='status':print(json.dumps(delivery.result()));return
    if args.command=='confirm':
        delivery.confirm(args.proof_file);print(json.dumps(delivery.result()));return
    fd=os.open(state/'delivery.lock',os.O_CREAT|os.O_RDWR,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        from .attachment_run import approve_action
        from .window_recovery import frontmost_pid
        from tools.computer_use.cua_backend import CuaDriverBackend
        from .screen_tools import name
        from bridge.backend_compat import adapt_backend
        backend=adapt_backend(CuaDriverBackend(permission_mode='standard'))
        if not any(name(w.get('app_name')) in {'pickle','피클'} and name(w.get('title')) in {'pickle','피클'}
                   and not w.get('off_screen') for w in backend.list_windows()):
            from .window_recovery import optional_recovery
            from .delivery_driver import initialize_startup_composer
            optional_recovery(ROOT,lambda pid:initialize_startup_composer(backend,pid))
        delivery.send(backend,approve_action,frontmost_pid)
        print(json.dumps(delivery.result()))
    finally:os.close(fd)


if __name__=='__main__':main()

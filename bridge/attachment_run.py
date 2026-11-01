"""One claimed file request, fixed computer-use actions, shared delivery lock."""
import fcntl
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(Path(os.environ.get('PICKLE_BRIDGE_HERMES_ROOT',str(Path.home()/'.hermes/hermes-agent')))))

def approve_action(action,args):
    """Approve only the fixed uploader's exact action, restoring the callback."""
    from tools.computer_use import tool
    from bridge.store import Denied
    previous=tool._approval_callback
    try:
        tool.set_approval_callback(lambda a,received,summary:'approve_once' if a==action and received==args else 'deny')
        if tool._request_approval(action,args):raise Denied('file_action_not_authorized')
    finally:tool.set_approval_callback(previous)

def main():
    from bridge.attachments import Attachments
    from bridge.attachment_driver import Uploader
    from bridge.store import Store,Denied
    from bridge.window_recovery import frontmost_pid
    from tools.computer_use import tool
    from tools.computer_use.cua_backend import CuaDriverBackend
    qid=sys.argv[1];state=ROOT/'.runtime'
    requests=Attachments(Store(state/'bridge.sqlite3'))
    if requests.get(qid)['status']!='verifying':raise Denied('claimed_file_request_required')
    inherited=os.environ.get('PICKLE_BRIDGE_ATTACHMENT_LOCK_FD')
    fd=int(inherited) if inherited is not None else os.open(state/'delivery.lock',os.O_CREAT|os.O_RDWR,0o600)
    actual=os.stat(state/'delivery.lock');received=os.fstat(fd)
    if (actual.st_dev,actual.st_ino)!=(received.st_dev,received.st_ino):raise Denied('delivery_lock_identity_mismatch')
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        backend=CuaDriverBackend(permission_mode='standard')
        Uploader(backend,approve_action,frontmost_pid,requests,qid).run()
    finally:os.close(fd)

if __name__=='__main__':main()

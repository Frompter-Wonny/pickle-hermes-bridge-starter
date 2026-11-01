"""Run an expiring public probe; optionally enable explicit task capabilities.

No private queue or vault is exposed.
"""
import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen
from .tunnel import settings,command,ngrok_ready_origin


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--seconds',type=int,default=7200)
    p.add_argument('--handoffs',action='store_true')
    args=p.parse_args()
    root=Path(__file__).resolve().parents[1]; state=root/'.runtime'
    tunnel=settings(state)
    if args.seconds==0 and (not args.handoffs or tunnel['provider']!='ngrok'):
        raise ValueError('unlimited_sessions_require_explicit_ngrok_handoffs')
    lock_fd=os.open(state/'session.lock',os.O_CREAT|os.O_RDWR,0o600)
    try:fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock_fd);raise SystemExit('Another verified bridge supervisor owns the listener.')
    current=json.loads((state/'active_probe.json').read_text())
    for key in ['public_url','session_expires_at','tunnel_provider']:current.pop(key,None)
    (state/'active_probe.json').write_text(json.dumps(current))
    (state/'probe_session.pid').write_text(str(os.getpid()))
    children=[]; stop=False

    def halt(*_):
        nonlocal stop
        stop=True

    signal.signal(signal.SIGTERM,halt);signal.signal(signal.SIGINT,halt)
    deadline=time.time()+args.seconds if args.seconds else None
    try:
        with (state/'server.log').open('a') as server_log, (state/'tunnel.log').open('w') as tunnel_log, (state/'questions.log').open('a') as questions_log:
            server_args=[sys.executable,'-m','bridge.server','--port','8766']
            if args.handoffs:server_args.append('--handoffs')
            if (state/'telegram_probe.json').exists():server_args.append('--telegram-probe')
            children.append(subprocess.Popen(server_args,
                cwd=root,stdout=server_log,stderr=server_log))
            for _ in range(30):
                if children[0].poll() is not None: raise RuntimeError('Probe server exited')
                try:
                    with urlopen('http://127.0.0.1:8766/health',timeout=1) as r:
                        if json.load(r).get('mode') in {'probe_only','capability_tasks'}: break
                except OSError: time.sleep(.2)
            else: raise RuntimeError('Probe server health timeout')
            if args.handoffs:
                children.append(subprocess.Popen([sys.executable,'-m','bridge.question_worker'],
                    cwd=root,stdout=questions_log,stderr=questions_log))
            children.append(subprocess.Popen(command(state,tunnel),
                cwd=root,stdout=tunnel_log,stderr=tunnel_log))
            (state/'probe_session.pid').write_text(str(os.getpid()))
            while not stop and (deadline is None or time.time()<deadline):
                if any(c.poll() is not None for c in children):
                    raise RuntimeError('Probe child exited; see private runtime logs')
                current=json.loads((state/'active_probe.json').read_text())
                if 'public_url' not in current:
                    if tunnel['provider']=='ngrok':origin=ngrok_ready_origin(tunnel)
                    else:
                        match=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', (state/'tunnel.log').read_text())
                        origin=match.group() if match else None
                    if origin:
                        current.update(public_url=origin+current['probe_path'],
                                       session_expires_at=deadline,tunnel_provider=tunnel['provider'])
                        (state/'active_probe.json').write_text(json.dumps(current))
                        print('Task tunnel ready. '+('Auto-stop enabled.' if deadline else 'Explicit persistent ngrok session.'),flush=True)
                time.sleep(.5)
    finally:
        for c in reversed(children):
            if c.poll() is None:
                c.terminate()
                try:c.wait(timeout=5)
                except subprocess.TimeoutExpired:c.kill();c.wait()
        os.close(lock_fd)


if __name__=='__main__':
    main()

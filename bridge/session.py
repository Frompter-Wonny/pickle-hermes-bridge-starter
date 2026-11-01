"""Start an expiring task listener on demand; no LLM polling or login startup."""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen
from .tunnel import settings

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'.runtime'


def live():
    try:
        pid=int((STATE/'probe_session.pid').read_text())
        command=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True,check=True).stdout
        if '-m bridge.probe_session' not in command:return None
        active=json.loads((STATE/'active_probe.json').read_text())
        expiry=active.get('session_expires_at',0)
        if expiry is not None and expiry<=time.time():return None
        with urlopen('http://127.0.0.1:8766/health',timeout=2) as r:health=json.load(r)
        return {'pid':pid,'expires':active['session_expires_at'],
                'origin':active['public_url'].split('/probe/')[0],
                'handoffs_enabled':health.get('handoffs_enabled',False),
                'tunnel_provider':active.get('tunnel_provider','cloudflare')}
    except (OSError,ValueError,KeyError,subprocess.CalledProcessError):return None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['start','status','stop'])
    p.add_argument('--seconds',type=int,default=3600)
    args=p.parse_args();current=live()
    if args.command=='status':
        print(json.dumps(current or {'running':False}));return
    if args.command=='stop':
        managed=subprocess.run(['launchctl','print',f'gui/{os.getuid()}/com.picklehermes.bridge'],capture_output=True,text=True)
        if managed.returncode==0:
            raise SystemExit('Managed by launchd. Use python3 -m bridge.service stop to stop and disable automatic restart.')
        if current:
            os.kill(current['pid'],signal.SIGTERM)
            for _ in range(60):
                status=subprocess.run(['ps','-p',str(current['pid']),'-o','stat='],capture_output=True,text=True)
                if status.returncode or status.stdout.strip().startswith('Z'):break
                time.sleep(.1)
        print('Stop requested.' if current else 'No verified live session.');return
    if current:
        if not current['handoffs_enabled']:
            raise SystemExit('Existing probe session is active; stop it explicitly before enabling tasks.')
        desired=settings(STATE)
        if current['tunnel_provider']!=desired['provider'] or (desired['provider']=='ngrok' and current['origin']!=desired['origin']):
            raise SystemExit('Existing tunnel differs from configured provider; stop it explicitly before switching.')
        print(json.dumps(current));return
    if args.seconds==0:
        if settings(STATE)['provider']!='ngrok':raise SystemExit('Persistent sessions require explicitly configured ngrok.')
    elif not 60<=args.seconds<=86400:raise SystemExit('Session duration must be 0 for ngrok, or 60..86400 seconds.')
    # Refuse to start another listener while an old supervisor still exists.
    pidfile=STATE/'probe_session.pid'
    if pidfile.exists():
        pid=int(pidfile.read_text())
        command=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True).stdout
        if '-m bridge.probe_session' in command:
            raise SystemExit('Supervisor exists but is not healthy. Inspect private logs; not replaced automatically.')
    active=json.loads((STATE/'active_probe.json').read_text())
    active.pop('public_url',None);active.pop('session_expires_at',None)
    (STATE/'active_probe.json').write_text(json.dumps(active))
    with (STATE/'supervisor.log').open('a') as log:
        child=subprocess.Popen([sys.executable,'-m','bridge.probe_session','--handoffs','--seconds',str(args.seconds)],
            cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
    for _ in range(80):
        if child.poll() is not None:raise SystemExit('Session exited; inspect private logs.')
        current=live()
        if current:
            print(json.dumps(current));return
        time.sleep(.25)
    raise SystemExit('Tunnel startup is still pending; use status before retrying. Do not create a duplicate session.')


if __name__=='__main__':main()

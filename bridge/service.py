"""Manage only the operator-authorized per-user pickle_bridge launch agent."""
import argparse
import json
import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path
from .session import ROOT,STATE,live
from .tunnel import settings

LABEL='com.picklehermes.bridge'
INSTALL_ROOT=Path.home()/'Library/Application Support/PickleHermesBridge'
DEST=Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
TARGET=f'gui/{os.getuid()}/{LABEL}'


def definition():
    runtime_root=INSTALL_ROOT if (INSTALL_ROOT/'bridge/probe_session.py').exists() else ROOT
    state=runtime_root/'.runtime'
    env={'PATH':str(Path.home()/'.local/bin')+':/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'}
    if os.environ.get('PICKLE_BRIDGE_HERMES_ROOT'):env['PICKLE_BRIDGE_HERMES_ROOT']=os.environ['PICKLE_BRIDGE_HERMES_ROOT']
    return {'Label':LABEL,'ProgramArguments':[sys.executable,'-m','bridge.probe_session','--handoffs','--seconds','0'],
            'WorkingDirectory':str(runtime_root),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':30,
            'ProcessType':'Background','ExitTimeOut':15,'Umask':0o077,
            'EnvironmentVariables':env,
            'StandardOutPath':str(state/'service.stdout.log'),'StandardErrorPath':str(state/'service.stderr.log')}


def control(*args,check=True):
    result=subprocess.run(['launchctl',*args],capture_output=True,text=True)
    if check and result.returncode:raise SystemExit('launchctl action failed; inspect private service logs. No security settings were changed.')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','install','start','stop','status'])
    args=parser.parse_args()
    if args.command=='prepare':
        path=ROOT/'deploy'/f'{LABEL}.plist';path.parent.mkdir(exist_ok=True)
        path.write_bytes(plistlib.dumps(definition()));print(str(path));return
    if args.command=='status':
        state=control('print',TARGET,check=False)
        print(json.dumps({'installed':DEST.exists(),'loaded':state.returncode==0,'session':live()}));return
    if args.command=='stop':
        previous=live()
        control('bootout',TARGET,check=False)
        control('disable',TARGET)
        for _ in range(80):
            previous_exited=True
            if previous:
                status=subprocess.run(['ps','-p',str(previous['pid']),'-o','stat='],capture_output=True,text=True)
                previous_exited=bool(status.returncode or status.stdout.strip().startswith('Z'))
            if previous_exited and control('print',TARGET,check=False).returncode:break
            time.sleep(.25)
        else:raise SystemExit('Bridge is still shutting down; wait before starting a replacement.')
        print('Bridge service stopped and disabled for automatic launch.');return
    if settings(STATE)['provider']!='ngrok' or not (STATE/'ngrok.yml').exists():
        raise SystemExit('Explicit ngrok settings and private auth configuration are required.')
    if args.command=='install':
        DEST.parent.mkdir(parents=True,exist_ok=True)
        DEST.write_bytes(plistlib.dumps(definition()));DEST.chmod(0o600)
    elif not DEST.exists():raise SystemExit('Service is not installed.')
    control('enable',TARGET)
    if control('print',TARGET,check=False).returncode:
        control('bootstrap',f'gui/{os.getuid()}',str(DEST))
    else:control('kickstart',TARGET)
    print('Authorized bridge launch agent started. Use status to verify readiness.')


if __name__=='__main__':main()

"""Prepare a short Pickle setup link after a tunnel changes or a chat resets."""
import argparse
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit
from .session import live,ROOT,STATE
from .store import Store,Denied
from .inbox import Inbox
from .handoff import Handoffs
from .permission_phrases import load as permission_rules


def private_json(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,ensure_ascii=False)
    path.chmod(0o600)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--force',action='store_true',help='Prepare another setup instruction even if one is already applied.')
    args=p.parse_args();session=live()
    if not session or not session['handoffs_enabled']:raise SystemExit('Start the task session first: python3 -m bridge.session start')
    rules=permission_rules(STATE)
    store=Store(STATE/'bridge.sqlite3');inbox=Inbox(store);handoffs=Handoffs(store)
    channel_file=STATE/'question_channel.txt';cap=None
    if channel_file.exists():
        candidate=urlsplit(channel_file.read_text().strip()).path.rsplit('/',1)[-1]
        try:
            with store.db() as db:existing=inbox.channel(db,candidate)
            if session['expires'] is not None or existing['expires']==0:cap=candidate
        except Denied:pass
    if cap is None:cap=inbox.create_channel(ttl=None if session['expires'] is None else 86400)
    channel=session['origin']+'/inbox/'+cap
    channel_file.write_text(channel);channel_file.chmod(0o600)
    instruction=(ROOT/'bridge/pickle_protocol.txt').read_text().replace('{{INBOX_URL}}',channel).replace('{{QUESTION_PERMISSION_RULES}}',json.dumps(rules,ensure_ascii=False))
    previous_file=STATE/'onboarding.json'
    if previous_file.exists() and not args.force:
        previous=json.loads(previous_file.read_text())
        try:
            task=handoffs.get(previous['capability'])
            if previous['url'].startswith(session['origin']+'/work/') and task['status']=='completed' and task['instruction']==instruction:
                print(json.dumps({'already_applied':True,'setup_url':previous['url']}));return
        except (Denied,KeyError):pass
    work=handoffs.create(instruction,'Operator-configured Pickle question-permission connection',
                         'configure:'+str(time.time_ns()))
    url=session['origin']+'/work/'+work
    private_json(previous_file,{'url':url,'capability':work})
    print(json.dumps({'already_applied':False,'setup_url':url}))


if __name__=='__main__':main()

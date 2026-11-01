"""Trusted local administration. Never expose these operations over the tunnel."""
import argparse
import json
import secrets
from pathlib import Path
from .store import Store


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--state',default='.runtime')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('init')
    sub.add_parser('probe')
    sub.add_parser('status')
    sub.add_parser('rules')
    g=sub.add_parser('grant')
    g.add_argument('--task',required=True)
    g.add_argument('--question',required=True)
    g.add_argument('--scope',required=True)
    r=sub.add_parser('revoke'); r.add_argument('id')
    a=sub.add_parser('answer'); a.add_argument('id'); a.add_argument('--text-file',required=True)
    r=sub.add_parser('rule'); r.add_argument('--kind',required=True); r.add_argument('--instruction',required=True); r.add_argument('--source',required=True)
    r=sub.add_parser('disable-rule'); r.add_argument('id')
    args=p.parse_args(); state=Path(args.state)
    state.mkdir(parents=True,exist_ok=True,mode=0o700); state.chmod(0o700)
    store=Store(state/'bridge.sqlite3')
    if args.command=='init':
        path=state/'tokens.json'
        if not path.exists():
            # O_EXCL and 0600 prevent an overwrite or a window of readable credentials.
            import os
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as f:
                json.dump({r:secrets.token_urlsafe(32) for r in ['cloro','hermes']},f)
        print('Initialized. Credentials kept in local private state; not printed.')
    elif args.command=='probe':
        print('/probe/'+store.create_probe())
    elif args.command=='status':
        print(json.dumps(store.summary(),ensure_ascii=False,indent=2))
    elif args.command=='rules':
        with store.db() as db:
            rows=[dict(row) for row in db.execute('SELECT * FROM rules ORDER BY kind')]
        print(json.dumps(rows,ensure_ascii=False,indent=2))
    elif args.command=='grant':
        print(store.grant(args.task,args.question,args.scope))
    elif args.command=='revoke':
        store.revoke(args.id); print('Revoked.')
    elif args.command=='answer':
        store.answer(args.id,Path(args.text_file).read_text()); print('Stored operator-provided answer.')
    elif args.command=='rule':
        print(store.rule(args.kind,args.instruction,args.source))
    elif args.command=='disable-rule':
        store.disable_rule(args.id); print('Disabled.')


if __name__=='__main__':
    main()

"""Refresh exact filenames inside already operator-authorized collections."""
import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from .attachments import normalized
from .store import Denied


def refresh(path):
    path=Path(path)
    original=path.read_bytes();policy=json.loads(original)
    if policy.get('enabled') is not True:raise Denied('file_policy_not_enabled')
    count=0
    for rule in policy['collections']:
        root=Path(rule['root']);resolved=root.resolve(strict=True)
        if root!=resolved or not root.is_dir():raise Denied('fixed_real_directory_required')
        pattern=re.compile(rule['filename_pattern'])
        files=root.rglob('*') if rule.get('recursive') is True else root.iterdir()
        allowed=[]
        for item in files:
            if item.is_symlink() or not item.is_file():continue
            rel=item.relative_to(root)
            if (not item.resolve(strict=True).is_relative_to(root) or any(p.startswith('.') for p in rel.parts)
                    or item.suffix.casefold() not in rule['extensions']
                    or not pattern.fullmatch(normalized(item.name))):continue
            allowed.append(str(rel))
        rule['files']=sorted(allowed);count+=len(allowed)
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='attachment-policy-',suffix='.tmp')
    try:
        with os.fdopen(fd,'w') as out:json.dump(policy,out,ensure_ascii=False)
        if path.read_bytes()!=original:raise Denied('file_policy_changed_during_refresh')
        os.replace(name,path)
    finally:Path(name).unlink(missing_ok=True)
    return count


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',default=str(Path(__file__).resolve().parents[1]/'.runtime'))
    parser.add_argument('command',choices=['refresh'])
    args=parser.parse_args()
    count=refresh(Path(args.state)/'attachment_policy.json')
    print(json.dumps({'refreshed_files':count,'permission_scope_changed':False}))

if __name__=='__main__':main()

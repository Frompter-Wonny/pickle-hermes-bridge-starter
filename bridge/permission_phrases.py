"""Owner-configured, question-specific permission language; never a blanket grant."""
import argparse
import hashlib
import json
import os
import re
import stat
import unicodedata
from pathlib import Path


def normalized(text):
    return ''.join(unicodedata.normalize('NFC',text).casefold().split())


def validate(rules):
    if not isinstance(rules,dict) or set(rules)!={'version','following_phrases','direct_templates'} or type(rules['version']) is not int or rules['version']!=1:
        raise ValueError('permission_phrase_schema_required')
    for key in ['following_phrases','direct_templates']:
        values=rules[key]
        if not isinstance(values,list) or not (1<=len(values)<=5 if key=='following_phrases' else len(values)<=5):
            raise ValueError('explicit_permission_phrases_required')
        seen=set()
        for value in values:
            if not isinstance(value,str) or not 4<=len(normalized(value))<=160 or any(c in value for c in '\n\r\x00'):
                raise ValueError('specific_single_line_permission_required')
            n=normalized(value)
            if n in seen:raise ValueError('duplicate_permission_phrase')
            seen.add(n)
            if key=='direct_templates':
                if value.count('{question}')!=1 or len(normalized(value.replace('{question}','')))<4:
                    raise ValueError('direct_template_question_slot_required')
            elif '{' in value or '}' in value:raise ValueError('following_phrase_must_be_literal')
            if key=='direct_templates' and any(c in value.replace('{question}','') for c in '{}'):
                raise ValueError('only_question_slot_supported')
    return rules


def read_private(path):
    path=Path(path);info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077:
        raise ValueError('owner_only_permission_file_required')
    return validate(json.loads(path.read_text()))


def load(state):return read_private(Path(state)/'question_permissions.json')


def digest(rules):return hashlib.sha256(json.dumps(rules,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def matches(rules,permission,mode):
    if not isinstance(permission,str) or not permission.strip():return False
    text=normalized(permission)
    if mode=='following':return text in {normalized(p) for p in rules['following_phrases']}
    if mode=='direct':
        for template in rules['direct_templates']:
            before,after=normalized(template).split('{question}')
            if re.fullmatch(re.escape(before)+r'.+'+re.escape(after),text):return True
    return False


def save(state,rules,replace=False):
    validate(rules);path=Path(state)/'question_permissions.json'
    if path.is_symlink():raise ValueError('permission_file_symlink_rejected')
    if path.exists() and not replace:raise ValueError('existing_permission_rules_require_explicit_replace')
    # Atomic replacement preserves the current valid rules if writing fails.
    import tempfile
    fd,tmp=tempfile.mkstemp(prefix='permission-',dir=state)
    try:
        with os.fdopen(fd,'w') as f:json.dump(rules,f,ensure_ascii=False)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state',default=str(Path(__file__).resolve().parents[1]/'.runtime'))
    p.add_argument('--input-file',required=True,help='Owner-only JSON containing the actual installation interview choices.')
    p.add_argument('--replace',action='store_true',help='Only after the owner explicitly changes existing phrases.')
    a=p.parse_args();save(a.state,read_private(a.input_file),replace=a.replace)
    print(json.dumps({'configured':True,'question_scope_required':True}))


if __name__=='__main__':main()

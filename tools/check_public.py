"""Publication guard; manual secret and privacy review remains necessary."""
import re
import hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PATTERNS=[re.compile(r'\b\d{8,12}:[A-Za-z0-9_-]{30,}\b'),
          re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
          re.compile(r'/Users/[A-Za-z0-9_.-]+/'),
          re.compile(r'https://[^\s/]+/(?:inbox|work)/[A-Za-z0-9_-]{20,}'),
          # Owner-specific names and old identifiers must not reappear.
          re.compile(r'\uD074\uB85C\uB85C|(?<![가-힣])\uB85C\uB85C'),
          re.compile(r'(?i)\x6b\x6c\x65\x72\x6f\x72\x6f|\x70\x69\x72\x6f\x72\x6f')]

# Exact flattened, visually reviewed excerpts only. A changed or new capture
# requires another privacy review; other binary files remain rejected.
REVIEWED_IMAGES = {
    'docs/images/attachment-menu-redacted.png': '497012ff07c651c9c574de78e69faff2903fe2e1922ddf14653d10af3062b30f',
    'docs/images/file-receipt-redacted.png': '730be1476a667c18c5a98159fc74931b0927930f3c1338aa3441fdbfec678e50',
    'docs/images/photo-transfer-redacted.png': 'c28a0217e7e78c8c2466ceb8a7b4f5f6124d440f53945d9c9b2729e31005f810',
}

def check(root):
    problems=[]
    for p in Path(root).rglob('*'):
        rel=p.relative_to(root)
        if '.git' in rel.parts or '__pycache__' in rel.parts:continue
        if any(pattern.search(str(rel)) for pattern in PATTERNS):
            problems.append((str(rel),'private identifier in path'))
        if p.is_symlink():problems.append((str(rel),'symlink'));continue
        if not p.is_file():continue
        if str(rel) in REVIEWED_IMAGES:
            if hashlib.sha256(p.read_bytes()).hexdigest()!=REVIEWED_IMAGES[str(rel)]:
                problems.append((str(rel),'reviewed capture changed; new privacy review required'))
            continue
        if any(x.startswith('.runtime') for x in rel.parts) or p.suffix in {'.db','.sqlite3','.log','.pem','.key','.png','.jpg'}:
            problems.append((str(rel),'private/runtime/binary file'));continue
        if p.suffix=='.pyc':continue
        try:text=p.read_text()
        except UnicodeError:problems.append((str(rel),'unexpected binary'));continue
        for pattern in PATTERNS:
            if pattern.search(text):problems.append((str(rel),'possible credential or personal path/URL'))
    return problems

if __name__=='__main__':
    errors=check(ROOT)
    for path,reason in errors:print(path+': '+reason)
    print('Publication guard: '+('FAIL' if errors else 'PASS (manual review still required)'))
    raise SystemExit(bool(errors))

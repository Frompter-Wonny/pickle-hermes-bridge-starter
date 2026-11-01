"""Explicit opt-in to restoring a uniquely identified minimized Pickle chat."""
import argparse,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def enable(root,consent=False):
    if consent is not True:raise ValueError('Explicit window restoration consent is required')
    path=Path(root)/'.runtime/delivery_preferences.json'
    if path.is_symlink() or not path.is_file() or path.stat().st_mode&0o077:
        raise ValueError('Existing owner-only delivery preferences are required')
    settings=json.loads(path.read_text())
    settings.update(native_window_restore_consent=True,
                    window_restore_consent_source='Local owner ran enable_window_recovery.py --consent.')
    temporary=path.with_name(path.name+'.new')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w') as f:json.dump(settings,f)
        os.replace(temporary,path)
    finally:
        if temporary.exists():temporary.unlink()
    return path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--consent',action='store_true')
    args=parser.parse_args()
    if not args.consent:parser.error('Read SETUP and explicitly permit native window restoration with --consent.')
    enable(ROOT,True)
    print('Window recovery enabled in private preferences; no UI action performed.')

if __name__=='__main__':main()

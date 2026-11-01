"""Explicit local opt-in to launching an installed Pickle app in background."""
import argparse,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def enable(root,app_path,consent=False,allow_brief_activation=False):
    if consent is not True:raise ValueError('Explicit app launch consent is required')
    app=Path(app_path).expanduser()
    if not app.is_absolute() or not app.is_dir() or app.suffix!='.app':raise ValueError('Select the installed Pickle .app directory')
    path=Path(root)/'.runtime/delivery_preferences.json'
    if path.is_symlink() or not path.is_file() or path.stat().st_mode&0o077:raise ValueError('Owner-only delivery preferences required')
    value=json.loads(path.read_text());value.update(native_app_launch_consent=True,pickle_app_path=str(app),native_launch_warmup_consent=allow_brief_activation is True,
        app_launch_consent_source='Local owner explicitly ran enable_app_launch.py --consent.')
    temporary=path.with_name(path.name+'.new');fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w') as f:json.dump(value,f)
        os.replace(temporary,path)
    finally:
        if temporary.exists():temporary.unlink()
    return path

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--app-path',required=True);p.add_argument('--consent',action='store_true');p.add_argument('--allow-brief-activation',action='store_true',help='Explicitly permit a brief startup activation followed by restoring the previous app; typing may be interrupted.');a=p.parse_args()
    enable(ROOT,a.app_path,a.consent,a.allow_brief_activation)
    print('App launch enabled in private preferences. No app launched; bundle identity will be verified at launch.')

if __name__=='__main__':main()

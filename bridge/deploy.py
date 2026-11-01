"""Install application-owned code/state outside macOS-protected Documents.

No Obsidian files are moved; no OS privacy permissions are changed.
"""
import json
import shutil
from pathlib import Path
from .session import ROOT,STATE,live
from .service import INSTALL_ROOT


def main():
    if ROOT==INSTALL_ROOT:raise SystemExit('Run deployment from the source project.')
    if live():raise SystemExit('Stop the bridge before deployment; live state is not moved.')
    INSTALL_ROOT.mkdir(parents=True,exist_ok=True,mode=0o700);INSTALL_ROOT.chmod(0o700)
    shutil.copytree(ROOT/'bridge',INSTALL_ROOT/'bridge',dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(ROOT/'docs/fixtures',INSTALL_ROOT/'docs/fixtures',dirs_exist_ok=True)
    shutil.copyfile(ROOT/'README.md',INSTALL_ROOT/'README.md')
    target=INSTALL_ROOT/'.runtime'
    if not STATE.is_symlink():
        if target.exists():raise SystemExit('Existing deployment state requires explicit review; not overwritten.')
        shutil.move(str(STATE),str(target))
        STATE.symlink_to(target,target_is_directory=True)
    elif STATE.resolve()!=target.resolve():raise SystemExit('Unexpected state symlink; not changed.')
    target.chmod(0o700)
    sources=target/'question_sources.json'
    config=json.loads(sources.read_text())
    if config.get('fixture')==str(ROOT/'docs/fixtures'):
        config['fixture']=str(INSTALL_ROOT/'docs/fixtures');sources.write_text(json.dumps(config));sources.chmod(0o600)
    (target/'deployment.json').write_text(json.dumps({'source':str(ROOT),'installed':str(INSTALL_ROOT)}))
    print('Application code and private state installed in Application Support. Source state path remains a symlink. No vault data copied.')


if __name__=='__main__':main()

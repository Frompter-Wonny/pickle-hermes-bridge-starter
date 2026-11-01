"""Initialize private config without starting services or overwriting state."""
import getpass,json,os,shutil,sys
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from bridge.store import Store


def initialize(root,vault,executable,origin,token):
    root=Path(root);vault=Path(vault).expanduser().resolve(strict=True)
    executable=Path(executable).expanduser().resolve(strict=True)
    if not vault.is_dir() or not executable.is_file() or not os.access(executable,os.X_OK):
        raise ValueError('Expected a note directory and official ngrok executable')
    if not token.strip() or any(c.isspace() for c in token):raise ValueError('Invalid token')
    state=root/'.runtime'
    if state.exists() or state.is_symlink():raise ValueError('Existing private state; refusing to overwrite')
    url=urlsplit(origin)
    if (url.scheme!='https' or not url.hostname or url.username or url.password or url.port
        or url.path not in {'','/'} or url.query or url.fragment
        or not url.hostname.endswith(('.ngrok-free.dev','.ngrok-free.app'))):
        raise ValueError('Expected your assigned free ngrok HTTPS origin')
    state.mkdir(mode=0o700)
    def save(name,value):
        fd=os.open(state/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:json.dump(value,f)
    save('tunnel.json',{'provider':'ngrok','origin':'https://'+url.hostname})
    save('ngrok.yml',{'version':'2','authtoken':token,'web_addr':'127.0.0.1:4041'})
    save('question_sources.json',{'fixture':str((root/'docs/fixtures').resolve()),'vault':str(vault)})
    shutil.copyfile(executable,state/'ngrok');(state/'ngrok').chmod(0o700)
    store=Store(state/'bridge.sqlite3');(state/'bridge.sqlite3').chmod(0o600)
    save('active_probe.json',{'probe_path':'/probe/'+store.create_probe()})
    return state


def main():
    print('Creates private config only. No service or tunnel is started.')
    vault=input('Test Markdown directory: ').strip()
    binary=input('Official ngrok executable path: ').strip()
    origin=input('Assigned ngrok HTTPS origin: ').strip()
    token=getpass.getpass('ngrok authtoken (hidden): ')
    initialize(ROOT,vault,binary,origin,token)
    print('Created owner-only .runtime. Keep it out of Git.')

if __name__=='__main__':main()

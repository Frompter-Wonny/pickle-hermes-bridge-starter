"""Tunnel selection without credential-bearing command arguments or output."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen


def settings(state):
    path=Path(state)/'tunnel.json'
    if not path.exists():return {'provider':'cloudflare'}
    config=json.loads(path.read_text())
    if config.get('provider')=='cloudflare':return {'provider':'cloudflare'}
    if config.get('provider')!='ngrok':raise ValueError('unsupported_tunnel_provider')
    origin=config.get('origin','');url=urlsplit(origin)
    if (url.scheme!='https' or not url.hostname or url.username or url.password or url.port
        or url.path not in {'','/'} or url.query or url.fragment
        or not url.hostname.endswith(('.ngrok-free.dev','.ngrok-free.app'))):
        raise ValueError('expected_assigned_free_ngrok_origin')
    return {'provider':'ngrok','origin':'https://'+url.hostname}


def command(state,config):
    state=Path(state).resolve()
    if config['provider']=='cloudflare':
        return [str(state/'cloudflared'),'--no-autoupdate','tunnel','--config','/dev/null',
                '--url','http://127.0.0.1:8766','--protocol','http2']
    if not (state/'ngrok.yml').exists():raise ValueError('ngrok_private_auth_config_missing')
    return [str(state/'ngrok'),'http','http://127.0.0.1:8766','--url',config['origin'],
            '--config',str(state/'ngrok.yml'),'--inspect=false','--log=stdout','--log-format=json']


def ngrok_ready_origin(config):
    # Loopback agent API remains available with HTTP payload inspection disabled.
    try:
        with urlopen('http://127.0.0.1:4041/api/tunnels',timeout=1) as response:data=json.load(response)
        for tunnel in data.get('tunnels',[]):
            if (tunnel.get('public_url')==config['origin']
                and tunnel.get('config',{}).get('addr')=='http://127.0.0.1:8766'
                and tunnel.get('config',{}).get('inspect') is False):
                return config['origin']
    except (OSError,ValueError):pass
    return None

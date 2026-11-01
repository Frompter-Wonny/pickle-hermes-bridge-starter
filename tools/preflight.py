"""Read-only installation checks. No UI actions, grants, model calls or repairs."""
import argparse
import ast
import json
import os
import platform
import plistlib
import re
import shutil
import socket
import stat
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class Host:
    def system(self):return platform.system()
    def mac_version(self):return platform.mac_ver()[0]
    def apple_silicon(self):
        if platform.machine().lower()=='arm64':return True
        # Read hardware capability even when the interpreter runs via Rosetta.
        try:
            p=subprocess.run(['/usr/sbin/sysctl','-n','hw.optional.arm64'],capture_output=True,text=True,timeout=2)
            return p.returncode==0 and p.stdout.strip()=='1'
        except (OSError,subprocess.TimeoutExpired):return False
    def python_info(self,executable):
        code='''import sys,json
from pathlib import Path
from importlib.metadata import version,PackageNotFoundError
site=Path(sys.argv[1])/'lib'/('python%d.%d'%sys.version_info[:2])/'site-packages'
sys.path.append(str(site))
try:native=version('pyobjc-framework-Cocoa')
except PackageNotFoundError:native=None
print(json.dumps({'version':list(sys.version_info[:3]),'cocoa':native}))'''
        try:
            p=subprocess.run([str(executable),'-I','-S','-c',code,str(Path(executable).parent.parent)],
                capture_output=True,text=True,timeout=5,env={'PATH':os.defpath})
            if p.returncode==0:return json.loads(p.stdout)
        except (OSError,ValueError,subprocess.TimeoutExpired):pass
        return None
    def port_open(self,port):
        try:
            with socket.create_connection(('127.0.0.1',port),timeout=.25):return True
        except OSError:return False


def private_json(path):
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077:
        raise ValueError('not_owner_only')
    if info.st_size>1_000_000:raise ValueError('config_too_large')
    value=json.loads(path.read_text())
    if not isinstance(value,dict):raise ValueError('config_object_required')
    return value


def app_id(path):
    # App Store iOS wrappers can expose Info.plist under Wrapper/*.app.
    candidates=[path/'Contents/Info.plist',path/'Info.plist']
    candidates+=list((path/'Wrapper').glob('*.app/Info.plist')) if (path/'Wrapper').is_dir() else []
    for p in candidates:
        try:
            with p.open('rb') as f:data=plistlib.load(f)
            if isinstance(data,dict) and data.get('CFBundleIdentifier')=='com.pickle.client':return True
        except (OSError,ValueError,plistlib.InvalidFileException):pass
    return False


def app_candidates():
    result=[]
    for base in [Path('/Applications'),Path.home()/'Applications']:
        try:
            for p in base.glob('*.app'):
                if app_id(p):result.append(p)
        except OSError:pass
    return result


def report(root=ROOT,hermes_root=None,pickle_app=None,phase='prerequisites',files=False,automatic=False,host=None):
    host=host or Host();root=Path(root);state=root/'.runtime';checks=[]
    required='block' if phase=='configured' else 'warn'
    def add(key,status,message,next_step=''):
        checks.append({'id':key,'status':status,'message':message,'next_step':next_step})
    mac=host.system()=='Darwin'
    add('macos','pass' if mac else 'block','macOS 실행 환경입니다.' if mac else 'macOS 이외 환경은 지원하지 않습니다.','로컬 Mac에서 실행하세요.' if not mac else '')
    if mac:
        supported=host.apple_silicon();add('apple_silicon','pass' if supported else 'block','Apple Silicon 하드웨어 확인.' if supported else 'Apple Silicon 하드웨어가 확인되지 않았습니다.','M1 이상 Mac인지 확인하세요.' if not supported else '')
        version=host.mac_version();parts=re.match(r'^(\d+)\.(\d+)',version)
        supported=bool(parts and tuple(map(int,parts.groups()))>=(14,0))
        add('macos_version','pass' if supported else 'block','macOS 14 이상 확인.' if supported else '요구 macOS 버전을 확인할 수 없거나 미달입니다.','App Store의 최신 호환성과 OS 버전을 확인하세요.' if not supported else '')
    add('runner_python','pass' if sys.version_info>=(3,11) else 'warn','점검 도구의 Python 버전 확인.','설치 실행은 아래에서 확인한 Hermes Python 3.11 이상을 사용하세요.' if sys.version_info<(3,11) else '')
    hermes=Path(hermes_root or os.environ.get('PICKLE_BRIDGE_HERMES_ROOT',str(Path.home()/'.hermes/hermes-agent'))).expanduser()
    python=hermes/'venv/bin/python'
    present=all((hermes/f).is_file() for f in ['cli.py','toolsets.py','tools/registry.py','tools/computer_use/cua_backend.py','tools/computer_use/tool.py'])
    add('hermes_source','pass' if present else 'block','Hermes 소스 구조 확인.' if present else '필요한 Hermes 소스 설치를 찾지 못했습니다.','실제 소스 루트를 --hermes-root로 지정하거나 공식 설치를 완료하세요.' if not present else '')
    info=host.python_info(python) if python.is_file() and os.access(python,os.X_OK) else None
    valid=bool(info and isinstance(info.get('version'),list) and tuple(info['version'][:2])>=(3,11))
    add('hermes_python','pass' if valid else 'block','Hermes Python 3.11 이상 확인.' if valid else 'Hermes Python이 없거나 3.11 미만이거나 실행 확인에 실패했습니다.','기존 모델 설정을 보존하고 호환되는 Hermes Python 환경을 준비하세요.' if not valid else '')
    native=bool(info and info.get('cocoa')=='13.0')
    add('native_dependency','pass' if native else required,'Cocoa 의존성 13.0의 설치 메타데이터 확인.' if native else '검증 기준 Cocoa 의존성이 없거나 다른 버전입니다.','Hermes Python으로 requirements-native.txt를 설치/검토하세요. 이 점검은 패키지를 설치하지 않습니다.' if not native else '')
    if present:
        expected={'toolsets.py':{'create_custom_toolset','resolve_multiple_toolsets'},'tools/computer_use/tool.py':{'set_approval_callback','_request_approval','_get_backend'},'tools/computer_use/cua_backend.py':{'_action'}}
        available=True;snapshot=False
        try:
            for rel,names in expected.items():
                tree=ast.parse((hermes/rel).read_text());found={n.name for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
                available=available and names<=found
            capture=hermes/'tools/computer_use/cua_backend_capture.py'
            if capture.is_file():
                tree=ast.parse(capture.read_text());snapshot=any(isinstance(n,ast.Attribute) and n.attr=='_snapshot_id' and isinstance(n.ctx,ast.Store) for n in ast.walk(tree))
            add('hermes_interfaces','pass' if available else 'block','주요 내부 함수 정의 확인.' if available else '브리지가 사용하는 내부 함수 정의가 빠져 있습니다.','호환 Hermes 버전/어댑터를 검토하세요. 자동 패치하지 않습니다.' if not available else '')
            add('snapshot_support','pass' if snapshot else 'warn','캡처 snapshot ID 저장 코드 확인.' if snapshot else '캡처 snapshot ID 저장이 정적 검사에서 확인되지 않았습니다.','driver 토큰/캡처 호환성을 가상 UI로 확인하세요. 이 항목만으로 고장을 단정하지 않습니다.' if not snapshot else '')
        except (OSError,SyntaxError,UnicodeError):add('hermes_interfaces','manual','Hermes 내부 코드를 정적으로 판독하지 못했습니다.','Hermes Python과 설치 버전을 확인하세요.')
    # Read only private state; never print contents, paths, names or exceptions.
    initialized=state.is_dir();state_safe=False
    if initialized:
        st=state.stat();state_safe=st.st_uid==os.getuid() and not stat.S_IMODE(st.st_mode)&0o077
    add('private_state','pass' if state_safe else (required if not initialized else 'block'),'비공개 상태 디렉터리 권한 확인.' if state_safe else '상태 디렉터리가 없거나 소유자 전용 권한이 아닙니다.','새 설치면 setup_local.py를 실행하세요. 기존 설치는 덮어쓰지 말고 확인하세요.' if not state_safe else '')
    prefs={}
    if state_safe and (state/'delivery_preferences.json').exists():
        try:prefs=private_json(state/'delivery_preferences.json')
        except (OSError,ValueError):add('delivery_preferences','block','입력 동의 설정 파일이 손상됐거나 비공개 권한이 아닙니다.','설치 소유자와 기존 설정을 확인하세요.')
    selected=pickle_app or prefs.get('pickle_app_path')
    if selected:
        candidate=Path(selected).expanduser();apps=[candidate] if candidate.is_dir() and app_id(candidate) else []
    else:apps=app_candidates() if mac else []
    add('pickle_app','pass' if len(apps)==1 else ('block' if selected or not apps else 'manual'),
        'Pickle 앱 bundle ID 확인.' if len(apps)==1 else ('Pickle 설치본을 확인하지 못했습니다.' if not apps else 'Pickle 후보가 여러 개라 설치본 선택이 필요합니다.'),
        '공식 Mac App Store 설치/로그인 후 실제 .app을 --pickle-app으로 지정하세요.' if len(apps)!=1 else '')
    if state_safe:
        try:
            sources=private_json(state/'question_sources.json')
            if not sources or not all(isinstance(v,str) and Path(v).expanduser().is_dir() for v in sources.values()):raise ValueError()
            add('note_sources','pass','자료 source 폴더의 존재·설정 권한만 확인했습니다. 노트 내용은 읽지 않았습니다.')
        except (OSError,ValueError,TypeError):add('note_sources',required,'노트 source 설정이 없거나 지정 폴더를 확인하지 못했습니다.','허락한 자료 폴더만 비공개 source 설정에 지정하세요.')
        try:
            path=state/'ngrok.yml';st=path.lstat()
            if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)&0o077:raise ValueError()
            add('tunnel_credentials','pass','터널 인증 파일의 존재·비공개 권한만 확인했습니다. 토큰 유효성은 검사하지 않았습니다.')
        except (OSError,ValueError):add('tunnel_credentials',required,'터널 인증 파일이 없거나 비공개 권한이 아닙니다.','공식 설치 절차로 로컬에서 인증정보를 설정하세요.')
        try:
            config=private_json(state/'tunnel.json');from urllib.parse import urlsplit
            u=urlsplit(config.get('origin',''))
            if config.get('provider')!='ngrok' or u.scheme!='https' or not u.hostname or not u.hostname.endswith(('.ngrok-free.dev','.ngrok-free.app')) or u.username or u.password or u.port or u.path not in {'','/'} or u.query or u.fragment:raise ValueError()
            add('tunnel_settings','pass','지원되는 터널 설정 형식 확인. 실제 연결은 별도 검증이 필요합니다.')
        except (OSError,ValueError,TypeError):add('tunnel_settings',required,'터널 설정이 없거나 지원 형식과 다릅니다.','할당된 HTTPS 주소를 비공개 설정에서 확인하세요.')
        binary=state/'ngrok'
    else:binary=Path(shutil.which('ngrok') or '/nonexistent-preflight-ngrok')
    add('ngrok_binary','pass' if binary.is_file() and os.access(binary,os.X_OK) else required,'ngrok 실행 파일의 존재·실행 권한 검사.','없으면 공식 ngrok을 설치하고 설정하세요.')
    if state_safe:
        try:
            sys.path.insert(0,str(root));from bridge.permission_phrases import load
            load(state);add('permission_phrases','pass','질문별 허락 문구의 형식·비공개 권한 확인.')
        except (OSError,ValueError):add('permission_phrases',required,'질문 허락 문구가 없거나 유효하지 않습니다.','설치 인터뷰에서 소유자가 문구를 선택하고 저장하세요.')
    if automatic:
        consent=prefs.get('native_clipboard_consent') is True and prefs.get('input_method')=='context_paste'
        add('automatic_delivery_consent','pass' if consent else required,'자동 전달의 명시적 로컬 동의 확인.' if consent else '자동 전달 동의가 설정되지 않았습니다.','소유자가 선택한 경우에만 동의 도우미를 사용하세요.' if not consent else '')
    if files:
        roots=[]
        try:
            cfg=private_json(state/'file_picker_favorites.json')
            items=cfg['favorites']
            if not isinstance(items,list) or not items:raise ValueError()
            for item in items:
                root_path=Path(item['root'])
                if not root_path.is_absolute() or root_path!=root_path.resolve(strict=True) or not root_path.is_dir() or type(item['ordinal']) is not int or item['ordinal']<0:raise ValueError()
                if root_path in roots:raise ValueError()
                roots.append(root_path)
            add('favorite_bindings','pass','즐겨찾기 바인딩 형식과 실제 폴더 존재를 확인했습니다. UI 순서는 미검증입니다.')
        except (OSError,ValueError,KeyError,TypeError,RuntimeError):add('favorite_bindings',required,'즐겨찾기 설정이 없거나 경로·순서 형식이 유효하지 않습니다.','허락한 폴더와 임시 폴더를 실제 선택창에서 확인해 비공개 바인딩을 저장하세요.')
        staging=Path.home()/'PickleUploadStaging'
        covered=any(staging.is_relative_to(r) for r in roots)
        add('staging_favorite','pass' if covered else required,'메신저 임시 폴더의 즐겨찾기 경로 범위 확인.' if covered else '메신저 임시 폴더의 즐겨찾기 바인딩이 없습니다.','메신저 파일 전달을 선택했다면 임시 폴더를 준비하고 바인딩하세요.' if not covered else '')
        add('favorite_ui','manual','파일 선택창의 실제 즐겨찾기 순서·전체 위치·입력란은 자동 확인하지 않았습니다.','설치 에이전트가 실제 UI와 가상 첨부 수신을 확인해야 합니다.')
        policy=state/'attachment_policy.json'
        if policy.exists():
            try:
                cfg=private_json(policy)
                if cfg.get('enabled') is True:
                    cols=cfg['collections']
                    if cfg.get('destination')!='pickle_own_chat' or not isinstance(cols,list) or not cols:raise ValueError()
                    for col in cols:
                        base=Path(col['root']).resolve(strict=True)
                        if not base.is_dir() or not any(base.is_relative_to(r) for r in roots):raise ValueError()
                    add('standing_file_policy','pass','상시 파일 정책의 수신 종류·컬렉션 폴더·즐겨찾기 범위만 확인했습니다. 개별 파일 허용/화면 검증은 별도입니다.')
                else:add('standing_file_policy','manual','상시 파일 요청 기능은 비활성 상태입니다.','사용자가 선택한 경우에만 정책을 설정하세요. 단발성 파일 전달과 별개입니다.')
            except (OSError,ValueError,KeyError,TypeError,RuntimeError):add('standing_file_policy','block','상시 파일 정책의 기본 구조·폴더·즐겨찾기 범위 확인에 실패했습니다.','소유자의 허락 범위와 기존 정책을 검토하세요. 자동 확대하지 않습니다.')
        else:add('standing_file_policy','manual','상시 파일 요청 정책은 없습니다. 단발성 파일 전달 허락을 대신하지 않습니다.','상시 파일 전달을 선택한 경우에만 별도 정책을 구성하세요.')
    for port in [8766,4041]:
        occupied=host.port_open(port)
        add('port_'+str(port),('manual' if initialized else 'block') if occupied else 'pass','필요한 포트가 사용 중입니다.' if occupied else '필요한 포트에 현재 TCP 응답이 없습니다.',
            '기존 브리지/터널의 소유 설치를 확인하세요. 이 도구는 프로세스를 종료하지 않습니다.' if occupied else '')
    add('os_permissions','manual','화면 기록·접근성 권한은 실제 computer-use 드라이버 프로세스에서 확인해야 합니다. 현재 Python의 권한을 대신 검사하지 않습니다.','Hermes computer-use doctor와 가상 UI 캡처/전송을 설치 절차에서 확인하세요.')
    add('live_connection','manual','앱 로그인·모델 인증·실제 터널·메시지/파일 수신은 이 점검으로 증명하지 않습니다.','설치 가이드의 실제 가상 자료 왕복 시험을 완료하세요.')
    return {'phase':phase,'read_only':True,'automatic_blockers':sum(c['status']=='block' for c in checks),
            'end_to_end_verified':False,'checks':checks}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--hermes-root');p.add_argument('--pickle-app');p.add_argument('--phase',choices=['prerequisites','configured'],default='prerequisites')
    p.add_argument('--with-files',action='store_true');p.add_argument('--automatic-delivery',action='store_true');p.add_argument('--json',action='store_true')
    a=p.parse_args()
    try:result=report(hermes_root=a.hermes_root,pickle_app=a.pickle_app,phase=a.phase,files=a.with_files,automatic=a.automatic_delivery)
    except (OSError,ValueError,TypeError,KeyError,RuntimeError):
        # OS/read errors can embed private paths or values. Never echo them.
        result={'phase':a.phase,'read_only':True,'automatic_blockers':1,'end_to_end_verified':False,
                'checks':[{'id':'preflight_read_error','status':'block','message':'점검 환경이나 설정을 읽는 중 오류가 발생했습니다.',
                           'next_step':'로컬에서 경로·권한·설정 형식을 확인하세요. 예외 원문을 공유하지 않습니다.'}]}
    if a.json:print(json.dumps(result,ensure_ascii=False,indent=2))
    else:
        for c in result['checks']:
            print('[%s] %s: %s'%(c['status'].upper(),c['id'],c['message']))
            if c['next_step']:print('  → '+c['next_step'])
        print('자동 차단 항목: %d. 실제 연결 검증은 별도로 필요합니다.'%result['automatic_blockers'])
    raise SystemExit(1 if result['automatic_blockers'] else 0)


if __name__=='__main__':main()

# 처음 설치하기

Codex·Claude Code에게 맡긴다면 [에이전트 설치 지침](AGENT_INSTALL.md)부터 읽게 하세요. 아래는 에이전트와 사람이 공통으로 사용하는 실제 명령·성공 기준입니다.

목표는 **가상 자료로 실제 왕복을 확인한 뒤**, 원하는 경우 Mac 로그인 자동 시작을 적용하는 것입니다. 처음부터 개인 옵시디언 전체를 연결할 필요는 없습니다.

명령어의 `$PICKLE_BRIDGE_PYTHON` 등은 아래에서 설정하는 경로 변수입니다. **모든 단계를 같은 터미널에서** 실행하세요. 실제 토큰은 채팅·명령 인자·Git에 넣지 않습니다.

## 1. 지원 환경과 준비물

**macOS 전용입니다. Windows·Linux에서는 설치·실행할 수 없습니다.** WSL이나 원격 Linux 환경도 피클 Mac 앱을 조작하는 이 브리지의 실행 환경으로 지원하지 않습니다. macOS 접근성 API·AppKit·launchd를 사용하므로 Windows용 명령으로 치환해서 설치하지 마세요.

2026-11-01 확인한 [Pickle App Store 호환성](https://apps.apple.com/us/app/pickle-your-personal-ai-agent/id6795790129)은 Apple M1 이상·macOS 14.0 이상입니다. **Intel Mac은 제외**됩니다. iPhone용 앱의 Mac 실행이며 macOS 검증 미완료 표기가 있으므로, 지원 조건만으로 설치·GUI 조작 성공을 보장하지 않습니다. 실제 Mac App Store에서 설치 버튼과 실행 가능 여부를 확인한 다음 브리지를 준비하세요. 앱의 배포 조건이 바뀌면 최신 표기를 우선합니다.

Pickle이 아직 없다면 설치 에이전트가 공식 App Store 페이지부터 안내합니다. Apple 인증·설치 승인·피클 로그인은 직접 완료한 뒤 같은 작업을 이어갑니다. [미설치 시 절차](AGENT_INSTALL.md#1-1-pickle이-설치되지-않은-경우)를 따르며 비공식 설치로 우회하지 않습니다.

| 준비물 | 먼저 확인할 것 |
|---|---|
| macOS·Pickle | Apple Silicon(M1 이상), macOS 14.0 이상. Mac App Store에서 Pickle 설치·실행 및 로그인 후 본인 채팅과 빈 입력란이 보임 |
| Hermes 소스 설치 | 모델 인증과 일반 대화가 됨. `venv/bin/python`, `venv/bin/hermes`가 존재 |
| Hermes computer_use | 드라이버 설치, 화면 기록·접근성 권한과 실제 피클 캡처가 동작 |
| ngrok | 공식 실행 파일, 계정의 할당된 HTTPS 도메인, authtoken 준비 |
| GitHub 접근 | 현재 Private 검토 중이므로 허락된 계정으로 접근 |

준비물이 없다면 [Hermes 공식 설치 안내](https://hermes-agent.nousresearch.com/docs/getting-started/installation), [computer_use 공식 안내](https://hermes-agent.nousresearch.com/docs/user-guide/features/computer-use), [ngrok Mac 설치](https://ngrok.com/download/mac-os), [GitHub CLI](https://cli.github.com/)부터 확인하세요. 서비스 가입·모델 인증은 자신의 계정으로 합니다.

이 브리지는 **소스 설치형 Hermes의 Python 내부 인터페이스**를 사용합니다. Desktop 앱이나 다른 패키징만 설치돼 있다면 경로와 호환성을 먼저 확인해야 합니다. 공식 최신 설치판이라는 이유만으로 그대로 호환된다고 가정하지 않습니다. 원래 검증 환경은 Hermes 체크아웃 `8068c09432d`의 로컬 환경·Python 3.11·cua-driver 0.38.0이며, CI는 Python 3.11/3.12/3.13에서 실행합니다. 해당 커밋만으로 원래 환경의 모든 로컬 변경까지 재현되지는 않습니다.

**같은 Mac의 기존 브리지가 있으면 여기서 멈추고 맨 아래 ‘기존 설치 업데이트’로 이동하세요.** 기본 포트 8766/4041과 launchd 이름 `com.picklehermes.bridge`를 공유하므로 여러 설치를 동시에 실행하지 않습니다.

## 2. 저장소 받기와 Python 경로 설정

GitHub CLI를 사용할 경우 자신의 계정으로 `gh auth login`을 완료한 뒤:

```sh
gh repo clone Frompter-Wonny/pickle-hermes-bridge-starter
cd pickle-hermes-bridge-starter
umask 077
export PICKLE_BRIDGE_HERMES_ROOT="$HOME/.hermes/hermes-agent"
PICKLE_BRIDGE_PYTHON="$PICKLE_BRIDGE_HERMES_ROOT/venv/bin/python"
"$PICKLE_BRIDGE_PYTHON" --version
```

위 Hermes 경로가 자신의 설치와 다르면 **실제 소스 루트로 수정**합니다. `No such file`이면 이후 명령을 실행하지 않습니다. Mac 기본 `python3`가 구버전일 수 있으므로 아래에서는 확인한 Hermes 환경의 Python을 사용합니다. 새 터미널에서는 변수를 다시 설정하세요.

먼저 로컬 코드 검사를 실행합니다. 이 단계는 서버·ngrok·피클을 시작하지 않습니다.

```sh
"$PICKLE_BRIDGE_PYTHON" tools/check_public.py
"$PICKLE_BRIDGE_PYTHON" -m unittest discover -s tests -q
"$PICKLE_BRIDGE_HERMES_ROOT/venv/bin/hermes" computer-use doctor
```

검사 실패는 먼저 해결합니다. 접근성·화면 기록 권한은 Mac 소유자가 직접 검토해 허용하며 보안 설정을 자동으로 끄지 않습니다.

## 3. 비공개 설정 만들기

**실행 위치: 내려받은 저장소 루트.** 아래에서 만든 시험용 자료 폴더는 비어 있어도 됩니다. 가상 예제는 별도로 포함된 `docs/fixtures`를 사용합니다.

```sh
PICKLE_BRIDGE_TEST_NOTES="$HOME/Library/Application Support/BridgeTestNotes"
mkdir -p "$PICKLE_BRIDGE_TEST_NOTES"
chmod 700 "$PICKLE_BRIDGE_TEST_NOTES"
command -v ngrok
"$PICKLE_BRIDGE_PYTHON" tools/setup_local.py
```

대화형 질문에는 다음을 입력합니다.

| 화면 질문 | 넣을 값 |
|---|---|
| Test Markdown directory | 방금 만든 시험 폴더의 전체 경로. `$HOME` 문자열 대신 실제 펼쳐진 경로를 입력 |
| Official ngrok executable path | `command -v ngrok`로 확인한 실행 파일 전체 경로 |
| Assigned ngrok HTTPS origin | 자신의 대시보드에 할당된 `https://…ngrok-free.dev` 또는 `https://…ngrok-free.app` 주소 |
| ngrok authtoken (hidden) | 자신의 토큰을 이 숨김 입력란에만 입력 |

시험 폴더의 전체 경로가 필요하면 `printf '%s\n' "$PICKLE_BRIDGE_TEST_NOTES"`로 확인합니다. `command -v ngrok`가 비어 있으면 먼저 ngrok 설치를 완료합니다.

성공하면 `Created owner-only .runtime`이 표시됩니다. 아직 서버·터널은 시작하지 않습니다. 토큰·DB는 비공개 `.runtime`에 보관하고 기존 상태는 덮어쓰지 않습니다. 전체 노트 볼트 연결은 첫 가상 시험을 마친 뒤 설치 소유자가 별도로 결정합니다.

## 4. Hermes 비서 스킬과 입력 도우미 준비

**실행 위치: 계속 소스 저장소 루트.** Hermes가 사용하는 같은 Python 환경에 네이티브 의존성을 설치합니다.

```sh
"$PICKLE_BRIDGE_PYTHON" -m pip install -r requirements-native.txt
mkdir -p "$HOME/.hermes/skills/productivity/pickle-delegation"
cp -i skills/pickle-delegation/SKILL.md "$HOME/.hermes/skills/productivity/pickle-delegation/SKILL.md"
mkdir -p "$HOME/.hermes/skills/productivity/pickle-delegation/references"
cp -i skills/pickle-delegation/references/local-file-upload.md "$HOME/.hermes/skills/productivity/pickle-delegation/references/local-file-upload.md"
mkdir -p "$HOME/.hermes/skills/productivity/pickle-delegation/scripts"
cp -i skills/pickle-delegation/scripts/stage_local_file.py "$HOME/.hermes/skills/productivity/pickle-delegation/scripts/stage_local_file.py"
```

기존 스킬이 있다면 덮어쓰기 전에 비교·백업합니다. `SKILL.md`, 연결된 `references/local-file-upload.md`, `scripts/stage_local_file.py`를 함께 설치합니다. 다른 Hermes 홈/프로필을 쓰면 그 프로필의 실제 스킬 경로에 설치하세요. 이 프로젝트가 기존 `AGENTS.md`나 다른 봇의 접근 정책을 자동 변경하지는 않습니다. 아래 명령을 실행하지 않고도 수동으로 링크를 전달하는 시험은 할 수 있지만, 자동 입력 시험에는 첫 동의가 필요합니다.

### 기능별로 이해하고 선택하기

| 기능 | 무엇을 허락하나 | 이 Mac에서 검증한 범위 |
|---|---|---|
| 백그라운드 전달 | 원래 클립보드의 모든 형식을 RAM에만 보관·복원하고 실제 입력란의 붙여넣기 메뉴 사용 | 일반 왕복·다른 앱 동시 타이핑 |
| 최소화 복원 | 유일한 실제 피클 채팅의 최소화만 해제 | 최소화부터 전달·답변 |
| 꺼진 앱 실행 | 지정한 설치본이 꺼졌을 때 한 번 실행 | 실행·기존 로그인/채팅 복귀 |
| 시작 시 잠깐 활성화 | **방금 새로 실행한 앱만** 잠깐 활성화해 빈 입력란을 선택하고 원래 앱 복원 | 이 준비를 포함한 완전 종료부터 실제 답변까지 1회 |

클립보드 내용은 모델·파일·로그에 보내지 않습니다. 새 복사가 감지되면 덮어쓰지 않고 중단하지만 동시 복사·붙여넣기 충돌 가능성은 남습니다. 시작 시 잠깐 활성화하는 순간에는 타이핑이 끊길 수 있습니다. 일반 전달·최소화 복원에는 그 활성화를 적용하지 않습니다.

설치 소유자가 각 범위에 동의할 때만 해당 명령을 직접 실행합니다. **이 명령들은 동의를 저장할 뿐, 지금 앱을 실행하거나 창을 조작하지 않습니다.**

```sh
# 자동 메시지 입력에 필요한 동의
"$PICKLE_BRIDGE_PYTHON" tools/enable_native_delivery.py --consent

# 선택: 최소화 복원
"$PICKLE_BRIDGE_PYTHON" tools/enable_window_recovery.py --consent
```

선택적으로 꺼진 앱도 자동 실행하려면 Finder에서 확인한 실제 설치 경로를 지정합니다. 아래 앱 이름은 자신의 설치에 맞게 수정합니다.

```sh
PICKLE_BRIDGE_PICKLE_APP="/Applications/피클.app"
"$PICKLE_BRIDGE_PYTHON" tools/enable_app_launch.py --app-path "$PICKLE_BRIDGE_PICKLE_APP" --consent
```

**완전 재실행 직후 배경 입력만으로는 실패한 이력이 있습니다.** 시작할 때 잠깐 활성화하는 것까지 동의한다면 위 명령 대신 다음을 실행합니다. 이미 앱 실행 동의를 저장했다면 이 명령으로 그 선택을 갱신할 수 있습니다.

```sh
"$PICKLE_BRIDGE_PYTHON" tools/enable_app_launch.py --app-path "$PICKLE_BRIDGE_PICKLE_APP" --consent --allow-brief-activation
```

로그인·업데이트·약관 화면은 넘기지 않고 멈춥니다. OS 잠금·절전도 해제하지 않습니다. 포괄적인 컴퓨터 조작 권한이나 전체 노트 접근 허락은 아닙니다.

## 5. 수동 세션에서 첫 연결

**피클에 로그인한 뒤 본인 채팅을 열고 입력란을 비워 둡니다.** 처음에는 앱을 열어 둔 상태로 연결하고, 최소화·종료 복구는 기본 왕복 뒤에 시험하세요.

```sh
"$PICKLE_BRIDGE_PYTHON" -m bridge.session start --seconds 3600
"$PICKLE_BRIDGE_PYTHON" -m bridge.session status
"$PICKLE_BRIDGE_PYTHON" -m bridge.configure > .runtime/configure-output.json
```

4단계에서 자동 입력에 동의했다면 같은 소스 루트에서 실행합니다. 동의하지 않았다면 아래의 수동 전달로 건너뜁니다.

```sh
"$PICKLE_BRIDGE_PYTHON" -m bridge.deliver --task-file .runtime/onboarding.json
"$PICKLE_BRIDGE_PYTHON" -m bridge.deliver --task-file .runtime/onboarding.json --status
```

최초 설정 작업이 `completed`가 되고 실제 Pickle 비서가 규칙 적용을 답하는지 확인합니다. `.runtime/onboarding.json`은 발행된 설정 작업 그 자체이며 추가 업무를 만들 필요가 없습니다. 링크는 비밀입니다.

자동 입력 동의를 하지 않았다면 비공개 `.runtime/configure-output.json`의 `setup_url`을 본인 피클 채팅에만 아래 문장으로 직접 보냅니다. 값을 공개 이슈에 붙이지 않습니다.

> 이 링크를 HTTP GET해서 task.instruction의 연결 규칙을 적용하고 result_url에 적용 결과를 POST해 줘: 여기에_내_setup_url

`configure`를 나중에 다시 실행해 `already_applied: true`가 나오면 완료된 작업을 재전송하지 않습니다. 새 대화가 설정을 잊었거나 실제 재적용이 필요할 때만 `bridge.configure --force`로 새 설정 작업을 만듭니다.

## 6. 성공 판정: 양방향 가상 시험

### A. Hermes 비서 → Pickle 비서

개인정보·전화·결제가 없는 첫 시험 업무를 만듭니다.

```sh
mkdir -p .runtime/first-task
cat > .runtime/first-task/instruction.txt <<'TASK'
가상 연결 시험이다. 다른 업무나 개인정보 조회 없이, 이 업무의 result_url에 status completed와 result 첫 연결 시험 성공 을 JSON POST하고 피클 채팅에도 첫 연결 시험 성공 이라고 답해 줘.
TASK
"$PICKLE_BRIDGE_PYTHON" -m bridge.handoff create --instruction-file .runtime/first-task/instruction.txt --source '설치 소유자의 가상 시험 지시' --request-id "first-test-$(date +%s)" --output-file .runtime/first-task/task.json
"$PICKLE_BRIDGE_PYTHON" -m bridge.deliver --task-file .runtime/first-task/task.json
"$PICKLE_BRIDGE_PYTHON" -m bridge.deliver --task-file .runtime/first-task/task.json --status
```

**성공 기준: `task_status: completed`·`result: 첫 연결 시험 성공`과 실제 피클 답변.** `exit_code: 0`이나 링크 전송만으로는 성공이 아닙니다. 불명확한 전송은 재실행하지 말고 기존 기록을 확인합니다. 첫 시험 파일은 새 파일로만 발행되므로 같은 명령을 무작정 반복하지 않습니다.

### B. Pickle 비서 → Hermes 비서

본인이 직접 피클에 입력합니다.

> Hermes 비서한테 가상 사용자 BRIDGE-QA-7319의 선호 활동이 뭔지 물어봐줘.

질문과 고유 번호가 피클에 표시되고, Hermes 비서의 실제 화면 검증 뒤 **“종이 제본 체험”**이 돌아오는지 확인합니다. 이 예제는 `docs/fixtures/BRIDGE-QA-7319.md`에 있으며 실제 가족 정보가 아닙니다. 처음 설정한 빈 시험 노트 폴더가 아닌 `fixture` 자료를 검색해야 합니다.

질문 뒤에 “그건 Hermes 비서한테 물어봐”라고 허락하는 경로도 지원합니다. 모든 질문의 포괄 허락은 아닙니다. 허락 없이 자동 조회되는지 확인하려고 수동 `grant`를 만들거나 검증을 끄지 않습니다.

### C. 선택한 복구 기능

기본 왕복이 끝난 뒤에만 최소화한 상태, 정상 종료한 상태에서 **각각 새 가상 업무**로 시험합니다. 기존 미완료 업무를 복제하지 않습니다. 시작 시 활성화를 허용했다면 원래 앱으로 돌아오는지도 확인하세요. 첫 새 Mac에서는 직접 결과를 보기 전까지 성공을 가정하지 않습니다.

## 6-1. 파일 전달 폴더와 즐겨찾기 (선택)

파일 전달도 쓰려면 **누구에게 어느 폴더의 어떤 파일을, 이번만 또는 이후에도 전달할지** 먼저 정하세요. 파일 선택창 즐겨찾기에 넣은 것만으로 접근 허락이 생기지는 않습니다. Codex·Claude Code는 기존 허락이 없으면 이 범위를 질문하고, 실제 Pickle 파일 선택창에서 즐겨찾기를 확인해야 합니다.

[폴더 즐겨찾기 설정](FOLDER_FAVORITES.md)에 따라 허락한 자료 폴더와 메신저 사본용 폴더를 각각 확인합니다. 없는 항목은 직접 추가하거나 지원되는 UI 도구로 추가하도록 구체적으로 요청할 수 있습니다. 자동 추가 기능이 이미 구현된 것으로 가정하지 않습니다. 파일 전달을 쓰지 않으면 생략하세요. 실제 개인 파일을 허락 없이 시험 전송하지 않습니다.

## 7. 원하면 Mac 로그인 자동 시작

가상 왕복이 성공한 뒤, Mac 로그인 시 중계 서버·ngrok을 상시 시작하고 싶은 경우에만 진행합니다. Hermes의 Telegram gateway는 별도로 이미 구성돼 있어야 하며 이 브리지가 대신 설치하지 않습니다.

**실행 위치: 소스 저장소 루트.**

```sh
"$PICKLE_BRIDGE_PYTHON" -m bridge.session stop
"$PICKLE_BRIDGE_PYTHON" -m bridge.deploy
"$PICKLE_BRIDGE_PYTHON" -m bridge.service install
"$PICKLE_BRIDGE_PYTHON" -m bridge.service status
```

`loaded: true`에 더해 `session`에 살아 있는 PID와 예상 주소가 표시되는지 확인합니다. 시작 직후 준비 중이면 `status`를 다시 확인하고 새 세션을 중복 시작하지 않습니다.

배포 후 운영 루트는 `~/Library/Application Support/PickleHermesBridge`이며 소스 `.runtime`은 같은 상태로 연결됩니다. 노트 자료는 이동·복사하지 않습니다. **설정 도우미 `tools/`는 소스 저장소에만 있으므로 동의 설정을 나중에 바꿀 때도 소스 루트에서 실행**합니다. 운영 명령은 설치 루트에서 실행할 수 있습니다.

```sh
cd "$HOME/Library/Application Support/PickleHermesBridge"
"$PICKLE_BRIDGE_PYTHON" -m bridge.service status
# 필요할 때만 중지 또는 재시작
"$PICKLE_BRIDGE_PYTHON" -m bridge.service stop
"$PICKLE_BRIDGE_PYTHON" -m bridge.service start
```

`stop`은 로그인 자동 시작·자동 재시작까지 중지합니다. supervisor만 kill하면 launchd가 되살릴 수 있습니다. Mac 전원·로그인·잠금 해제와 인터넷 연결은 여전히 필요합니다.

## 선택: 허용된 파일의 자동 첨부

[파일 요청 설정과 시험](ATTACHMENTS.md)을 따릅니다. 기본 설치에는 허용된 폴더가 없습니다. 소유자가 직접 정한 채널·자료 범위만 로컬 정책에 저장하고 가상 MD·이미지로 먼저 왕복을 확인합니다. 이 기능은 일반 질문의 최소 답변·질문별 허락을 포괄 해제하지 않습니다.

## 기존 설치 업데이트

먼저 실제 전달·질문 처리가 끝났는지 확인합니다. 기존 `.runtime`을 삭제하거나 `setup_local.py`를 다시 실행하지 않습니다.

1. 설치 루트에서 `bridge.service stop`으로 중지합니다.
2. 자신의 **소스 체크아웃**으로 이동해 변경 사항을 검토하고 `git pull --ff-only`로 갱신합니다. 로컬 수정이 있으면 강제로 덮어쓰지 않습니다.
3. 소스 루트에서 `bridge.deploy` → `bridge.service install` → `bridge.service status`를 같은 Hermes Python으로 실행합니다.
4. 스킬 변경도 검토해 설치본에 반영하고 새 가상 업무로 확인합니다. 기존 비밀값·기능별 동의·노트 경로는 유지합니다.

임시 수동 세션만 사용하는 설치는 `bridge.session stop` 뒤 소스를 갱신하고 `bridge.session start`로 다시 시작합니다.

## 문제 해결

| 증상 | 확인·다음 행동 |
|---|---|
| 저장소를 찾을 수 없음 / 404 | 저장소 URL과 네트워크 접근을 확인. 현재 Private 검토 상태와 계정 접근권 확인 |
| Python 또는 Hermes 경로 없음 | 2단계 경로를 실제 소스 설치 환경으로 수정. Desktop 앱 경로를 추측하지 않음 |
| `Existing private state` | 기존 설치가 있음. 초기화 반복 대신 업데이트 절차 사용 |
| 포트 사용 중 / supervisor 존재 | 기존 설치·서비스부터 확인. 프로세스를 임의로 죽여 새 인스턴스를 겹쳐 띄우지 않음 |
| 설정 도우미가 없음 | `tools/`는 소스 체크아웃에서 실행. 설치 루트에는 복사하지 않음 |
| `exactly_one…` / 피클 창 확인 실패 | 본인 채팅 하나와 빈 입력란을 유지. 다른 화면·로그인·업데이트·잠금 여부 확인 |
| 앱은 켜졌지만 붙여넣기 실패 | 완전 재실행 직후 문제일 수 있음. 동의한 경우에만 시작 준비 옵션 사용. 전면 입력으로 임의 우회하지 않음 |
| `preparing` / `sending` / `sent_unconfirmed` | 중복 전달 금지. 실제 화면과 기존 상태·비공개 기록 확인 |
| `prepared` | 미전송 입력이 정확히 일치할 때만 같은 작업을 resume 가능 |
| 업무 `needs_user` | 추가 답변 대기. 질문별 허락 후 답을 받으면 같은 업무에서 완료 |
| 질문 `draft` | 허락 후 Pickle 비서가 activate했는지 확인. 수동 grant로 우회하지 않음 |
| 질문 `denied` | 실제 질문·이번 번호·사용자 허락의 연결과 화면 작성자 확인 |
| 같은 직접 질문이 다시 거절됨 | 문구를 한 번 소비함. ‘다시’를 포함한 새 지시나 새 번호 뒤 허락 필요 |
| 결과 없음 | 지정 자료에 없다는 뜻. 캘린더나 Telegram 기록을 조회한 것으로 해석하지 않음 |
| ngrok 연결 실패 | 자신의 계정·주소·네트워크·한도와 비공개 로그 확인 |

비공개 로그는 `.runtime/`에 있습니다. 이슈에는 토큰·업무/질문 링크·DB·원문·개인 캡처를 붙이지 말고 오류명과 단계만 전달하세요.

## 참고할 운영 경계

- 화면 기반 허락은 암호학적 인증이 아니며 기존 Hermes 기억을 완전히 격리하지 않습니다. [SECURITY](../SECURITY.md)를 읽으세요.
- 답변 프롬프트에 들어 있는 `AGENTS.md`, `_System/00000 Home.md`, MOC는 원래 운영자의 노트 관례입니다. 자신의 자료에 없다면 모델이 읽었다고 가정하지 않습니다. 실제 볼트를 연결하기 전 자료 구조와 운영 규칙을 검토하세요.
- 현재 상대 날짜 해석은 `Asia/Seoul`입니다. 다른 시간대는 질문 worker를 검토해야 합니다.
- Telegram 상태 알림 봇은 선택 사항이며 기본 연결에 필요하지 않습니다. 원하면 별도 봇의 토큰·본인 chat ID를 소유자 전용 `.runtime/telegram.json`에 직접 저장합니다. 기존 Hermes 봇 토큰·웹훅·폴링은 변경하지 않습니다.
- 새 Mac 전체 설치는 미검증입니다. 문서의 절차 점검·자동 테스트·원래 Mac 왕복 성공을 새 환경 성공으로 확대하지 않습니다.

# 설치 전 자동 점검

`tools/preflight.py`는 설치 환경·비공개 설정의 존재와 형식만 읽는다. 앱/서버/터널을 켜거나 끄지 않고, 설치·권한 변경·파일 수정·모델 호출·화면 캡처·클립보드 사용·노트 내용 조회·외부 API 요청을 하지 않는다. 포트 충돌 확인은 로컬 127.0.0.1 TCP 연결만 사용한다. Hermes Python 버전/설치 메타데이터 확인은 `-I -S` 격리 subprocess에서 표준 라이브러리만 실행하며 Hermes·AppKit 자체를 import하지 않는다.

## 명령

저장소 루트에서 실행한다. Python 경로를 아직 찾지 못했다면 `python3 tools/preflight.py`로 시작할 수 있고, 실제 설치·네이티브 의존성에는 확인된 Hermes Python 3.11 이상이 필요하다.

```sh
python3 tools/preflight.py
```

기존 경로를 알고 있다면 실제 값을 지정할 수 있다. 실제 경로는 로컬에서만 사용하고 공유 로그에 넣지 않는다.

```sh
"$PICKLE_BRIDGE_PYTHON" tools/preflight.py --hermes-root "$PICKLE_BRIDGE_HERMES_ROOT" --json
```

비공개 설정을 만든 뒤에는 다음을 실행한다. 파일 전달/자동 입력을 소유자가 선택한 경우에만 관련 플래그를 추가한다. 이 플래그는 점검 대상 선택이며 기능 활성화나 동의가 아니다.

```sh
"$PICKLE_BRIDGE_PYTHON" tools/preflight.py --phase configured --json
# 파일 전달과 자동 입력을 실제로 선택한 경우:
"$PICKLE_BRIDGE_PYTHON" tools/preflight.py --phase configured --with-files --automatic-delivery --json
```

Pickle 설치본이 여러 개이거나 기본 Applications 폴더 밖에 있다면 실제 .app 경로를 `--pickle-app`으로 지정한다. App Store의 iPhone 앱 Wrapper 구조도 bundle ID로 확인한다. 앱을 실행하거나 로그인 여부를 확인하는 명령은 아니다.

## 결과 해석

| 상태 | 뜻 |
|---|---|
| `pass` | 해당 정적 점검만 통과. 실제 UI/연결 성공을 뜻하지 않음 |
| `warn` | 준비 단계의 누락 또는 호환성 위험. 다음 조치를 확인 |
| `block` | 지원 환경·필수 구성 또는 설정 안전성 문제. 해결 전 다음 연결/서비스 시작을 진행하지 않음 |
| `manual` | 실제 드라이버/화면/계정에서 별도로 확인할 항목 |

종료 코드 1은 자동 차단 항목이 있다는 뜻이다. 종료 코드 0은 자동 차단 항목이 없다는 뜻일 뿐 **설치 완료나 정상 작동이 아니다.** JSON의 `end_to_end_verified`는 항상 false다. `automatic_blockers`와 각 항목의 `next_step`, manual 항목을 읽고 실제 설치 절차를 이어간다.

기본 `prerequisites` 단계에서는 아직 만들지 않은 설정을 경고로 표시한다. `configured` 단계에서는 빠진 필수 설정을 차단한다. 포트가 이미 사용 중이면 새 설치는 차단하고, 상태 폴더가 있는 설치는 기존 서비스인지 검토하도록 표시한다. 상태 폴더가 있다는 이유만으로 포트 소유권을 증명하지 않으며 자동 종료/재시작하지 않는다.

## 확인하는 항목과 한계

- macOS·Apple Silicon(Rosetta에서도 하드웨어 확인)·macOS 14 이상.
- Hermes 소스 구조·Python 3.11 이상·Cocoa 13.0 설치 메타데이터·주요 내부 함수 정의·브리지 snapshot 어댑터가 요구하는 캡처 함수. Hermes 원본에 별도의 snapshot ID 저장 패치가 있는지는 필수 조건이 아니다. 정적 함수 존재만으로 모든 Hermes/driver 버전 호환성을 보장하지 않는다.
- Pickle bundle ID 및 설치본 선택. App Store 지역/계정 배포·다운로드·로그인은 실제 화면에서 확인한다.
- 상태 폴더·설정 파일의 소유자/비공개 권한, 자료 source 폴더의 존재. 노트 본문을 열거나 전체 폴더를 재귀 검색하지 않는다.
- ngrok 실행 파일·터널 설정 형식·인증 파일의 존재/권한. 토큰 자체를 읽거나 출력하지 않고 실제 인증 성공도 판정하지 않는다.
- 설치 때 정한 질문 허락 문구의 유효성. 설정을 생성·변경하거나 승인을 주입하지 않는다.
- 선택한 자동 입력 동의, 즐겨찾기 바인딩의 실제 폴더/순서 형식·메신저 임시 폴더 범위·선택된 상시 파일 컬렉션의 기본 경로 범위. 즐겨찾기가 UI에서 그 순서로 보이는지, 개별 파일 전송이 허락됐는지는 별도 확인한다.
- 고정 포트 8766/4041의 사용 여부.

화면 기록·접근성 권한은 실제 computer-use 드라이버 프로세스에 적용되므로 이 Python 프로세스의 권한을 조회해 대신 정상이라고 말하지 않는다. 에이전트는 `manual` 항목을 숨기지 말고 doctor·가상 UI 캡처·질문 허락/거절·파일 수신·원하는 자동 시작을 실제 설치에서 확인해야 한다.

표준 출력에는 실제 계정·폴더명·파일 목록·연결 주소·토큰·설정 원문·예외 본문을 넣지 않는다. 그래도 `pass`가 보안 보증이나 OS 샌드박스는 아니다. 원래 설정과 보안 경계는 [SECURITY](../SECURITY.md)를 따른다.

화면 응답 보완의 범위와 실제 검증 한계는 [Hermes 호환성](HERMES_COMPATIBILITY.md)을 참고한다.

# Agent entry point

이 저장소는 Mac의 Pickle 앱과 기존 Hermes 비서를 연결하는 브리지다.

- **설치·연결·설정·업데이트 요청:** 먼저 [docs/AGENT_INSTALL.md](docs/AGENT_INSTALL.md)를 읽고 해당 경로를 끝까지 수행한다. 안내만 설명하고 실행을 끝내지 않는다.
- **코드·문서 수정 요청:** 요청한 변경만 수행한다. 설치 지침이 있다는 이유로 현재 Mac의 서비스·앱·권한을 변경하지 않는다.
- 권한·비밀값 처리는 [SECURITY.md](SECURITY.md), 실제 명령과 성공 기준은 [docs/SETUP.md](docs/SETUP.md), Hermes 위임 동작은 [skills/pickle-delegation/SKILL.md](skills/pickle-delegation/SKILL.md)를 따른다.
- 기존 설치·노트·모델 설정을 보존하고 `.runtime`·토큰·개인 자료·로그·캡처는 커밋하지 않는다. 검색과 로그는 필요한 범위부터 읽고 비밀값은 출력하지 않는다.
- 문서나 스킬 자체는 사용자 동의가 아니다. 현재 사용자 요청과 이전에 실제 받은 동의 범위를 적용하며 같은 동의를 반복해서 묻지 않는다.
- 변경 검증: `tools/check_public.py`, 변경에 맞는 테스트, `git diff --check`. 프로젝트의 Python 경로는 설치 환경에서 확인하고 Mac 기본 `python3`라고 가정하지 않는다.

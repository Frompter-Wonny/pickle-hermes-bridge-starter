# 허용된 로컬 파일 요청과 첨부

이 기능은 Pickle 비서가 요청한 원본 파일을 Mac 앱 채팅에 첨부한다. 파일을 HTTP로 내려받게 하거나 볼트 전체 접근권을 주지 않는다. 기본 설치에는 허용된 폴더가 없으므로 파일 요청은 거절된다. 먼저 소유자가 특정 수신 대상과 자료 범위를 직접 허락해야 한다.

## 로컬 설정

운영 `.runtime/attachment_policy.json`에 다음 형식으로 저장한다. 파일 권한은 `0600`으로 유지하고 Git·공유 문서에 넣지 않는다. `channel_digest`는 실제 `Inbox.digest(channel_capability)`이며 capability 원문을 문서·터미널 출력에 남기지 않는다. 폴더는 `Path.resolve()`로 구한 절대 경로를 사용한다. 심볼릭 링크 경로는 거절된다.

```json
{
  "enabled": true,
  "destination": "pickle_own_chat",
  "channel_digest": "operator-configured-channel-sha256",
  "root_volume_label": "Macintosh HD",
  "max_file_bytes": 20971520,
  "collections": [
    {
      "id": "approved-documents",
      "root": "/absolute/operator-approved/folder",
      "filename_pattern": "example-[0-9]+\\.md",
      "extensions": [".md"],
      "recursive": false
    }
  ]
}
```

예제 경로를 실제 사용자의 자료로 임의 치환해 활성화하지 않는다. 허락받은 폴더와 파일 이름 패턴만 설정한다. 이미지 하위 폴더는 별도 컬렉션과 이미지 확장자 목록으로 좁혀 지정한다. `enabled: false` 또는 컬렉션 삭제로 이후 전송을 중단할 수 있다. 이미 전송된 파일을 회수하는 기능은 아니다.

`root_volume_label`은 실제 파일 선택창 위치 메뉴에서 확인한 시스템 볼륨 이름이다. 즐겨찾기 바인딩이 없을 때 기존 실행기는 이 볼륨의 루트에서 경로를 탐색하며 한국어/영어의 일부 macOS 폴더 이름을 처리한다. 다른 볼륨·언어·숨김 폴더는 검증 없이 지원한다고 가정하지 않는다.

## 폴더 목록 권한과 새 파일

macOS 상시 서비스에서 Documents 폴더 나열이 거절되지만 알려진 파일 접근은 가능한 경우가 있다. 그때는 소유자의 허락 범위가 이미 저장된 정책을 유지한 채, 해당 폴더에 접근 가능한 Hermes 비서 터미널/로컬 세션에서 다음을 실행해 각 컬렉션의 `files` 상대 파일명 목록을 만든다. 원문을 복사하거나 OS 권한을 변경하지 않는다.

```sh
python3 -m bridge.attachment_policy refresh
```

새 파일이 추가되면 이 목록도 갱신해야 한다. 자동 스캐너는 없다. 사용자가 허락한 새 회차/이미지 요청에서 목록에 파일이 없으면 운영 Hermes 비서가 위 갱신을 실행하고 다시 확인한다. 이 명령은 기존 root·이름 패턴·확장자·수신 채널을 확대하지 않는다. 폴더 자체를 읽을 수 없으면 권한을 자동으로 우회하지 않고 실패한다.

## 요청 프로토콜

기존 inbox URL을 `INBOX`라고 할 때:

| 요청 | 결과 |
|---|---|
| `GET INBOX/files` | 허용된 파일의 `id`, `name`, `collection`. 로컬 경로·내용은 없음 |
| `POST INBOX/files`에 `{"client_request_id":"unique","file_id":"catalog-id"}` | 요청 ID, filename, marker, activate/result URL |
| 파일명과 marker를 비서 말풍선 하나에 표시한 뒤 `POST activate_url`에 `{}` | 처리 대기 |
| `GET result_url` | 현재 전송 상태만 반환 |

등록·activate 자체는 권한을 만들지 않는다. 수신 채널에 대해 소유자가 저장한 정책을 다시 확인하고, 실제 Pickle 채팅에서 요청 파일명과 `BRIDGE-F:` marker를 대조한다. 일반 `/inbox` 질문 처리의 최소 텍스트 답변 경로와 분리되어 있다. 새 프로토콜을 Pickle에 적용하려면 이미 완료한 설정 작업을 재전송하지 말고 `bridge.configure --force`로 새 설정 작업을 발행한 뒤 기존 전달 절차를 따른다.

워커는 유휴 상태에서 SQLite만 확인한다. 기존 업무 전달과 같은 파일 잠금을 사용하므로 동시에 입력하지 않는다. 한 파일씩 고정된 background computer-use 동작으로 실제 폴더·파일을 열며, 일반 키보드·클립보드·전면 활성화를 사용하지 않는다. 파일 선택창을 이미 다른 작업이 열었거나 사용자 초안이 있으면 중단한다.

## 상태와 검증

`draft → queued → verifying → opening → attached → sending → sent_unconfirmed → confirmed` 순서다. `confirmed`만 실제 수신까지 확인한 상태다. `opening`부터는 앱에 업로드되었을 수 있다. 오류나 재시작 후 이 상태들을 자동 재실행하지 않으며, 미완료·불확실한 같은 파일을 새 요청 ID로 중복 요청하는 것도 차단한다. 최대 대기 시간을 넘으면 원래 요청의 상태를 확인한다.

파일 목록 밖의 요청, 철회·만료된 채널, 범위 밖 심볼릭 링크, 중복 요청·불확실 전송, 사용자 초안·초점 변경에 대한 거절을 테스트한다. 실제 설치에서는 가상 MD와 이미지로 요청→화면 검증→첨부→수신 확인을 검증한 뒤 허락된 실제 자료에 적용한다. 파일 전달은 공개 게시·예약의 허락을 대신하지 않는다.

계층 보기의 폴더 탐색은 AXBrowser의 가장 오른쪽 AXList(현재 폴더의 내용 열) 안에서만 수행한다. 상위 경로와 현재 폴더에 같은 이름이 있더라도 왼쪽 열의 항목을 선택하지 않는다. 왼쪽에서 오른쪽으로 배치된 macOS 계층 보기를 전제로 하며 다른 배치·목록 보기로 임의 추측하지 않는다. 파일을 열기 전 실패 시에는 이번 실행이 연 유일한 선택창만 취소한다. 초점 변경·업로드 시작 이후에는 이 정리도 자동 수행하지 않는다.


설치 단계의 사용자 질문·즐겨찾기 추가·검증은 [폴더 즐겨찾기 설정](FOLDER_FAVORITES.md)을 따른다.

## 즐겨찾기로 파일 선택

운영자가 파일 선택창에서 허락된 폴더를 즐겨찾기에 추가하고 실제 위치와 순서를 확인한 뒤, 비공개 `.runtime/file_picker_favorites.json`에 저장한다. 이 설정은 탐색 단축이며 파일 접근 허락을 추가하지 않는다.

```json
{
  "favorites": [
    {"root": "/absolute/operator-approved/folder", "ordinal": 0}
  ]
}
```

`ordinal`은 최근 항목 다음 첫 즐겨찾기 그룹에서의 0부터 시작하는 순서다. 실제 UI를 보고 정하며 추측하지 않는다. 메신저 사본용 `~/PickleUploadStaging`와 사전 허용된 자료 폴더를 각각 바인딩할 수 있다. 공유 저장소에는 실제 폴더·순서를 넣지 않는다.

실행기는 가장 가까운 승인된 상위 폴더의 즐겨찾기를 한 번 선택하고, 위치 메뉴의 폴더명과 전체 상위 경로를 검증한 뒤 필요한 하위 폴더와 정확한 파일만 선택한다. 즐겨찾기를 이동·삭제하거나 순서를 바꾸면 잘못된 파일을 열지 않고 중단하므로 실제 UI를 재확인해 설정을 갱신한다. 화면 밖 항목은 제한된 횟수만 스크롤하며 선택 여부를 확인한다.

## 메신저 첨부의 고정 로컬 실행기

사용자가 특정 수신 파일을 Pickle 비서에게 전달하라고 직접 지시했다면 스킬의 `scripts/stage_local_file.py`로 바이트가 같은 일반 폴더 사본을 만든다. 그 다음 `bridge.upload_local`의 `lookup → prepare → send → status`를 사용한다. 정확한 명령·비공개 지시 출처 파일·수신 확인 절차는 [로컬 파일 첨부 스킬](../skills/pickle-delegation/references/local-file-upload.md)을 따른다.

이 실행기는 즐겨찾기 설정을 요구하며 기존 워커와 같은 전달 잠금을 사용한다. 새 웹 API나 상시 파일 권한을 만들지 않는다. 같은 작업은 반복 전송하지 않고 불확실한 동일 파일 전송도 차단한다. 실제 Pickle 비서 수신을 화면에서 확인한 뒤에만 `confirm`하고 해당 사본을 정리한다. 원본과 즐겨찾기 폴더는 보존한다. 파일 선택을 매번 임의 computer-use 명령으로 재구성하지 않는다.

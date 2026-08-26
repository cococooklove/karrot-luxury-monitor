# daangn

```
pyuic6 MAIN.ui -o daangn/ui_mainwindow.py
uv run main.py
```

```
OUT.json: 지역 파일
scrap_area_code.py: 법정동 데이터를 이용해 당근에 요청하여 OUT.json을 생성
scrap_area_check.py: OUT.json 정합성 체크
```

## 알림 설정 (자동 모니터)

`자동 검색` 탭 → `알림 설정` 버튼.

| 항목 | 설명 |
|---|---|
| 텔레그램 토큰 | @BotFather 로 봇 생성 후 받은 `123456:AA...` |
| 텔레그램 방 | chat_id. 개인=양수, 그룹/채널=`-100...`. 봇에게 `/start` 또는 방 초대 먼저 |
| 구글시트 | 시트 URL (선택) |
| 시트 인증파일 | 구글 서비스계정 JSON 키. 시트를 그 계정 이메일과 **편집자**로 공유해야 함 |

- `테스트 발송` 으로 저장 전에 설정 검증 (실패 시 원인 표시 — 토큰오류/방오류/차단/권한).
- `저장` 하면 `notify.json`(권한 0600)에 기록 → 재시작해도 유지.
- 전송은 매물 여러 건을 한 메시지로 묶어 보냄(텔레그램 레이트리밋 회피).
  429 는 `retry_after` 만큼 대기 후 재전송, 실패는 로그에 반드시 표시.

테스트: `python notify_test.py`

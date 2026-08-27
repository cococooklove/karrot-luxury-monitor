# 키워드 알림 엔드포인트 캡처 — 폴링을 푸시로 바꾸기

폴링(지역×키워드×주기)은 `daily_cap` 때문에 구조적으로 불가능하다.
키워드 알림을 계정마다 등록해 두면 **조회 요청 0으로 신규 매물을 즉시** 받는다.
등록/조회/삭제 엔드포인트를 캡처하면 계정 세팅 전체가 스크립트화된다.

## 이미 확보된 것 (data/capture.jsonl, 2026-08-27)

```
GET https://search-bff.kr.karrotmarket.com/api/v1/fleamarket/keyword/notification/info?keyword=샤넬
→ 200 {"keyword":"샤넬","isBannedKeyword":false,"isRegistered":false,"isNotificationBannedKeyword":false}
```

- 호스트가 **`search-bff`** = 검색과 동일 → **인증서 피닝 없음. Frida 불필요.**
- `OPTIONS` preflight 가 붙는다 = 앱 내 웹뷰 호출. 헤더 세트는 검색과 동일
  (`authorization` · `x-device-identity` · `x-user-agent` · `x-karrot-session-id` · `origin`/`referer`).
- `isRegistered` — 이미 등록된 키워드인지. 계정별 등록 상태 동기화에 그대로 쓴다.
- `isBannedKeyword` / `isNotificationBannedKeyword` — **알림 등록이 막힌 키워드가 존재한다.**
  브랜드셋을 등록 전에 이 엔드포인트로 선별해야 한다.

## 미캡처 (이번에 딸 것)

| 용도 | 예상 | 캡처 방법 |
|---|---|---|
| 등록 | `POST /api/v1/fleamarket/keyword/notification` | 검색 결과 상단 알림 벨 탭 |
| 목록 | `GET  /api/v1/fleamarket/keyword/notification(s)` | 나의 당근 → 키워드 알림 |
| 삭제 | `DELETE .../notification?keyword=` | 목록에서 키워드 삭제 |
| **개수 상한** | 400/422/429 응답 본문 | 상한 넘을 때까지 계속 추가 |

## OPTIONS 탐색은 안 통한다 (2026-08-27 실측)

앱 조작 없이 경로를 알아내려고 CORS 프리플라이트로 후보 42경로를 프로브했더니
**42/42 전부 `allow=DELETE,GET,HEAD,PATCH,POST,PUT`** 이 돌아왔다.
존재하지 않는 경로(`/api/v2/...`, `/keyword/alarm/...`)까지 전부 통과 →
이 서버의 프리플라이트는 **경로 존재 여부를 검증하지 않는다.** 탐색 수단으로 못 쓴다.

`tools/probe_keyword_endpoints.py` 는 이 위양성을 감지하면 `--write` 를 거부한다.
가짜 경로가 스펙에 들어가면 등록이 조용히 실패하기 때문이다.

→ **앱 조작 캡처 외에 우회로 없음.** 아래 절차대로 간다.

## 절차

준비물은 **mitmproxy + 기기 프록시 뿐.** `TOKEN_REFRESH_CAPTURE.md` 와 달리
`api.kr.karrotmarket.com` 을 건드리지 않으므로 Frida·루팅·탈옥 전부 불필요하다.

1. 캡처 시작

   ```bash
   mitmdump -s capture/karrot_dump.py --listen-port 8080
   ```

   기기 프록시 → `PC IP:8080`, mitm 루트 인증서 신뢰. (`SETUP_LDPLAYER.md` 3단계까지)

2. 앱에서 아래를 **순서대로** 조작한다. 각 조작이 요청 1건씩을 만든다.

   1. 중고거래 검색 `샤넬가방` → 결과 화면 상단 **알림 받기(벨)** 탭 → 등록 `POST`
   2. 나의 당근 → 설정 → **키워드 알림** 화면 진입 → 목록 `GET`
   3. 목록에서 방금 키워드 **삭제** → `DELETE`
   4. **상한 확인** — 키워드를 계속 추가한다. 더 안 되는 지점에서 나오는
      에러 응답이 상한값을 담고 있다. `APP_API.md` 에 적힌 대로 이 서버는
      422 에 필요 필드·허용값을 그대로 실어 준다.
   5. 동네 설정 화면에서 **알림 범위**(가까운/먼 동네) 변경 → 범위 파라미터 확인

3. 추출

   ```bash
   python3 tools/find_keyword_alert.py
   ```

   메서드별 대표 요청의 URL·body·응답 스키마를 뽑아준다. 토큰은 마스킹된다.
   `★ 상한 후보 키워드` 줄에 상한값 키가 표시된다.

## 캡처 안 될 때

- 후보 0건 → 스크립트가 캡처된 **호스트 분포**를 출력한다. `search-bff` 가 안 보이면
  프록시가 안 물린 것. `webapp` 만 보이면 알림이 다른 호스트로 갔다는 뜻이니 그 호스트를
  `capture/karrot_dump.py` 의 `HOST_MATCH` 에 추가한다.
- 등록 요청이 안 보이는데 앱에서는 등록됨 → 웹뷰가 아니라 네이티브 gRPC 경로일 수 있다.
  이 경우만 `api.kr.karrotmarket.com` 피닝 우회(`TOKEN_REFRESH_CAPTURE.md` 2단계)가 필요하다.

## 파이프라인 (구현 완료)

```
build_keyword_set.py   브랜드×접미어 220개 생성        → data/keywords_luxury.json
        ↓
screen_keywords.py     info 로 금지 키워드 제거         → data/keywords_screened.json   [지금 실행 가능]
        ↓
setup_keyword_alerts.py 계정별 등록 + 상한 실측         → data/alert_assignments.json   [등록 경로 캡처 필요]
        ↓
notification_listener.py adb 알림함 폴링                → data/alert_hits.jsonl
        ↓
alert_pipeline.py      알림 → 앱검색으로 매물 해석      → data/listings_luxury.jsonl
```

```bash
python3 tools/selftest_alert.py          # 오프라인 회귀 게이트 (네트워크·adb 불필요)
python3 tools/build_keyword_set.py       # 220개 (--tier 1 이면 80개)
python3 tools/screen_keywords.py --limit 20
python3 -m collector.keyword_alert learn # 캡처 후 등록/목록/삭제 경로 자동 주입
python3 tools/setup_keyword_alerts.py --probe-cap   # 계정당 상한 실측
python3 tools/notification_listener.py --all &
python3 collector/alert_pipeline.py
```

`accounts.json` 에 계정별 동네가 있어야 알림→매물 해석이 된다:
`{"name":"acc1", ..., "region_id":"6128", "lat":37.498, "lon":127.026}`

## 남는 것

- 알림 누락 대비로 웹 SSR 저빈도 스윕(1일 1회)을 대조군으로 남긴다.
  알림을 100% 신뢰하면 당근이 억제할 때 조용히 구멍이 난다.

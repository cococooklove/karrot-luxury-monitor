# 당근 중고거래 명품 매물 수집

토큰 요청 차단 원인 특정 → 우회 → 매물 수집/모니터. 전 파이프라인 완성됨.
계획: `~/.claude/plans/replicated-baking-whistle.md`

> ⚠️ 당근 약관은 자동 수집 금지. 공식 파트너/광고 API 있으면 그 경로가 정석. 사용 책임은 운영자.

## 구조
```
capture/
  karrot_dump.py        mitmproxy 애드온: 앱 트래픽 → data/capture.jsonl
  frida/ssl_unpin.js    cert pinning 우회
  frida/sign_hook.js    동적 서명 함수 후킹 + RPC
tools/
  build_keyword_set.py       브랜드×접미어 알림 키워드셋 생성
  screen_keywords.py         info 로 등록가능 키워드 선별 (금지 키워드 제거)
  probe_keyword_endpoints.py OPTIONS 프리플라이트로 등록/목록 경로 탐색
  find_keyword_alert.py      캡처에서 알림 요청 추출
  setup_keyword_alerts.py    계정별 알림 등록 + 상한 실측
  notification_listener.py   adb 알림함 폴링 → 매물 신호
  selftest_alert.py          알림 파이프라인 오프라인 회귀 게이트
  analyze_capture.py    ★ 차단 원인 자동 리포트 (mine.json 불필요)
  diff_requests.py      성공요청 vs 내요청 수동 diff
  extract_token.py      인증/디바이스 헤더 추출 → data/config.json
collector/
  keyword_alert.py      ★ 키워드 알림 API — 폴링을 푸시로 (info 확정 / 등록·목록 캡처대기)
  app_search.py         앱 API v5 중고거래 검색 (spatialContext 2곳 + pageToken)
  alert_pipeline.py     알림 → 매물 해석 → 정규화 저장
  karrot_api.py         공유 클라: 헤더 재현 + 레이트제한 + (옵션)Frida서명
  parse.py              응답 JSON → 매물 정규화 (MAP 한번 맞추면 끝)
  collect_listings.py   지역별 페이지 순회 수집
  monitor.py            신규 매물 폴링 + 스냅샷 diff 알림
  replay.py             단건 재생 (차단 뚫리는지 검증)
```

## 설치
```bash
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -r requirements.txt
```
> 시스템 `pip` shebang 깨졌으면(bad interpreter) 항상 `python3 -m pip` 사용.
> venv 안에선 정상.

## 실행 순서

### Phase 0 — 원인 특정 (네 기기 필요)
```bash
mitmdump -s capture/karrot_dump.py --listen-port 8080
```
- LD플레이어/기기 프록시 → `PC IP:8080`, mitm 루트 인증서 시스템 신뢰
- pinning 이면: `frida -U -f <패키지> -l capture/frida/ssl_unpin.js`
- 실제 앱으로 **같은 지역 매물 조회 2~3회** → `data/capture.jsonl` 축적
```bash
python tools/analyze_capture.py     # ★ 차단 원인 한눈에
```

### Phase 1 — 우회 (analyze 결과대로)
| 결과 | 대응 |
|---|---|
| 디바이스/앱버전/서명 헤더 빠짐 (값 고정) | 그대로 진행 — karrot_api 가 헤더 재현 |
| "매번 변함" 헤더 존재 | `frida -U <앱> -l capture/frida/sign_hook.js` → `discover("sign")` 로 서명함수 특정 → sign_hook CONFIG 채움 → `KARROT_FRIDA=1` |
| 무결성(에뮬 로그인 실패/integrity 헤더) | 실기기 / 에뮬은 Magisk+PlayIntegrityFix |
| 429 패턴 | karrot_api 랜덤 지연 기본 적용 |

검증:
```bash
python collector/replay.py "<path>"    # 200 뜨면 우회 성공
```

### Phase 2 — 수집
```bash
# 응답 스키마 확인 후 collector/parse.py MAP 필드 1회 조정
python collector/collect_listings.py --path "<path>" \
    --region-param region_id --region 1234 --page-param page --pages 5
```

### Phase 3 — 신규 모니터
```bash
python collector/monitor.py --path "<path>" \
    --region-param region_id --regions 1234 5678 --interval 300
```
알림 연동은 `monitor.py` 의 `notify()` 에 웹훅 추가.

## 지금 막힌 것
- mitmproxy 캡처는 네 기기에서만 실행 가능 (여기선 물리 접근 없음).
- **`data/capture.jsonl` 붙여주면** analyze/parse MAP/서명헤더명까지 내가 확정.

## 클론 후 로컬 설정 (git 에 안 올라가는 파일)

자격증명은 저장소에 없음. 예시 파일을 복사해 채운다.

```bash
cd delivery/integrated/manual_gui
cp settings.example.txt settings.txt     # 1줄 간격, 2줄 동시요청, 3줄~ 프록시
cp proxies.example.txt  proxies.txt      # 테스트 스크립트용
# 알림은 GUI [알림 설정] 에서 입력 → notify.json 자동 생성 (권한 0600)
# 구글시트 쓰면 서비스계정 JSON 키를 credentials.json 으로 배치
```

`.gitignore` 로 제외되는 것: `settings.txt` `proxies.txt` `notify.json` `credentials.json`
`accounts.json` `data/config.json` `data/capture.jsonl` `*.db` `.venv/`

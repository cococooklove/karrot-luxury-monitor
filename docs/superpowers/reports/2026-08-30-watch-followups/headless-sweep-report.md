# 헤드리스 런타임 검색 스윕 배선

무인 서버 런타임(`_run_headless`)이 앱 슬롯 상한(약 30개)을 넘긴 키워드를 아무도
감시하지 않던 구멍을 막았다. GUI 는 `스윕` 라벨을 붙여 놓고 서버에서는 그 키워드를
훑는 주체가 없었다.

## 1. 만든 수명 — GUI 와 겹치는 곳 / 갈라지는 곳

### 공용(모듈 레벨, 두 런타임이 같은 함수를 쓴다)

| 함수 | 하는 일 | GUI 호출부 | 헤드리스 호출부 |
|---|---|---|---|
| `sweep_resync_action(want, have, running)` | 갈아끼울지 판정(`""`/`start`/`revive`/`restart`) | `MainWindow._resync_search_sweep` | `HeadlessSweepRunner.resync` |
| `sweep_conditions(entries, ...)` | 큐 엔트리 → 엔진 `conditions` | `MainWindow._sweep_cfg` | `headless_sweep_cfg` |
| `sweep_keyword_for(payload, keywords)` | 찾은 매물에 붙일 키워드 선택 | `MainWindow._on_sweep_found` | `_run_headless._sweep_found` |
| `sweep_found_to_match(payload, kw)` | 엔진 payload → watch 행 (기존) | 동일 | 동일 |
| `seed_router_from_server(router, list_fn, log, state)` | 첫 실행 서버 목록 인정 | `MainWindow._auto_poll_tick` | 헤드리스 루프 · `--register` 직전 |
| `harvest_token_quiet(path)` | LDPlayer 수확 후 최신 access | `MainWindow._harvest_token_quiet`(위임만 남김) | 스윕 cfg 의 `token_provider` |

판정 로직을 공유한 것이 핵심이다. `_resync_search_sweep` 의 분기를 그대로 옮겨
쓰면 "서버에서만 나는 버그"가 생긴다. 기존 GUI 동작·로그 문구("죽어 있음",
"키워드 변경")는 그대로 유지했고 `unified_tab_wiring_test.py` 123/123 이 그걸 지킨다.

### 일부러 갈라 둔 곳

- **cfg 조립**: `MainWindow._auto_cfg_base` 는 값을 **위젯**(`autoRestMin`,
  `autoAreaTree`, `_collect_proxies` → `self.controller.proxies`)에서 읽는다.
  위젯이 없는 런타임에서 그 함수를 부를 방법이 없다. 그래서 헤드리스는
  `headless_sweep_cfg(settings, entries, notify, ...)` 로 `data/alert_settings.json`
  에서 같은 키를 만든다. 기본값은 GUI 위젯 초기값과 일치시켰다(휴식 30~90초,
  지역간격 0.4~1.2초, 레인 자동, 끌올 7일). **조건 조립만은 공유**한다.
- **프록시**: GUI 는 컨트롤러가 이미 읽어 둔 목록을 쓴다. 헤드리스에는 컨트롤러가
  없어 `headless_proxies()` 가 `settings.txt`(controller 와 같은 포맷) +
  `accounts.json` 을 직접 읽는다. `proxy_provider` 로도 넘겨 실행 중 변경이 반영된다.
- **스레드**: GUI 는 `AutoMonitor(QThread)`, 헤드리스는 `threading.Thread(daemon=True)`.
  둘 다 같은 `SweepEngine` 을 돈다.
- **서버 목록 조회**: GUI 는 `_safe_alert_list`(단일 계정 API), 헤드리스는
  `_server_keyword_list`(첫 유효 계정으로 `KeywordAlertAPI.list()`). 등록은 전 계정에
  같은 키워드를 쓰므로 한 계정만 봐도 함대 상태를 안다.

### `HeadlessSweepRunner`

`start` / `stop(join=)` / `resync` / `running`. GUI 의 `_start_search_sweep` ·
`_stop_search_sweep` · `_resync_search_sweep` 를 그대로 옮긴 것이고, 로그 문구도
같다. `engine_factory` / `thread_factory` 로 테스트가 진짜 스레드·네트워크 없이
수명만 확인한다.

루프 1회당 순서(= GUI `_auto_poll_tick` 과 같다):
씨딩 → `router.rebalance()` → `sweep_runner.resync()` → 폴링 → 워치 스윕.
`resync` 는 루프 1회에 한 번뿐이라 대기열이 요동쳐도 재시작이 폴링 주기당
한 번을 넘지 않는다.

### 요청량 상한 (실 API 를 치는 코드다)

- `SWEEP_REVIVE_MAX = 5` — 엔진이 뜨자마자 죽는 상황(토큰 없음·프록시 전멸)에서
  틱마다 무한히 다시 띄우지 않는다. 5회 되살리고 포기하며 포기 로그는 한 번만
  남긴다. **대기열 키워드가 바뀌면** 상한이 풀린다(그건 정당한 재시작이다).
- `SEED_ATTEMPT_MAX = 3` — routes 가 비어 있고 서버 목록도 계속 비면 씨딩이 영원히
  안 끝난다. 시도 자체를 3회로 묶는다. routes 가 차 있으면 목록 조회조차 하지
  않으므로 첫 실행 뒤에는 공짜다.
- 재시작 자체가 `resync` 한 번에 최대 한 번.

### 종료

`while True` 를 `try: / finally:` 로 감쌌다. `--once`, `KeyboardInterrupt`, 예외
어느 경로로 나가도 `sweep_runner.stop(join=8)` 을 지난다. `--register --once`
조기 return 경로에도 같은 정리를 넣었다. 스레드는 `daemon=True` 라 join 이
초과해도 프로세스가 걸리지 않는다(그 경우 로그를 남긴다).

## 2. `--register` 가 라우터를 지난다

`m.register_all(LUXURY_BRANDS, ...)` 직접 호출 → `router.add_many(...)`.
키워드마다 결과 라우트를 로그에 남긴다:
`[등록] 샤넬 → sweep (앱 등록 실패…)`. 직접 호출은 라우터가 모르는 키워드를
서버에 만들어 상한 계산을 어긋나게 하고 스윕 대기열도 만들지 않았다.
등록 **직전**에 씨딩도 한다 — 이 브랜치 이전 경로로 서버가 이미 차 있으면
인정하지 않고 등록해봐야 전부 실패해 스윕으로 밀린다.

## 3. 씨딩을 폴링 틱에서

`seed_from_server` 는 GUI 에서 `_alert_populate`(명시적 새로고침·추가·삭제)에서만
불렸다. 8초 자동시작 경로는 곧장 `_auto_poll_tick` 으로 들어가 씨딩을 건너뛴다.
이제 두 런타임 모두 폴링 틱에서 `seed_router_from_server` 를 지난다.
`_alert_populate` 의 기존 씨딩은 그대로 뒀다(이미 목록을 들고 있어 더 싸다).

**남는 우려**: GUI 폴링 틱의 씨딩은 GUI 스레드에서 동기 HTTP 조회를 한다.
첫 실행에 최대 3회뿐이고 실패해도 삼키지만, 그동안 창이 잠깐 멈출 수 있다.
워커 스레드로 옮기려면 `_alert_run` 을 태워야 하는데 폴링 잡과 경합해서
이번엔 넣지 않았다.

## 4. git log --oneline -2

```
91ce52a feat: 헤드리스 런타임서 지역 스윕 실행
5b99620 fix: 슬롯 상한 관측을 추론이 아니라 실측으로 다시 만듦
```

(부모가 `e731f8f` 에서 `5b99620` 으로 바뀌었다 — 같은 워크트리에서 다른 에이전트가
`keyword_router.py` 작업을 중간에 커밋했다. 커밋 뒤 그 상태로
`headless_sweep_test` 101/101, `unified_tab_wiring_test` 123/123,
`article_watch_test` 177/177, `sweep_engine_test` 57/57 을 다시 확인했다.)

## 5. 테스트 결과 (실제 꼬리)

신규 `headless_sweep_test.py` (101 체크: 판정·조건조립·cfg·수명·되살리기 상한·
종료·on_found→watch·씨딩 상한·양쪽 런타임 배선·진짜 스레드):

```
=== M. 진짜 스레드로 — Qt 이벤트 루프 없이 돈다 ===
  [PASS] 진짜 스레드로 시작  
  [PASS] 엔진 run 진입  
  [PASS] 살아 있다고 보고  
  [PASS] on_found 가 스레드서 넘어옴  [{'id': 'T1', 'title': '샤넬 스레드', 'price': 1}]
  [PASS] 데몬 스레드(프로세스 종료를 안 막음)  
  [PASS] join 뒤 스레드 종료  
  [PASS] 엔진 run 정상 탈출  

===== 101/101 PASS =====
```

기존 스위트:

```
article_watch_test.py         ===== 177/177 PASS =====
unified_tab_wiring_test.py    ===== 123/123 PASS =====
article_watch_wiring_test.py  ===== 27/27 PASS =====
sweep_engine_test.py          ===== 57/57 PASS =====
supervisor_test.py            ===== 20/20 PASS =====
sweep_queue_test.py           ===== 29/29 PASS =====
watch_listing_test.py         ===== 47/47 PASS =====
backfill_test.py              ===== 26/26 PASS =====
notify_test.py                54/54 PASS
robust_test.py                29/29 PASS
```

(마지막 꼬리 원문 예: `article_watch_test.py`
```
  [PASS] 재등록 후 다시 기준선부터  
  [PASS] 판매완료·삭제(dead)는 재등록 안 함  

===== 177/177 PASS =====
```
`unified_tab_wiring_test.py`
```
  [PASS] 헤드리스가 dedupe_new_matches 를 쓴다  
  [PASS] 헤드리스에 fallback 집합이 있다  
  [PASS] 헤드리스 옛 FIFO 제거  
  [PASS] GUI 에 match_seen 파일 코드 없음  

===== 123/123 PASS =====
```
)

기존 실패(내 것 아님, 그대로): `full_test.py`, `_construct_test.py`,
`button_test.py`, `gui_func_test.py`.

## 6. 헤드리스 스모크

`QT_QPA_PLATFORM=offscreen python main.py --headless --once --no-harvest`
(`data/`·`accounts.json` 부재 — 대기열이 비어 스윕은 시작하지 않는 것이 정상):

```
[12:18:55] === 헤드리스 무인 모니터 시작 ===
[12:18:55] 전계정(0) 매칭 0건(중복제거)
[12:18:55] [매칭] 신규 0 (유효계정 0, 커버 전국)
[12:18:55] --once 완료
```

트레이스백 없음, 종료코드 0, 남는 스레드 없음.

대기열이 **찬** 경우까지 보려고, 엔진만 무해한 스텁으로 갈아끼운 스모크를
따로 돌렸다(실계정 요청 0건, `_run_headless` 본체는 그대로):

```
[12:19:29] === 헤드리스 무인 모니터 시작 ===
[12:19:29] 유효 계정 0개 (만료계정 제외)
[12:19:29] 전체: 등록 0 · 스킵 0 · 실패 0
[12:19:29]   샤넬: 검색 스윕으로 — 앱 등록 실패(차단 키워드·유효 계정 없음)
[12:19:29] 유효 계정 0개 (만료계정 제외)
[12:19:29] 전체: 등록 0 · 스킵 0 · 실패 0
[12:19:29]   구찌: 검색 스윕으로 — 앱 등록 실패(차단 키워드·유효 계정 없음)
[12:19:29] [스텁엔진] 조건 2개로 run() 진입
[12:19:29] [검색스윕] 시작 — 키워드 2개
[12:19:29] 전계정(0) 매칭 0건(중복제거)
[12:19:29] [매칭] 신규 0 (유효계정 0, 커버 전국)
[12:19:29] [검색스윕] 신규 매물 추적: 구찌 마몬트 스모크
[12:19:29] --once 완료
[12:19:29] [검색스윕] 정지 요청
[12:19:29] [스텁엔진] stop 플래그 확인 후 run() 종료
EXIT=0
```

`rebalance` → 스윕 시작 → `on_found` 가 `add_from_matches(..., source="sweep")`
로 watch 테이블에 도달 → `--once` 종료 시 엔진 정지까지 한 줄로 확인된다.
(이 스모크가 남긴 `data/sweep_queue.json` · `keyword_routes.json` · watch 행은
전부 되돌렸다.)

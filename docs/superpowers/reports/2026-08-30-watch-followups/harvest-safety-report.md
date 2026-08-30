# 수확 소유권 · accounts.json 동시쓰기 — Finding 1 / Finding 4 / 공통 근본

커밋 2개 (branch `watch-followups`): `47eff59`(1차) · `b148b63`(2차).
건드린 파일: `main.py`, `ld_autoharvest.py`, `harvest_safety_test.py`(신규),
`headless_sweep_test.py`, `unified_tab_wiring_test.py`, `.gitignore`.
`daangn_ext/keyword_router.py`, `daangn_ext/keyword_alert_api.py`,
`keyword_router_test.py` 는 다른 에이전트 소유라 손대지 않았다.
`daangn/sweep_engine.py` 는 **변경하지 않았다** — 이유는 아래 "잘라내지 않은 것".

---

## 1. 이제 수확은 누가 소유하는가

런타임마다 **하나**다.

| 런타임 | 수확 소유자 | 주기 | 스윕의 토큰 출처 |
|---|---|---|---|
| 헤드리스 | 폴링 루프의 `ld_autoharvest.harvest_all` | 1200초 | `read_token_quiet` — accounts.json 읽기만 |
| GUI | `_HarvestThread` (`main.py:549`, `__init__` 에서 기동) | 1200초 | `MainWindow._read_token_quiet` — 읽기만 |

두 런타임 모두 **전용 수확기 하나 + 읽기만 하는 스윕**이라는 같은 모양이 됐다.

### 헤드리스

이전에는 `token_provider=harvest_token_quiet` 가 스윕 cfg 로
들어가 `SweepEngine.run` 이 기동 시 1회 + **사이클마다** 함대 전체 수확을 돌렸고
(`daangn/sweep_engine.py:299-303`), 동시에 폴링 루프가 1200초마다 독립적으로
수확했다. 서버에서 두 스레드가 스케줄에 맞춰 `harvest_all` 을 동시에 돌리는
구조였다 — adb/에뮬레이터 중복 폭주이자 아래 3의 손상 창이며, "LDPlayer 인스턴스는
순차 기동, 동시 기동 금지"라는 운영 규칙 위반이다.

이제 헤드리스 스윕은 `read_token_quiet` 를 받는다. 파일만 읽고 가장 늦게 만료되는
access 를 돌려준다. 스윕이 필요한 건 *수확*이 아니라 *신선한 토큰*이고, 토큰을
신선하게 유지하는 일은 폴링 루프가 이미 한다.

`--no-harvest` 는 그대로 `token_provider=None` 이다. 아무도 갱신하지 않는 실행에서
provider 를 주면 `stabilize` 가 켜지며 기존 동작이 바뀌므로 게이트를 유지했다.
(`stabilize = bool(token_provider)` — `main.py:348`. 읽기전용 provider 여도
`stabilize` 는 그대로 True 가 된다: `harvest_safety_test` C 절에서 검증.)

### GUI

같은 대접을 했다. `_auto_cfg_base` 의 `token_provider` 가
`self._harvest_token_quiet` → `self._read_token_quiet`(파일 읽기 전용)로 바뀌었다.

처음 보고에서 나는 "GUI 는 그 provider 가 유일한 주기적 수확기라 못 자른다"고 썼는데
**틀렸다**. GUI 에는 이미 전용 수확기가 있다:

```
main.py:1047   self._harvest_thread = _HarvestThread(interval=1200, accounts="./accounts.json")
main.py:1048   self._harvest_thread.tick.connect(self._on_harvest_tick)
main.py:1049   self._harvest_thread.start()
```

`_HarvestThread`(`main.py:549`)는 `MainWindow.__init__` 에서 기동돼 1200초마다
`harvest_all` 을 돌린다 — 헤드리스 폴링 루프와 같은 주기다. 건강 표시줄도 그 상태를
읽는다(`main.py:1953-1954`). 즉 GUI 상황은 헤드리스와 동일했고, 스윕이 휴식주기
(30~90초)마다 함대를 통째로 다시 깨우는 것이 순전한 중복이었다. 이제 두 런타임
모두 프로세스당 수확 소유자가 정확히 하나다.

`stabilize` 는 `autoTokenRefresh` 체크박스에서 오므로 그대로다(헤드리스처럼
`bool(token_provider)` 에 묶여 있지 않다). `_HarvestThread` 는 체크박스와 무관하게
항상 돌므로, 체크박스를 꺼도 토큰 신선도는 예전과 같다.

수확이 남아 있는 GUI 경로는 `_alert_api()` 하나다 — 사용자가 등록·목록조회를 **직접**
눌렀을 때만 타고, 스케줄이 아니다. 방금 요청한 등록이 만료토큰으로 실패하지 않게
하는 경로라 남겼고, 프로세스 락이 `_HarvestThread` 와의 겹침을 직렬화한다.

### `stabilize` 가 깨지지 않는 이유 (자르기 전에 확인한 것)

`stabilize` 는 `AccountScheduler` 를 켠다. 스케줄러는 **자기가 accounts.json 을
다시 읽어** 계정을 라운드로빈하고(`sched.pick()` → `pick["access"]`), 토큰은
거기서 나온다. `sweep_engine.py:299-303` 의 `token_provider()` 호출은 반환값을
버린다 — 순전히 수확 부작용용이다. 즉 sched 경로가 provider 에게 기대하는 건
"accounts.json 을 신선하게 만들어 달라"이고, 그 일을 헤드리스에서는 폴링 루프가
한다. sched 미사용 경로(`:316-320`)는 provider 의 **반환값**을 쓰는데, 읽기전용
provider 가 정확히 그걸 준다. 어느 쪽도 깨지지 않는다.

### 잘라내지 않은 것

`sweep_engine.py:299-303` 의 사이클별 `token_provider()` 호출 **자체**는 남겼고
`daangn/sweep_engine.py` 는 한 줄도 바꾸지 않았다. 이제 두 런타임 모두 읽기전용
provider 를 넘기므로 그 호출은 값싼 파일 읽기다(sched 경로는 반환값을 버리고,
비-sched 경로는 그 값을 쓴다). 엔진에서 지우면 비-sched 경로가 토큰 갱신을 잃는다.

남은 흠 하나: `sweep_engine.py:301` 의 실패 로그 문구가 `[수확] 실패(계속)` 인데
이제 그 자리는 수확이 아니라 파일 읽기다. 엔진 파일을 건드리지 않기로 해서 두었고
아래 "남은 우려"에 적는다.

---

## 2. 씨딩 경로가 대신 하는 일 (Finding 1)

이전 경로:
`_auto_poll_tick`(QTimer 콜백 = GUI 스레드) → `seed_router_from_server(..., _safe_alert_list)`
→ `_alert_api()` → `_harvest_token_quiet()` → `harvest_all(nudge=True)`
→ (인스턴스 없으면) `ensure_ldplayer()` = LDPlayer 부팅 → 최대 16 에뮬레이터 팬아웃
→ 그 뒤 20초 타임아웃 HTTP `list()`. 전부 GUI 스레드.

바뀐 것 두 가지:

1. **싼 `list_fn`.** `MainWindow._quiet_keyword_list(core_only)` 를 새로 뒀다.
   헤드리스 `_server_keyword_list`(`main.py:4602`)와 같은 문이다 —
   `self._multi()._valid(core_only)` 로 살아있는 access 를 고르고, 첫 계정으로
   `KeywordAlertAPI(...).list()` 한 번, `finally` 에서 close. **수확 없음.**
   유효 계정이 없으면 조회조차 하지 않고 `{}` 를 돌려준다(= LDPlayer 를 깨우지
   않는다). 등록은 전 계정에 같은 키워드를 쓰므로 한 계정만 봐도 함대 상태를 안다.
2. **GUI 스레드에서 뺐다.** 씨딩과, 씨딩 결과에 의존하는 `router.rebalance` 를
   폴링 잡 안으로 옮겼다. 잡은 `_alert_run` → `_AlertWorker`(QThread)에서 돈다.
   로그는 위젯 직접 append 가 아니라 워커의 `log` 시그널로 나간다.

`_auto_poll_tick` 에 GUI 스레드로 남은 것: `supervisor.retune()`,
`_resync_search_sweep()`(QThread 를 만들고 세우는 일이라 워커로 못 옮긴다 — 대신
네트워크를 타지 않는다), 진행중 스킵 가드, `_alert_run` 디스패치.

순서 변화 하나: 이전은 씨딩 → 승격 → 재동기화 → 폴링. 지금은 재동기화 →
[워커: 씨딩 → 승격 → 폴링]. 씨딩→승격 순서(승격이 씨딩에 기대는 부분)는 그대로다.
재동기화가 그 틱의 승격보다 앞서므로 승격 결과는 다음 틱 재동기화가 받는데,
`_resync_search_sweep` docstring 이 이미 인정하는 지연("아직 정지 중이면 다음 틱이
이어받는다")과 같은 성질이다. 요청량은 늘지 않는다.

부수 효과: 이전 폴링이 진행 중인 틱에서는 씨딩·승격도 건너뛴다. 라우터를 두 워커가
동시에 바꾸는 일이 없어져 더 안전하다.

---

## 3. 원자적 쓰기 (공통 근본)

`ld_autoharvest.merge_accounts` 는 고정 경로 `accounts.json.tmp` 에 쓰고
`os.replace` 했다. `os.replace` 는 원자적이지만 **그 임시파일의 내용은 아니다** —
두 수확이 같은 파일에 끼어 쓰면 뒤섞인 결과가 승격된다.

옛 구현을 느린 writer + 스레드 2개로 실제로 재현했다:

```
FileNotFoundError: ... '/tmp/.../accounts.json.tmp' -> '/tmp/.../accounts.json'
OLD parses: True  codes: {'AAA111'}  both present? False
```

한 스레드는 상대가 먼저 승격해 사라진 tmp 때문에 죽었고, 살아남은 파일은 파싱은
되지만 `BBB222` 계정이 통째로 없다. 재발급 불가능한 세션 하나가 사라지는 것이다.

바꾼 것:

- `_atomic_write_json(fp, data)` — `tempfile.mkstemp(dir=대상 디렉터리)` 로 **고유**
  임시파일(같은 파일시스템 유지 → `os.replace` 가 원자적), `flush` + `os.fsync`,
  그 뒤 `os.replace`. 실패하면 임시파일을 지우고 예외를 올린다(원본은 그대로).
- `merge_accounts` 는 `_MERGE_LOCK` 을 잡고 `_merge_accounts_locked` 를 부른다.
  임시파일만 고유하게 만들면 손상은 막지만 **읽기-병합-쓰기의 lost update** 는
  못 막는다(둘 다 옛 base 를 읽고 나중 쓰기가 앞선 삽입을 덮는다). 락이 그걸 막는다.
- `harvest_all` 은 `_HARVEST_LOCK` 을 잡고 `_harvest_all_locked` 를 부른다.
  한 프로세스 안에서 두 스레드가 아예 동시에 수확하지 못한다 — 뒤쪽은 기다렸다가
  갱신된 파일 위에서 병합한다. `ensure_ldplayer` 동시 호출도 함께 막힌다.

해피패스 동작은 그대로다: 같은 dedupe, 같은 갱신/삽입 판정, 같은 스키마,
같은 `(upd, ins, len(base))` 반환.

### 프로세스 간 락 — 문서화가 아니라 닫았다

스레드 락은 한 프로세스 안에서만 유효하다. 그리고 두 프로세스는 실제로 겹친다:
클라 PC 가 GUI 를 띄운 채 헤드리스 런타임을 돌리는 상황(테스트·이관 중)이 그것이다.
여기서 lost update 는 "방금 수확한 토큰이 조용히 사라지고 그 계정은 다음 갱신에서
죽는다"를 뜻하고, 복구 경로는 폰 앱 스택뿐이다. 그래서 닫았다.

`merge_accounts` 는 이제 `_MERGE_LOCK`(스레드) **안쪽에** 사이드카 파일락을 한 겹 더
잡고, 그 임계구역 안에서 base 를 읽는다. 잠근 뒤에 읽는 순서가 핵심이다 — base 를
읽고 나서 잠그면 이미 늦다.

- 대상: `accounts.json.lock` 사이드카. `accounts.json` 자체를 잠그면 안 된다 —
  `os.replace` 로 갈아끼워져 inode 가 바뀌므로 거기 건 락은 다음 writer 에게 보이지 않는다.
- POSIX(개발 Mac): `fcntl.flock(fd, LOCK_EX | LOCK_NB)` 를 50ms 폴링으로 재시도.
- Windows(배포 대상): `msvcrt.locking(fd, LK_NBLCK, 1)` — 즉시 실패하는 비블로킹
  변형을 같은 폴링 루프에 넣었다. `os.lseek(fd, 0)` 로 위치를 맞춘 뒤 1바이트 구간을
  잠근다(EOF 너머 구간도 잠글 수 있다). 해제는 `LK_UNLCK`.
- 락 수단이 없는 플랫폼이면 조용히 넘어가지 않고 그 사실을 로그에 남기고 진행한다.
- `.gitignore` 에 `**/accounts.json.lock` 추가(런타임 산출물).

#### 스테일 락 정책

`flock` 과 `msvcrt.locking` 은 **파일핸들에 매달린 OS 락**이다. 프로세스가 죽으면
(정상 종료든 SIGKILL/TerminateProcess 든) 커널이 핸들을 닫으며 락을 즉시 놓는다.
락파일 **존재 여부**로 판정하는 프로토콜과 달리 영구 스테일이 구조적으로 없다 —
이게 이 방식을 고른 첫 번째 이유다. 테스트로도 확인했다(홀더를 kill 한 뒤 재획득).

남는 위험은 *살아 있는* 프로세스가 오래 쥐는 경우뿐이다. 여기서 무한 대기는
막으려던 lost update 보다 나쁘다 — 수확기가 통째로 멎으면 함대 전체 토큰이 만료된다.
그래서 **`LOCK_TIMEOUT = 20초`를 넘기면 크게 로그를 남기고 락 없이 진행한다**:

```
[수확] accounts.json 파일락 20초 대기 초과 — 다른 프로세스(GUI/헤드리스)가 쥔 채로
오래 있습니다. 락 없이 진행합니다(수확분이 덮일 수 있음).
```

이때 최악은 손상이 아니라 lost update 로 되돌아가는 것뿐이다(고유 임시파일 덕분).
즉 타임아웃은 안전성을 한 단계 낮출 뿐 깨뜨리지 않는다.

## 4. 검증

새 스위트 `harvest_safety_test.py` (68/68). 표명이 아니라 테스트로 증명한 것:

- **A. 동시 병합** — 청크 단위로 쪼개 쓰는 느린 writer 를 끼우고 스레드 2개로
  `merge_accounts` 동시 호출: 예외 없음, 결과 파싱됨, **두 writer 의 계정이 모두**
  남고 access/refresh 짝이 유지됨, 임시파일 잔여 없음, `accounts.json.tmp` 미사용.
  쓰기 실패 시 예외를 삼키지 않고 원본을 보존하며 임시파일을 청소하는 것까지.
- **B. 수확 락 직렬화** — 4스레드가 `harvest_all` 진입, 내부 동시 진입 최대치가 1,
  4회 전부 실행, 병렬이면 나올 수 없는 경과시간.
- **C. 스윕 provider 가 함대 수확을 트리거하지 않음(양쪽 런타임)** —
  `read_token_quiet` 호출 시 `harvest_all` 호출 0회, 가장 늦게 만료되는 access 반환,
  소스에 `harvest_all` 없음. 헤드리스: `_run_headless` 배선이 `read_token_quiet` 를
  쓰고 `harvest_token_quiet` 는 안 쓰며 폴링 루프의 `harvest_all` 은 남아 있음.
  GUI: `_auto_cfg_base` 가 `_read_token_quiet` 를 쓰고 `_harvest_token_quiet` 는 안
  쓰며, `MainWindow._read_token_quiet` 를 실제로 불러 `harvest_all` 호출 0회 확인.
  그리고 **`_HarvestThread` 가 여전히 토큰을 신선하게 유지한다**는 것 —
  `__init__` 에서 기동, `run` 이 `harvest_all` 을 소유, 기본 주기 1200초(헤드리스와
  동일), `__init__` 이 1200 을 붙임. 사용자 조작 경로 `_alert_api` 는 수확 유지.
- **D. 폴링 틱 씨딩** — GUI 스레드에서는 목록 조회도 승격도 일어나지 않고 잡만
  넘어간다. 잡을 별도 스레드에서 돌리면 그때 씨딩이 일어나고, **수확 호출 0회**,
  씨딩 스레드 ident 가 GUI 스레드와 다름, 라우터가 서버 키워드를 인정, 승격은 씨딩
  뒤, 폴링 결과 반환. 이전 폴링 진행 중이면 잡을 새로 띄우지 않음.
  `_quiet_keyword_list` 자체도 `_multi()` 를 수확 인자 없이 부르고 `_alert_api` 를
  쓰지 않으며 첫 유효계정의 토큰·프록시로 조회 후 close 한다.

- **E. 프로세스 간 락** — 실제 `subprocess` **두 개**(스레드 아님)를 띄워 GO 파일로
  동시에 출발시키고 느린 읽기(0.4초)로 read-modify-write 창을 겹치게 한 뒤:
  둘 다 정상 종료, 파일 파싱됨, **두 수확분 모두 남음(lost update 없음)**, 토큰 짝 유지,
  사이드카가 대상 파일과 별개. 홀더 프로세스가 락을 쥔 동안 `_try_lock` 이 False 를
  돌려주는 것(= 진짜 OS 락)까지 확인. 타임아웃 경로: 남이 쥔 상태에서
  `timeout=0.3` 으로 들어가면 예외 없이 `False` 를 받고 상한만큼만 기다린 뒤
  **블록을 실행**하며(멎지 않음), "대기 초과 … 락 없이 진행" 로그를 남긴다.
  스테일 정책: 홀더를 `kill()` 한 뒤 락이 재획득되는 것 확인.

이 스위트가 실효 테스트인지 각각 옛 동작으로 확인했다. 스레드 경합(A)은 위의
`FileNotFoundError` + 계정 소실이고, 프로세스 경합(E)은 `_file_lock` 만 무력화하면:

```
NO-FLOCK codes: {'PB2222'} -> both present? False
```

`PA1111` 의 수확분이 통째로 사라진다. 락을 되돌리면 둘 다 남는다.

기존 스위트 중 두 개의 단언을 갱신했다(개수 변동 없음):
`headless_sweep_test.py` — "틱이 `seed_router_from_server` 를 부른다"를
"틱의 씨딩은 GUI 스레드 밖(폴링 잡)에서 돈다"로(중첩 코드 오브젝트 검사, 동시에
GUI 스레드 co_names 에 없음을 요구), rebalance 검사는 잡까지 포함해 확인.
`unified_tab_wiring_test.py` — 폴링이 `_alert_run` 으로 나가므로 스텁 대상 변경.

### 실제 테일 (직접 실행해서 본 것)

```
### article_watch_test.py (rc=0)
===== 191/191 PASS =====
### unified_tab_wiring_test.py (rc=0)
===== 148/148 PASS =====
### headless_sweep_test.py (rc=0)
===== 101/101 PASS =====
### sweep_engine_test.py (rc=0)
===== 57/57 PASS =====
### watch_listing_test.py (rc=0)
===== 47/47 PASS =====
### article_watch_wiring_test.py (rc=0)
===== 27/27 PASS =====
### sweep_queue_test.py (rc=0)
===== 29/29 PASS =====
### supervisor_test.py (rc=0)
===== 20/20 PASS =====
### backfill_test.py (rc=0)
===== 26/26 PASS =====
### notify_test.py (rc=0)
54/54 PASS
### robust_test.py (rc=0)
29/29 PASS
### _construct_test.py (rc=0)
===== 9/9 PASS =====
### button_test.py (rc=0)
===== 30/30 PASS =====
### full_test.py (rc=0)
===== 17/17 PASS =====
### proxy_test.py (rc=0)
[SKIP] proxies.txt 없음(gitignore) — 실 프록시 연결성/스케일링 실측 생략.
===== 6/6 PASS =====
### e2e_chain_test.py (rc=0)
10/10 PASS
### _proxy_ui_test.py (rc=0)
===== 5/5 PASS =====
### nationwide_test.py (rc=0)
[SKIP] proxies.txt 없음(gitignore) — 전국 실수집 생략.
===== 4/4 PASS =====
### app_api_test.py (rc=0)
44/44 PASS
### throttle_test.py (rc=0)
===== 22/22 PASS =====
### harvest_safety_test.py (rc=0)
===== 68/68 PASS =====
```

전부 기대치와 일치. `keyword_router_test.py` 는 다른 에이전트 소유라 실행/보고에서 제외.

### 헤드리스 스모크

```
$ QT_QPA_PLATFORM=offscreen python main.py --headless --once --no-harvest
[13:37:44] === 헤드리스 무인 모니터 시작 ===
[13:37:44] 전계정(0) 매칭 0건(중복제거)
[13:37:44] [매칭] 신규 0 (유효계정 0, 커버 전국)
[13:37:44] --once 완료
EXIT=0
```

(자격증명이 없는 환경이라 유효계정 0 — 씨딩은 `_server_keyword_list` 가 `{}` 를
돌려줘 조용히 끝난다. 실 API·실 에뮬레이터에 닿은 것 없음.)

---

## 5. git 상태 (실제 출력)

```
$ git log --oneline -2
b148b63 fix: GUI 스윕도 읽기전용 provider 로 · accounts.json 프로세스 간 병합락
e19d526 test: 생산자 보고값 단언을 KeyError 대신 FAIL 로 잡게
```

`e19d526` 은 다른 에이전트 커밋이다(그 사이에 들어왔다). 내 커밋 **두 개**는:

```
$ git log --oneline -6
b148b63 fix: GUI 스윕도 읽기전용 provider 로 · accounts.json 프로세스 간 병합락   ← 내 것(2차)
e19d526 test: 생산자 보고값 단언을 KeyError 대신 FAIL 로 잡게
87b4790 fix: 관측 상한이 수렴하도록 '만원'의 정의를 하나로
47eff59 fix: 수확 소유자를 런타임당 하나로 좁히고 accounts.json 동시쓰기 차단      ← 내 것(1차)
fd87693 test: 마지막 빨간 테스트 4종 정리 — 삭제 2·설계변경 반영 1·SKIP관례 적용 1
f4756c1 test: 비밀파일 없으면 건너뛰게·JWT 헬퍼 나노스 충돌 제거
```

```
$ git status --short
?? cap-convergence-report.md
?? cleanup-report.md
?? harvest-safety-report.md
?? headless-sweep-report.md
?? last-red-report.md
?? observed-cap-report.md
?? red-tests-report.md
?? residual-fixes-report.md
?? sweep-engine-report.md
```

modified 가 하나도 없다 — 내 변경분은 전부 커밋됐다. `47eff59`: `main.py`,
`ld_autoharvest.py`, `harvest_safety_test.py`(신규), `headless_sweep_test.py`,
`unified_tab_wiring_test.py`. `b148b63`: `main.py`, `ld_autoharvest.py`,
`harvest_safety_test.py`, `.gitignore`. `?? *-report.md` 는 이 저장소에서 원래
추적되지 않는 에이전트 리포트다(이 문서 포함).

## 6. 남은 우려

1. **`sweep_engine.py:301` 의 로그 문구** `[수확] 실패(계속)` 는 이제 수확이 아니라
   파일 읽기 실패를 가리킨다. 기능엔 영향이 없지만 운영자를 오도한다. 엔진 파일을
   건드리지 않기로 해서 남겼다 — 한 줄 문구 수정이면 된다.
2. **락 타임아웃(20초) 초과 시에는 여전히 lost update 가 가능하다.** 설계상 그렇게
   골랐다(무한 대기보다 낫다). 로그가 크게 남으니, 실서버에서 그 줄이 보이면 어느
   프로세스가 오래 쥐는지 봐야 한다. 정상 병합은 밀리초 단위라 평시엔 안 뜬다.
3. **`_alert_api` 는 여전히 수확한다** — 사용자 조작 경로라 의도적으로 남겼다.
   스케줄이 아니고 두 락이 `_HarvestThread` 와의 겹침을 직렬화한다.
4. **파일락은 같은 파일시스템 전제다.** accounts.json 을 네트워크 공유(SMB/NFS)에
   두면 `flock`/`msvcrt.locking` 의 보장이 약해진다. 현재 배포는 로컬 디스크다.

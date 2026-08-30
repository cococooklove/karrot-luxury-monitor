# 사후 리뷰 잔여 4건 — 종료 보고

브랜치 `watch-followups`, 시작 HEAD `b148b63`.

---

## Finding 5 (HIGH) — 헤드리스 스윕이 영구 전국이고 좁힐 레버가 없다

### 무엇을 했나

`_save_alert_settings` 가 `autostart`/`core_only`/`night`/`crash_recover` 넷만
쓰던 것을, GUI 스윕 패널 위젯 값 전부를 `headless_sweep_cfg` 가 **읽는 바로 그
키 이름**으로 쓰게 했다.

- `MainWindow._sweep_settings_patch()` — 위젯 → `sweep_regions`,
  `sweep_nationwide`, `sweep_extra`, `sweep_exclude`, `sweep_min`, `sweep_max`,
  `sweep_days`, `sweep_rest_min/max`, `sweep_gap_min/max`, `sweep_lanes`.
- `MainWindow._restore_sweep_settings()` — 저장값을 위젯으로 되돌린다(패널이
  서버가 실제로 쓸 값을 보여준다).
- `MainWindow._wire_sweep_settings()` — 변경 시 300ms 디바운스 저장. 디바운스가
  없으면 시도/구를 한 번 체크할 때 `itemChanged` 가 수백 발 나면서 그만큼
  파일을 쓴다.
- 범위 판정을 `sweep_scope_for(regions, nationwide, out_json, log)` 하나로
  합쳐 `MainWindow._auto_cfg_base` 와 `headless_sweep_cfg` 가 같이 쓴다.
  `sweep_resync_action` 이 있는 이유와 같다 — 갈라지면 서버에서만 나는 버그다.

### 새 설치의 기본값: 무엇을 골랐고 왜인가

**전국이 아니다. 명품 밀집 5개 구(용산·성동·서초·강남·송파) = 166동이다.**
`default_sweep_regions()` 가 `OUT.json` 에서 뽑는다.

근거는 산수다. 스윕 한 사이클은 (지역 수 × 키워드 수) 요청이다. 전국은 동
6537곳이므로 키워드가 하나뿐이어도 한 사이클이 6537 요청이고, 이는 계정 하루
상한(`daily_cap=300`)의 **21배**다. 즉 아무 설정도 없는 서버는 첫 사이클에
계정 하나의 하루치를 21번 태우고, 계정 수만큼 사이클이 돌면 함대가 전부 캡에
걸린 채 남은 하루를 30~90초 no-op 루프로 보낸다. 그 상태에서 운영자가 쥘 레버는
없었다. **아무 입력도 없는 상태가 가장 비싼 모드로 떨어지는 것은 기본값으로
성립하지 않는다.**

166동은 전국의 1/39 이다. 요청량을 39배 낮추면서 명품 재판매 거래량이 실제로
모이는 구역은 남긴다(이 앱의 목적이 중고 명품이다). 좁은 쪽이 기본이고 넓히는
쪽이 의식적인 동작이어야 한다 — 좁아서 놓치는 것은 로그와 결과 건수로 보이지만,
예산 고갈은 조용히 일어난다.

### '미선택 = 전국' 규칙을 버린 것 — 내가 내린 판단

지시된 최소 수정은 "위젯 값을 저장한다" 였다. 그런데 그것만 하면 구멍이
남는다: GUI 의 옛 규칙이 '지역 미선택 = 전국'이었으므로, 운영자가 지역을 한 번도
건드리지 않은 채 휴식 시간만 바꿔도 저장 파일에 `sweep_regions: []` 가 쓰이고
서버는 다시 전국으로 간다. 사고를 우연한 저장 한 번으로 되살리는 셈이다.

그래서 **전국을 명시적 옵트인으로 바꿨다**: 스윕 패널에 `[전국 훑기]`
체크박스(기본 꺼짐, 툴팁에 요청량 설명)를 추가하고 `sweep_nationwide` 로
저장한다. GUI 동작이 바뀐다는 뜻이다(예전엔 미선택이 곧 전국이었다). 의도한
변경이고, 두 런타임에 똑같이 적용된다. 이 판단은 내가 내렸음을 밝혀 둔다.

판정 규칙(양쪽 런타임 공통):

| 상태 | 결과 |
|---|---|
| 고른 지역이 있다 | 그 지역만 |
| 지역 없음 + `[전국 훑기]` 켜짐 | `nationwide` (6537동) |
| 지역 없음 + 꺼짐 | 기본 166동, 로그로 알림 |
| `OUT.json` 을 못 읽음 | 빈 지역 목록 — **전국으로 안 떨어진다** |

마지막 줄이 중요하다. 폴백의 폴백이 전국이면 버그 하나로 사고가 되돌아온다.
커버리지 0 은 로그에 보이고, 예산 고갈은 안 보인다.

### 테스트로 확인한 것

- `default_sweep_regions` 가 동 코드를 내고, 중복이 없고, 전국의 1/10 미만이다.
- `OUT.json` 이 없으면 빈 목록(전국 아님).
- `sweep_scope_for` 세 갈래 + 지역이 전국 플래그를 이긴다.
- GUI 위젯을 만지고 저장 → `headless_sweep_cfg(저장값)` 이 만든 cfg 의
  `rest_min/rest_max/gap_min/gap_max/lanes/scope/regions/conditions` 가
  `_auto_cfg_base()` 결과와 **값까지 일치**한다.
- 설정 파일이 없는 새 설치에서 GUI·헤드리스 둘 다 `scope == "regions"` 이고
  regions 가 기본 166동이다.
- 저장 → 위젯 흩뜨리기 → `_restore_sweep_settings()` 왕복.
- `[전국 훑기]` 를 켜면 GUI·저장값·헤드리스가 모두 `nationwide`.

### 테스트가 잡은 실제 버그 하나

복원 코드 첫 판은 `min<=max` 강제 배선(`lo.valueChanged→hi.setMinimum`,
`hi.valueChanged→lo.setMaximum`) 때문에 저장값이 **잘렸다**. 현재 위젯에
휴식 200~300 이 들어 있는 상태에서 저장값 55~140 을 복원하면, 상한 140 이
현재 하한 200 에 막혀 200 으로 잘린다. 순서를 바꿔도 반대 방향으로 같은 일이
난다. `_spin_range()` 로 커플링을 잠시 풀고 두 값을 넣은 뒤 다시 거는 식으로
고쳤다. (`복원: 휴식 (55, 200)` FAIL → PASS)

---

## Finding 6 (MEDIUM) — GUI 스윕 되살리기가 무제한이고 죽은 엔진을 흘린다

`SWEEP_REVIVE_MAX` 를 세는 코드가 `HeadlessSweepRunner.resync` 안에만 있어서
GUI 는 상한이 아예 없었다. 세는 자리를 모듈 수준 순수 함수로 옮겼다:

```
sweep_revive_step(revives, want_n) -> (허락?, 다음 revives, 로그 문구)
```

로그 문구까지 함께 돌려준다 — 세는 곳과 말하는 곳이 갈라지면 숫자와 문구가
또 어긋난다. `HeadlessSweepRunner.resync` 와 `MainWindow._resync_search_sweep`
둘 다 이 함수를 부른다. GUI 도 헤드리스와 같은 자리에서 카운터를 0 으로
되돌린다(무동작 / start / restart).

죽은 엔진 처분은 `MainWindow._dispose_auto_monitor()` 로 뺐다.
`_start_search_sweep` 이 새 `AutoMonitor` 를 만들기 직전에 부른다:
`log`/`found` 시그널을 끊고 `deleteLater()` 한다. 시그널을 끊는 것도 같이 해야
한다 — 죽었지만 아직 삭제 안 된 객체가 계속 슬롯을 때린다.

**확인:** 항상 죽은 채로 뜨는 가짜 `AutoMonitor` 로 `_resync_search_sweep` 을
`SWEEP_REVIVE_MAX + 6` 회 돌린다. 만들어진 모니터는 `1 + SWEEP_REVIVE_MAX` 개,
마지막 하나만 빼고 **전부** `deleteLater` 됐고, 버려진 것들은 시그널 연결이
0 이며, 포기 로그는 정확히 한 번, 대기열이 바뀌면 상한이 풀린다.

---

## Finding 7 (MEDIUM) — 헤드리스가 락 없는 커넥션 하나로 두 스레드에서 watch.db 를 쓴다

### 고른 모양: **인계 큐** (락이 아니다)

스윕 스레드는 `sweep_found_q.put_nowait(payload)` 만 한다. 정규화(`keyword` 판정
포함)와 `WatchStore` 접근은 전부 폴링 스레드의 `drain_sweep_finds()` 가 한다.
큐는 `maxsize=SWEEP_FIND_QUEUE_MAX(2000)`, 넘치면 버리고 센 뒤 로그로 알린다.

### 왜 락이 아닌가

1. **불변식의 강도.** 락은 "앞으로 추가될 mutator 마다 잊지 말고 걸기" 라는
   규율에 기댄다. 큐는 sqlite 를 단일 스레드에 묶어 **구조로** 보장한다.
   `WatchStore` 에 메서드가 하나 더 붙어도 새로 지킬 것이 없다.
2. **두 런타임이 같은 모양이 된다.** GUI 는 `AutoMonitor.found` 가
   `pyqtSignal` 이라 큐 연결로 GUI 스레드에 배달되고 — 이 위험이 애초에 없다.
   큐는 헤드리스에 그 모양을 그대로 준다. 락은 헤드리스에만 있는 또 하나의
   갈래가 되고, 이 코드베이스가 `sweep_resync_action` 을 공유하는 이유가 바로
   그 갈래를 막기 위해서다.
3. **막히지 않는다는 요구를 정면으로 만족한다.** 이게 결정적이다. 요구는
   "스윕 스레드가 폴링 루프의 긴 네트워크 스윕에 붙잡히면 안 된다" 이다.
   메서드 단위 락이라면 네트워크(`api.fetch`)는 store 메서드 **밖**에서 나므로
   실제로는 안 붙잡히겠지만, 그건 "락 잡은 구간에 네트워크를 넣지 않는다"는
   또 하나의 규율에 기댄 안전이다. `put_nowait` 은 큐가 가득 차도 즉시
   돌아온다 — 어떤 미래 코드가 폴링 쪽을 얼마나 오래 붙들든 스윕 스레드는
   구조적으로 한 순간도 대기하지 않는다.

지연 비용은 있다: 스윕이 찾은 매물이 다음 폴링 틱에 등록된다. GUI 의 queued
시그널도 똑같은 성질이고, 이 매물들은 어차피 다음 스윕 회차에 조회된다.

### 진짜 스레드로 확인

`WatchStore` 를 `ThreadWitness` 로 감싸 **모든 메서드 호출의
`threading.get_ident()`** 를 기록한다. 진짜 스레드가 400건을 콜백으로 밀어넣는
동안 메인(=폴링) 스레드가 `drain_sweep_finds` + `enforce_cap` +
`active_count`(=읽기-수정-쓰기 3종)를 반복한다. 결과:

- 저장소를 만진 스레드 ident 집합의 크기 = **1**, 그 값이 폴링 스레드다.
- 스윕 스레드 ident 는 그 집합에 없다.
- 400건 전부 등록됐고, 버려진 건 0, `enforce_cap` 이 실제로 돌아
  활성 행이 `ACTIVE_CAP`(300) 이하다.
- 소스 수준으로도: `_sweep_found` 본문에 `put_nowait` 만 있고
  `add_from_matches`/`watch_tracker` 가 없다.

---

## Finding 9 (MEDIUM) — `reset_observed_cap()` 에 호출자가 없다

관측 상한은 하강만 하고 스스로 회복하지 않는다. 등록 엔드포인트의 일시적 오류
하나로 내려앉으면 서버에서 `data/keyword_routes.json` 을 손으로 고치는 것
말고는 길이 없었다.

**이제 닿는 곳 둘:**

| 런타임 | 조작 |
|---|---|
| GUI | 고급 패널 `[슬롯 상한 초기화]` 버튼 → `MainWindow.on_reset_cap_clicked()` |
| 헤드리스 | `python main.py --headless --reset-cap` |

로그 문구도 고쳤다. 예전엔 운영자에게 없는 것(`reset_observed_cap()` 이라는
내부 메서드 이름)을 알려줬다.

```
⚠ 앱 슬롯 상한 관측치 하향: 30 → 12(... — 잘못 내려갔으면 고급 패널
[슬롯 상한 초기화], 서버는 --reset-cap 으로 되돌릴 것)
```

`keyword_router.py` 모듈 docstring 과 `reset_observed_cap` docstring 도 같은
두 조작을 가리킨다.

**확인:** GUI 버튼이 고급 패널 안에 있고, 툴팁이 `--reset-cap` 을 언급하고,
가짜 라우터로 `.click()` 이 실제로 핸들러를 타고(고급 패널을 펴야 활성이다),
되돌릴 게 있으면 True + 로그, 없으면 False + 다른 로그. 헤드리스 쪽은 소스
배선 + 아래 실행 확인.

---

## git

```
$ git log --oneline -2
da9016f fix: 서버 스윕에 레버를 주고, 없던 상한·경계·탈출구를 채운다
b148b63 fix: GUI 스윕도 읽기전용 provider 로 · accounts.json 프로세스 간 병합락
```

```
$ git status --short
?? ../../../cap-convergence-report.md
?? ../../../cleanup-report.md
?? ../../../harvest-safety-report.md
?? ../../../headless-sweep-report.md
?? ../../../last-red-report.md
?? ../../../observed-cap-report.md
?? ../../../red-tests-report.md
?? ../../../residual-fixes-report.md
?? ../../../sweep-engine-report.md
```

추적 대상 변경은 전부 커밋됐다(`M` 행 없음). 남은 `??` 는 이전 세션들이
워크트리 루트에 남긴 보고서 파일들로, 이번 작업과 무관하다.

변경 파일 4개:

```
 .../manual_gui/daangn_ext/keyword_router.py        |  12 +-
 .../integrated/manual_gui/headless_sweep_test.py   | 209 +++++++++-
 delivery/integrated/manual_gui/main.py             | 423 +++++++++++++++++++--
 .../manual_gui/unified_tab_wiring_test.py          | 233 ++++++++++++
 4 files changed, 828 insertions(+), 49 deletions(-)
```

---

## 헤드리스 스모크

```
$ QT_QPA_PLATFORM=offscreen python3 main.py --headless --once --no-harvest
[14:13:18] === 헤드리스 무인 모니터 시작 ===
[14:13:18] 전계정(0) 매칭 0건(중복제거)
[14:13:18] [매칭] 신규 0 (유효계정 0, 커버 전국)
[14:13:18] --once 완료
EXIT=0
```

`--reset-cap` 도 실제로 태워 봤다:

```
$ QT_QPA_PLATFORM=offscreen python3 main.py --headless --once --no-harvest --reset-cap
[14:13:22] === 헤드리스 무인 모니터 시작 ===
[14:13:22] [라우터] 상한 관측치가 이미 비어 있습니다 — 되돌릴 것이 없습니다
[14:13:22] 전계정(0) 매칭 0건(중복제거)
[14:13:22] [매칭] 신규 0 (유효계정 0, 커버 전국)
[14:13:22] --once 완료
```

(자격증명이 없어 계정 0, 대기열 0 이라 스윕은 뜨지 않는다 — 그래서 기본 범위
로그는 여기 안 나온다. 그 경로는 위 테스트가 직접 덮는다.)

---

## 테스트 — 27개 전부 exit 0

`delivery/integrated/manual_gui/` 에서 실행. 실제로 본 꼬리 그대로:

```
########## _auto_test.py (exit=0)
    🆕 신규 [종로구-2] 구찌 GG 체리 반지갑 250,000원 /kr/buy-sell/%EA%B5%AC%EC%B0%8C-gg-
    🆕 신규 [종로구-2] 구찌 쿼츠 가죽 시계 250,000원 /kr/buy-sell/%EA%B5%AC%EC%B0%8C-%EC%
    🆕 신규 [종로구-2] (백화점구매정품) 구찌 디오니소스 GG 체인 1,100,000원 /kr/buy-sell/%EB%B0%B
PASS
########## _construct_test.py (exit=0)
  [PASS] 프록시 로테이션  http://a:1
  [PASS] 프록시 없으면 None  

===== 9/9 PASS =====
########## _proxy_ui_test.py (exit=0)
프록시 UI OK — 수동/자동 버튼 문구 '프록시 목록 (0)' / 목록 다이얼로그 존재

==================================================
===== 5/5 PASS =====
########## _ux_test.py (exit=0)
'강남' 필터 결과: ['서울특별시 강남구 역삼동', '서울특별시 강남구 대치동', '서울특별시 강남구 청담동', '서울특별시 강남구 논현동', '서울특별시 강남구 삼성동'] (총 35)
전체선택(강남 필터) → 선택: []
전체해제 후 선택: 0
PASS: 지역검색+전체선택/해제 동작
########## app_api_test.py (exit=0)
  [PASS] refresh 없으면 토큰만료 표시  

==============================================
44/44 PASS
########## article_watch_test.py (exit=0)
  [PASS] 기본 상한은 옛 파일과 같다  
  [PASS] 백필 묘비 출처 상수  

===== 191/191 PASS =====
########## article_watch_wiring_test.py (exit=0)
  [PASS] 경계 포함  
  [PASS] 처음(0) → True  

===== 27/27 PASS =====
########## backfill_test.py (exit=0)

  [PASS] auto_seen 지워도 된다는 문구 없음  

===== 26/26 PASS =====
########## button_test.py (exit=0)
=== 지역 트리에서 동을 고를 수 있다 ===
  [PASS] 지역 트리 채워짐  부암동-6

===== 30/30 PASS =====
########## e2e_chain_test.py (exit=0)
  계정 3 · refresh 회전 정상 · 401 자동복구 정상

==================================================
10/10 PASS
########## full_test.py (exit=0)
  [PASS] 수동 검색 위젯  
  [PASS] 감시 위젯  

===== 17/17 PASS =====
########## harvest_safety_test.py (exit=0)
  ok   상한 초과를 크게 남긴다
  ok   상한 기본값 20초
  ok   홀더가 죽으면 락이 풀린다(영구 스테일 없음)
===== 68/68 PASS =====
########## headless_sweep_test.py (exit=0)
            " 서버는 --reset-cap 으로 되돌릴 것)")


===== 155/155 PASS =====
########## keyword_router_test.py (exit=0)
  [PASS] 진짜 반환값으로도 sweep  {'keyword': '초과', 'route': 'sweep', 'reason': '앱 등록 실패(차단 키워드·유효 계정 없음)'}
  [PASS] 진짜 반환값으로도 free 가 0 으로 수렴  {'cap': 15, 'used': 15, 'free': 0}

===== 155/155 PASS =====
########## ldwin_sim_test.py (exit=0)
ok   test_rescue_offscreen_leftover
ok   test_shutdown_restores_mixed_state
ok   test_stow_then_unstow_restores_position_and_taskbar
ok   test_stowed_window_attached_then_released_comes_back_on_screen
########## ldwin_test.py (exit=0)
ok   test_resolve_marks_missing_window_not_running
ok   test_resolve_recovers_from_wrong_field_order
ok   test_resolve_trusts_matching_handle
ok   test_short_and_broken_fields
########## nationwide_test.py (exit=0)
[SKIP] proxies.txt 없음(gitignore) — 전국 실수집 생략. 실행하려면 이 디렉터리(/Users/younglee/당근부동산_숨고/.claude/worktrees/watch-followups/delivery/integrated/manual_gui)에 실 프록시 계정을 담은 proxies.txt를 두고 재실행할 것.

==================================================
===== 4/4 PASS =====
########## notify_test.py (exit=0)
  [PASS] 실제 API 401 → 실패로 보고(무음 아님)  401 Unauthorized — 봇 토큰이 잘못됨

==============================================
54/54 PASS
########## proxy_test.py (exit=0)
[SKIP] proxies.txt 없음(gitignore) — 실 프록시 연결성/스케일링 실측 생략. 실행하려면 이 디렉터리(/Users/younglee/당근부동산_숨고/.claude/worktrees/watch-followups/delivery/integrated/manual_gui)에 실 프록시 계정을 담은 proxies.txt를 두고(형식은 proxies.example.txt 참고) 재실행할 것.

==================================================
===== 6/6 PASS =====
########## robust_test.py (exit=0)
  [PASS] 일반 실패는 기존 문구 유지  상품 리스트 가져오기 실패 (빈응답 0·차단 3)

==============================================
29/29 PASS
########## supervisor_test.py (exit=0)
  [PASS] retune 이 스윕 간격 갱신  1800000
  [PASS] 정지 중 retune 은 무동작  

===== 20/20 PASS =====
########## sweep_engine_test.py (exit=0)
  [PASS] [robust_test] _regions 언바운드 호출  ['강남구-381']
  [PASS] 엔진 _regions 도 동일 동작  

===== 57/57 PASS =====
########## sweep_queue_test.py (exit=0)
  [PASS] touch 가 파일에 남음  ['에르메스', '구찌', '짝퉁']
  [PASS] touch 가 조건을 안 지움  {'keyword': '샤넬', 'min': 100, 'max': 200, 'exclude': ['가품'], 'at': 77}

===== 29/29 PASS =====
########## throttle_test.py (exit=0)
  [PASS] 프록시 20 > 워커 16 → 16  
  [PASS] 프록시 없음 → 설정값 유지  

===== 22/22 PASS =====
########## unified_tab_wiring_test.py (exit=0)
  [PASS] 라우터를 실제로 불렀다  2
  [PASS] 클릭 시그널이 핸들러에 연결돼 있다  3

===== 205/205 PASS =====
########## variance_test.py (exit=0)
          매 회차 재현율 23.0%
미확인    0/10 회차에서 확인 실패 구간 발생

✅ 편차 0.4% — 동일 조건 반복 결과 안정
########## watch_listing_test.py (exit=0)
  [PASS] 묘비는 그대로 dead  {'id': '99', 'title': '오래된 매물', 'region': '압구정', 'url': 'u99', 'price': 100000, 'status': 'ongoing', 'republish_count': 0, 'published_at': 1785408000, 'first_seen': 1788000000, 'last_check': 1788000000, 'next_check': 1788000000, 'tier': 'dead', 'fail': 0, 'keyword': '샤넬', 'source': 'app', 'first_price': 100000, 'last_change': 0, 'last_delta': 0}
  [PASS] 묘비는 가격 이력 안 남김  []

===== 47/47 PASS =====
```

### 기준선 대비

| 스위트 | 이전 | 이후 |
|---|---|---|
| `headless_sweep_test.py` | 101/101 | **155/155** |
| `unified_tab_wiring_test.py` | 148/148 | **205/205** |
| `article_watch_test.py` | 191/191 | 191/191 |
| `keyword_router_test.py` | 155/155 | 155/155 |
| `harvest_safety_test.py` | 68/68 | 68/68 |
| `sweep_engine_test.py` | 57/57 | 57/57 |
| `watch_listing_test.py` | 47/47 | 47/47 |
| `app_api_test.py` | 44/44 | 44/44 |

나머지 19개는 기준선과 동일. 새로 추가한 단언 111개.

### 고친 낡은 단언 2개

기존 테스트가 옛 동작을 못 박고 있어 의도적으로 바꿨다.

1. `headless_sweep_test.py` `지역 미지정 → 전국` → `지역 미지정이어도 전국이
   아니다` + `지역 미지정 → 기본 지역`. Finding 5 가 고치라고 한 바로 그
   동작이다.
2. 같은 파일 `source='sweep' 로 등록` 의 대상. `source="sweep"` 리터럴이
   `_run_headless` 에서 `drain_sweep_finds` 로 옮겨갔으므로 단언 대상을
   옮기고, `헤드리스가 인계 큐를 드레인` 을 더했다.

---

## 남는 것

- **`--reset-cap` 은 `--once` 없이도 부팅 시 한 번만 실행된다.** 폴링 루프
  진입 전에 있으므로 상시 구동 서버에서는 재시작해야 먹는다. 상한이 잘못
  내려앉는 것 자체가 드문 사건이고 그때는 어차피 서버를 만지므로, 실행 중
  초기화를 위한 IPC 채널까지는 만들지 않았다.
- **`AccountBudget` 과 `AccountScheduler` 의 예산이 여전히 별개다.**
  `article_watch.AccountBudget` docstring 이 명시한 기존 과제이고 이번 범위가
  아니다. Finding 5 로 스윕 쪽 요청량이 39배 줄어 합산 초과 여지는 그만큼
  좁아졌다.
- **기본 지역은 `OUT.json` 의 시도/구 이름 문자열에 의존한다.** 이름이 바뀌면
  빈 목록으로 떨어지고(전국이 아니라), 그때는 지역이 0개라는 사실이 로그와
  결과 건수로 드러난다. 조용히 비싸지는 쪽보다 낫다고 판단했다.

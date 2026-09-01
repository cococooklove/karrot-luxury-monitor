# 함대 전체 기동 보장 — ensure_ldplayer

대상: `delivery/integrated/manual_gui/ld_autoharvest.py`, `fleet_boot_test.py`

## 결함 (세 겹이었다)

1. `_harvest_all_locked` 이 `list_instances(adb)` 가 **하나라도** 돌려주면 그걸
   함대로 받아들이고 `ensure_ldplayer` 를 건너뛰었다. 클라 서버에서 6대 중 1대만
   adb 에 보였고 나머지 5대는 영영 안 깨어나 토큰이 만료된 채 방치됐다(수명은
   당시 2시간으로 적었으나 실측 30분이다 — 아래 예산 항목의 정정 참고).
   주석의 "클라가 안 켜도 됨" 약속은 함대가 **완전히** 죽었을 때만 유효했다.
2. 그 5대는 dnplayer 프로세스가 **살아 있는** 채로 hang 해 있었다(VM RUNNING ·
   BIOS 는 도는데 게스트 커널 미기동). 이 상태에서 `ldconsole launch --index N`
   은 no-op 이다 — LDPlayer 가 '이미 실행중'으로 보고 아무것도 하지 않은 채
   성공을 반환한다(코디네이터 실측: launch 후 90초, 새 프로세스도 새 adb 기기도
   나타나지 않음). 즉 "adb 기기 없는 인스턴스를 켠다"만으로는 부족하다.
3. 응답 여부를 serial 단위로만 알면 `androidStarted=1` 인데 대답 안 하는
   인스턴스를 **지목할 수 없어** 조치를 못 한다. 집계로는 "6대 중 1대만 응답"
   까지가 한계다. 그런데 그게 클라 서버가 지금 갇힌 상태 그대로다.

## 부팅 정책

### 판정: 인덱스별 프로브 (집계 아님)

```
ldconsole adb --index N --command "shell echo PROBE_OK"
```

ldconsole 이 인덱스 → serial 을 **스스로 풀어준다**. 코디네이터 실서버 실측:

```
> ldconsole.exe adb --index 1 --command "shell echo PROBE_OK"
PROBE_OK

> ldconsole.exe adb --index 3 --command "shell echo PROBE_OK"
adb.exe: device 'emulator-5560' not found
```

성공 판정은 **종료코드 0 + 토큰만 단독으로 있는 줄**이다. 부분일치를 쓰지 않는
이유: ldconsole 버전에 따라 명령줄을 그대로 되울리는 경우가 있는데, 그러면 실패
출력에도 토큰이 섞여 무응답을 응답으로 오독한다. 타임아웃/예외도 무응답이다.
`PROBE_TIMEOUT = 8초`.

기동 **성공 확인**도 같은 프로브다. "아무 기기나 새로 붙었나" 같은 집계는 다른
인스턴스가 늦게 뜬 것을 이 인스턴스의 성공으로 오독한다.

### 인스턴스별 조치

| 프로브 | list2 상태 | 조치 |
|---|---|---|
| 응답 | — | 건드리지 않음 (quit 도 launch 도 안 감) |
| 무응답 | `pid`/`vboxPid` 있음 **또는** `androidStarted=1` | **quit → 소멸 확인 → launch** |
| 무응답 | 프로세스 없음 | 바로 launch |

두 번째 줄에 `androidStarted=1` 무응답이 **포함된다** — 클라 서버가 갇힌 바로 그
상태다. 이전 설계에서는 이걸 "인덱스를 특정할 수 없다"며 로그만 남기고 넘겼는데,
그건 기계를 고장난 채로 두는 것이었다. 인덱스 프로브가 있으니 지목이 되고,
따라서 조치한다.

### 예산 · 재시도

- `FLEET_BOOT_BUDGET = 600.0` (10분). 수확 틱은 20분(`_HarvestThread(interval=1200)`,
  헤드리스 폴링 루프도 20분)이므로 한 틱 안에 들어간다. 예산은 프로브 단계부터
  센다. 넘기면 남은 인스턴스는 그 자리에서 포기하고 **다음 틱**이 이어서 올린다.
  **정정(2026-09-01 실측): 토큰 수명은 2시간이 아니라 30분이다**(JWT `exp-iat`
  = 1800초, 서버 4계정 전부 동일). 그래서 "틱 6회분 여유"는 성립하지 않는다.
  한 틱(1200초)에 못 깨운 인스턴스는 다음 틱까지 버티지 못하고 그 계정 토큰은
  실제로 만료된다. 예산 초과는 '다음 틱이 이어서 올린다'가 아니라 '그 계정은
  한 주기 쉰다'로 읽어야 한다. 함대가 예산 안에 다 들어오는지가 곧 가동률이다.
- `BOOT_RETRY = 1` — 인스턴스당 한 사이클에 launch 최대 2회. 영구 고장난
  인스턴스를 매 사이클 무한정 다시 깨우는 adb/VM 폭주를 막는다.
- `_BOOT_FAILS`(인덱스별 연속 실패 횟수)가 부팅 **순서**를 정한다. 실패가 쌓인
  인덱스는 뒤로 밀리므로 고장난 1대가 예산 앞머리를 선점해 멀쩡한 5대를 매 사이클
  굶기지 않는다. 성공하면 카운트가 지워진다.
- 기동은 **순차**다. 동시 launch 는 게스트 커널이 안 뜨는 하드 실패이므로 기존
  `gap`(35초)과 `retry` 를 그대로 유지했다.

### 프로세스가 정말 사라졌는지 어떻게 확인했나

`_wait_process_gone(console, idx, limit)` 이 `ldconsole list2` 를 다시 읽어 **그
인덱스 행의 `pid`/`vboxPid` 가 더는 보고되지 않을 때까지** 3초 간격으로 폴링한다.
근거를 list2 자신에게서 얻는 이유는 그게 LDPlayer 가 launch 를 무시할지 판단하는
것과 **같은 정보원**이기 때문이다 — list2 가 그 인덱스에 프로세스가 없다고 말하는
순간이 곧 launch 가 실제로 먹는 순간이다.

`ldconsole quit` 이 먹지 않으면(비대화형 세션에서 보낸 quit 은 대화형 데스크톱
세션이 소유한 프로세스를 못 죽인다) list2 가 준 pid 로 `taskkill /F /T /PID`
(POSIX 는 `os.kill`)로 승격하고 다시 확인한다. 대기는 양쪽 다 유한하다 —
`QUIT_WAIT = 40초`, `KILL_WAIT = 15초`. 안 먹는 quit 이 무인 수확기를 무는 일은 없다.

### 영구 고장 인스턴스

- launch 해도 안 뜨는 경우: retry 소진 후 **건너뛴다**. 다음 인스턴스를 막지 않고
  `_BOOT_FAILS` 만 올라가 다음 사이클 후순위가 된다. 사이클당 launch 최대 2회.
- quit 도 kill 도 안 먹어 프로세스가 안 내려가는 경우: **launch 를 아예 보내지
  않는다**(그 상태의 launch 는 no-op 이라 의미가 없다). 크게 남기고 넘어간다.
- 어느 쪽도 호출자를 물지 않는다. 매 사이클 재시도는 하되 상한 안에서만 한다.

## 인덱스→serial 매핑

**매핑 공식은 만들지 않았다. 필요가 없다.**

처음 조사에서 확인한 것: `list2` 필드(`index,name,topWindowHandle,
bindWindowHandle,androidStarted,pid,vboxPid,width,height,dpi`)에 adb 포트도
serial 도 없고, 이 코드베이스 어디에도 인덱스로 serial 을 계산하는 코드가 없다.
`list_instances` 가 아는 것은 `emulator-P` 와 `127.0.0.1:(P+1)` 이 같은
인스턴스라는 **포트 쌍** 관계뿐이고 인덱스와는 무관하다.
`tools/randomize_fingerprint.py` · `collector/run_pipeline.py` 는 serial 과
`ld_index` 를 **둘 다 설정에서 따로 받는다**. `ANTIBAN.md` 의
`emulator-5554 / ld_index 0` 는 문서상의 관례일 뿐 코드가 보증하지 않는다.

그래서 공식을 지어내는 대신 **ldconsole 에게 대신 풀게 했다**. `ldconsole adb
--index N` 은 인덱스를 받아 그 인스턴스의 adb 를 태우고, 실패할 때는 자기가 고른
serial 을 에러 메시지에 찍어준다(`device 'emulator-5560' not found`). 우리는
serial 을 한 번도 계산하지 않는다.

- **켜고 죽일 대상**은 전부 인덱스로 지목된다(`ld_probe` / `ld_launch` /
  `ld_quit` / `ld_rows` 의 pid). serial 을 거치지 않는다.
- **serial** 이 등장하는 곳은 반환값 하나뿐이다 — `harvest_one` 이 serial 로
  말하기 때문에 `live_instances(adb_bin)` 로 대답하는 기기 목록을 만들어 넘긴다.
  이건 수확 대상 목록일 뿐 어떤 인덱스를 조작할지 정하는 데 쓰이지 않는다.

`fleet_boot_test.py` 의 가짜 serial 은 일부러 포트 산술과 무관한 `dev-0`,
`dev-1` … 로 지었다. 코드가 매핑을 가정하지 않는다는 것 자체가 테스트로 고정된다.

## _harvest_all_locked

`use = list(serials or []) or list_instances(adb_bin)` → 매번 `ensure_ldplayer`
로 함대를 보장한 뒤 그 결과(= 대답하는 기기)만 수확한다. 호출자가 serial 을
명시하면 기존대로 함대 보장을 건너뛴다. `_HARVEST_LOCK`(프로세스 내 직렬화)과
`merge_accounts` 의 `_MERGE_LOCK` + `accounts.json.lock` 파일락은 손대지 않았다.

## 코디네이터 실서버 확인 (내 기계에서 재현 불가한 부분)

- 복구 사슬 수동 검증: hang 한 인덱스를 quit → `dnplayer` 프로세스 수 감소 확인 →
  launch → `emulator-5556` 이 adb 에 등록되는 것 확인 → nudge 수확 → **2시간 전
  만료됐던 계정에서 잔여 1763초짜리 새 토큰**이 돌아옴. 파이프라인 자체는
  멀쩡했고 부팅 분류만 고장나 있었다.
- 인덱스 프로브 실측 출력은 위 "판정" 절에 그대로 인용했다.

## 검증

### git log --oneline -2
```
24ba0db fix: 무응답 인스턴스를 인덱스로 지목해 되살린다
7a8cd59 fix: 프로세스가 살아 있는 인스턴스에 launch 를 보내 함대가 영영 안 살아나던 문제
```

### git status --short
```
?? ../../../docs/superpowers/reports/2026-08-30-watch-followups/fleet-boot-report.md
(유일한 미추적 파일은 이 보고서 자신이다. 소스 변경분은 전부 커밋됐다.)
```

### 테스트

코디네이터 지시로 검증면을 좁혔다. 아래 5개만 돌렸다 —
`ld_autoharvest.py` 를 타거나 수확 소유권·계정파일 락에 닿는 스위트다.
작업 디렉터리에서 `python3 -u <name>_test.py`. 각 스위트 마지막 3줄이다.

```
$ python3 fleet_boot_test.py
  ok   _HARVEST_LOCK 유지
  ok   merge_accounts 가 _MERGE_LOCK + 파일락을 모두 잡는다
===== 101/101 PASS =====
exit=0

$ python3 harvest_safety_test.py
  ok   상한 기본값 20초
  ok   홀더가 죽으면 락이 풀린다(영구 스테일 없음)
===== 68/68 PASS =====
exit=0

$ python3 article_watch_test.py
  [PASS] 백필 묘비 출처 상수  

===== 191/191 PASS =====
exit=0

$ python3 headless_sweep_test.py


===== 155/155 PASS =====
exit=0

$ python3 unified_tab_wiring_test.py
  [PASS] 클릭 시그널이 핸들러에 연결돼 있다  3

===== 205/205 PASS =====
exit=0

```

**돌리지 않음:** `nationwide_test.py` — 실프록시 20개로 전국 6537개 동을 실제로
수집하는 라이브 네트워크 스위트다. 두 번 시도했고 두 번 다 세션 안에 끝나지 않아
중단했다(마지막 관측: `=== 3. 전국 실수집 (20프록시 병렬) ===` 이후 진행 없음).
**not run (live-network) — 통과했다고 주장하지 않는다.** `ld_autoharvest` 를
import 하지 않고 `daangn_ext.adaptive` / `daangn_ext.search_filters` 만 쓰므로
수확 경로에 닿지 않는다.

(`proxy_test.py` 는 아래 참고 표에서 9/9 로 통과했다 — 프록시 파일이 없으면
수집 구간을 SKIP 하는 관례라 완주한다.)

나머지 스위트는 이번 라운드의 공식 검증 대상이 아니지만, 지시 이전에 걸어둔
전체 실행이 최종 코드로 완주해 결과가 남았다 — 맨 아래 참고 표.

### 브리핑 수치와 다른 항목

`unified_tab_wiring_test.py` 는 **205/205** 였다(브리핑의 148/148 은 오래된
수치 — 코디네이터가 확인해줬다. 관측값을 쓴다). `article_watch_test.py`
191/191, `headless_sweep_test.py` 155/155, `harvest_safety_test.py` 68/68 은
브리핑과 일치한다.

신규 `fleet_boot_test.py` **101/101**. 회귀 감지력은 변이 검사로 확인했다:
판정을 인덱스 프로브에서 `androidStarted` 로 되돌리면 9개가 FAIL 한다
(92/101) — 무응답 인덱스에 quit→launch 가 안 나가고 6대 중 1대만 살아남는,
정확히 클라 서버의 그 증상이 잡힌다.

### 참고: 전체 스위트 백그라운드 실행 (지시 이전에 걸어둔 것)

검증면을 좁히라는 지시 전에 걸어둔 전체 실행이 최종 코드(인덱스 프로브 포함)
기준으로 완주했다. nationwide 를 뺀 **26개 전부 exit 0**:

```
_auto_test.py EXIT=0 :: 
_construct_test.py EXIT=0 :: ===== 9/9 PASS =====
_proxy_ui_test.py EXIT=0 :: ===== 5/5 PASS =====
_ux_test.py EXIT=0 :: 
app_api_test.py EXIT=0 :: 
article_watch_test.py EXIT=0 :: ===== 191/191 PASS =====
article_watch_wiring_test.py EXIT=0 :: ===== 27/27 PASS =====
backfill_test.py EXIT=0 :: ===== 26/26 PASS =====
button_test.py EXIT=0 :: ===== 30/30 PASS =====
e2e_chain_test.py EXIT=0 :: 
fleet_boot_test.py EXIT=0 :: ===== 101/101 PASS =====
full_test.py EXIT=0 :: ===== 17/17 PASS =====
harvest_safety_test.py EXIT=0 :: ===== 68/68 PASS =====
headless_sweep_test.py EXIT=0 :: ===== 155/155 PASS =====
keyword_router_test.py EXIT=0 :: ===== 155/155 PASS =====
ldwin_sim_test.py EXIT=0 :: 
ldwin_test.py EXIT=0 :: 
notify_test.py EXIT=0 :: 
proxy_test.py EXIT=0 :: ===== 9/9 PASS =====
robust_test.py EXIT=0 :: 
supervisor_test.py EXIT=0 :: ===== 20/20 PASS =====
sweep_engine_test.py EXIT=0 :: ===== 57/57 PASS =====
sweep_queue_test.py EXIT=0 :: ===== 29/29 PASS =====
throttle_test.py EXIT=0 :: ===== 22/22 PASS =====
unified_tab_wiring_test.py EXIT=0 :: ===== 205/205 PASS =====
variance_test.py EXIT=0 :: 
watch_listing_test.py EXIT=0 :: ===== 47/47 PASS =====
```

`watch_listing_test.py` 는 실행 창이 내 pkill 과 겹쳐서 위 기록을 그대로
믿지 않고 따로 다시 돌렸다 — `exit=0`, `===== 47/47 PASS =====`.
`variance_test.py` 등 PASS 줄이 비어 보이는 스위트는 종료 형식이 달라서이며
(예: `✅ 편차 0.4% — 동일 조건 반복 결과 안정`) 전부 exit 0 이다.

이 표는 참고용이다. 이번 라운드의 공식 검증은 위 5개 스위트다.

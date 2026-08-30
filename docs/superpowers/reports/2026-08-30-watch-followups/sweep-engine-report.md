# 스윕 엔진 Qt 분리 (daangn/sweep_engine.py + daangn/auto_monitor.py)

## 분리 형태 (최종 — 평범한 모듈 분리)

- **`daangn/sweep_engine.py`** — 순수 파이썬. Qt 를 어느 수준에서도 import 하지 않는다.
  `SweepEngine.__init__(self, cfg: dict, on_log=None, on_found=None, on_status=None)`.
  콜백은 전부 선택, 기본값은 모듈 수준 `_noop`. 내부에서는 `self._log(...)` /
  `self._found(...)` / `self._status(...)` 세 디스패치 메서드로 콜백을 부른다
  (예전 `self.log.emit` 자리 1:1 치환).
  로직 전부 이 파일: `_stop`, `stop()`, `_rest`, `_live_proxies`, `_proxy_cycle`,
  `_plan_lanes`, `notify`, `_flush_notify`, `_telegram`, `_sheet_append`, `_regions`,
  `_dedup_notify`, `run`, 그리고 상수(`CYCLE_REST_*`, `REGION_GAP_*`,
  `MIN_IP_PER_LANE`, `MAX_LANES`) + `_clamp_range`/`_pi`/`_P` +
  `load_conditions_from_excel`(openpyxl 뿐, Qt 무관).

- **`daangn/auto_monitor.py`** — 60줄 어댑터. 최상단에서 평범하게
  `from PyQt6.QtCore import QThread, pyqtSignal`, `from daangn.sweep_engine import SweepEngine`.
  `AutoMonitor(QThread)` 는 `log`/`found`/`status` 시그널, `__init__(self, parent, cfg)`,
  `stop()`, `run()` 그대로. 생성자에서
  `SweepEngine(cfg, on_log=self.log.emit, on_found=self.found.emit, on_status=self.status.emit)`
  를 만들어 `self.engine` 에 보유. `stop()`/`run()` 은 엔진으로 위임.

- **`main.py`** — 한 줄만 바뀜: `:2725` 의
  `from daangn.auto_monitor import load_conditions_from_excel` →
  `from daangn.sweep_engine import ...`. `:2915` 의
  `from daangn.auto_monitor import AutoMonitor` 는 그대로(GUI 경로는 Qt 위라 정상).

앞 커밋(e6c91c9)의 모듈 `__getattr__`(PEP 562) 지연 import 는 **제거**됐다.
`_build_auto_monitor()` 도 없다.

### 어댑터의 여분 표면 — 무엇이 load-bearing 인가

셋 다 **기존 테스트**가 실제로 쓰는 것이라 남겼다. 내 새 테스트 전용은 없다
(내 테스트는 엔진을 `daangn.sweep_engine` 에서 직접 잡는다).

| 표면 | 필요한 곳 | 이유 |
|---|---|---|
| `_stop` property(get/set) | `notify_test.py:379,395` | `m._stop = True/False` 로 직접 세운다. 어댑터에 사본을 두면 엔진 플래그와 갈라져 `TelegramSender(should_stop=...)` 가 엉뚱한 걸 본다 |
| `__getattr__` 엔진 위임 | `notify_test.py:353,357,360…` (`m._tg`, `m._dedup_notify`, `m._flush_notify`), `full_test.py:68,76,82` (`m._dedup_notify`, `m._proxy_cycle`, `m._telegram`, `m._sheet_append`) | 인스턴스에서 엔진 내부를 직접 부른다 |
| `_regions` 클래스 본문 정의 | `robust_test.py:188` | `AutoMonitor.__dict__["_regions"]` 로 **언바운드**로 꺼내 더미 객체에 물린다 → 클래스 사전에 실물이 있어야 한다 |

`load_conditions_from_excel` 재수출(`auto_monitor` → `sweep_engine`)도 마찬가지 이유:
`full_test.py:54`, `gui_func_test.py:13`, `_construct_test.py:4` 가 `daangn.auto_monitor`
에서 가져간다. 새 코드는 `daangn.sweep_engine` 에서 직접 쓰면 된다(main.py 가 그렇다).

## 의도적으로 보존한 동작

- **`_stop` 은 하나뿐** — 어댑터는 엔진 것을 읽고 쓴다.
- **휴식 조기 기상**: `_rest` 의 `while not self._stop` + `time.sleep(min(0.2,left))` 원문.
- **프록시 샤딩/레인 산술**: `_plan_lanes` 의 `MIN_IP_PER_LANE`/`MAX_LANES` 클램프,
  프록시 목록 변경을 **사이클 경계에서만** 반영.
- **계정 안정화**: `AccountScheduler` 지연 import, `daily_cap`/`warmup_days`,
  `pick()` 실패 시 `_rest` 후 `continue`, `sched.note()`/`note_block()`.
- **사이클마다 토큰 provider 갱신**: sched 있을 때의 부작용 호출(반환값 무시)과
  sched 없을 때 `nt != token` 갱신 분기 둘 다.
- **`_dedup_notify`**: `auto_seen.db` 스키마/`INSERT OR REPLACE`/`UPDATE`, 가격·끌올
  필터, 반환 `(new, changed)`. `found` 페이로드의 `id` 필드 유지.
- **알림 배칭**: 지역마다 `_flush_notify()`, `finally` 의 `_flush_notify(final=True)`
  (`ignore_stop=True`, 30초 데드라인) + 집계 로그 + `[종료]` 로그.
- **`except Exception:` → `[치명오류]` + `traceback.format_exc()`** 로그. 삼키지 않음.

## git log --oneline -2

```
e731f8f refactor: 스윕 엔진을 별도 모듈로 분리(daangn/sweep_engine.py)
69db185 feat: 앱 슬롯 상한을 관측값으로 캐시(하향만, 오탐 방지)
```

커밋에 담긴 파일: `daangn/sweep_engine.py`(신규), `daangn/auto_monitor.py`,
`main.py`(1줄), `sweep_engine_test.py`. `daangn_ext/keyword_router.py` 와
`keyword_router_test.py` 는 손대지 않았다.

## 테스트 (전부 `delivery/integrated/manual_gui/` 에서 실행)

`python sweep_engine_test.py`
```
  [PASS] [robust_test] _regions 언바운드 호출  ['강남구-381']
  [PASS] 엔진 _regions 도 동일 동작  

===== 57/57 PASS =====
```

`python notify_test.py`
```
=== G. 실네트워크 (텔레그램 실API) ===
  [PASS] 실제 API 401 → 실패로 보고(무음 아님)  401 Unauthorized — 봇 토큰이 잘못됨

==============================================
54/54 PASS
```

`python robust_test.py`
```
==============================================
29/29 PASS
```

`python article_watch_test.py`
```
  [PASS] 판매완료·삭제(dead)는 재등록 안 함  

===== 177/177 PASS =====
```

`python unified_tab_wiring_test.py`
```
  [PASS] 헤드리스 옛 FIFO 제거  
  [PASS] GUI 에 match_seen 파일 코드 없음  

===== 123/123 PASS =====
```

`python article_watch_wiring_test.py`
```
  [PASS] 처음(0) → True  

===== 27/27 PASS =====
```

`python supervisor_test.py`
```
  [PASS] 정지 중 retune 은 무동작  

===== 20/20 PASS =====
```

`python sweep_queue_test.py`
```
  [PASS] touch 가 조건을 안 지움  {'keyword': '샤넬', 'min': 100, 'max': 200, 'exclude': ['가품'], 'at': 77}

===== 29/29 PASS =====
```

`python watch_listing_test.py`
```
  [PASS] 묘비는 가격 이력 안 남김  []

===== 47/47 PASS =====
```

`python backfill_test.py`
```
  [PASS] auto_seen 지워도 된다는 문구 없음  

===== 26/26 PASS =====
```

(참고: 앞선 요구 목록의 `keyword_router_test.py` 는 다른 에이전트가 그 파일을
작업 중이라 이번엔 돌리지 않았다. 직전 커밋 시점엔 72/72 PASS 였다.)

### sweep_engine_test.py 가 증명하는 것 (57 항목)

- **A.** 서브프로세스에서 `import daangn.sweep_engine` → `SweepEngine` 생성 →
  `_log/_status/_dedup_notify/stop` 까지 굴린 뒤에도 `sys.modules` 의 `PyQt6*` 0개
  (`qt_loaded: False`).
- **B.** 분리 형태 자체를 소스로 검사: 엔진 모듈에 `PyQt`/`QThread`/`.emit(` 없음,
  어댑터는 최상단에서 평범하게 PyQt import, **모듈 `__getattr__` 꼼수 없음**,
  어댑터 80줄 이하, 상수·엑셀로더는 엔진 모듈 소속, `main.py` 의 두 import 사이트.
- **C.** 콜백이 예전 시그널이 emit 하던 값 그대로: `notify` 로그 문자열(신규/가격변동),
  `found` 페이로드 9키와 `id`, `_dedup_notify` 의 신규/중복/가격변동 판정.
- **D.** 콜백 미지정(no-op 기본값)으로 `notify`/`_dedup_notify` 까지 무크래시.
- **E.** `stop()` → `_stop`, 그 플래그로 `_rest` 즉시 기상, `TelegramSender.should_stop` 전파.
- **F.** 어댑터: 엔진 콜백 → 시그널 3종 실제 발화, `run()`/`stop()` 위임, 그리고 위
  표의 하위호환 표면 3종을 **어느 기존 테스트 때문인지 이름표를 달아** 검사.
- 실제 스윕은 돌리지 않음(외부 API 미접촉).

## 남는 사항

- 이 커밋은 **엔진을 헤드리스에서 돌릴 수 있게** 만든 것까지다. `main.py` 의
  `_run_headless` 가 `SweepEngine` 을 실제로 기동하는 배선은 아직 없다 —
  서버에서 스윕 큐 키워드가 감시되지 않는 상태는 그 배선 전까지 그대로다.
- 무관한 기존 실패 2건(내 변경 전부터): `full_test.py:27`
  `TokenManager` 에 `ensure_safe` 없음, `_construct_test.py` 의 `w.tabs.count() == 2`
  (탭 제거 커밋 c3aa94f 이후 어긋남). 둘 다 AutoMonitor 도달 전에 죽는다.

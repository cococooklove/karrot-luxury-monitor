# 슬롯 상한 수렴 + 요청량 절감 (Finding 2·3·8·10)

## 1. '만원'을 어느 쪽으로 정했나 — `_observe_cap_full` 하나로 통일

**결론 지점은 `_observe_cap_full` 하나뿐이다. 상한 = 그때의 `used`.**
실측값(`observed_count`)은 '상한 값'이 아니라 '근거'로만 쓴다.
`_observe_measured_count` → `_observe_measured_full` 로 바꿔, 부등식 판정만 하고
결론은 `_observe_cap_full` 에 넘긴다.

왜 `capacity()` 에서 `free = cap - max(used, observed)` 를 계산하는 쪽이 아니라
이쪽인가:

- **실측값은 라우터가 쓸 수 있는 슬롯수가 아니다.** 서버 실보유수에는 이 브랜치
  이전 일괄등록분처럼 라우터가 모르는 키워드가 섞여 있다. 리뷰어 시나리오의 20 은
  "라우터 15 + 라우터가 모르는 5" 다. 20 을 상한으로 삼으면 라우터는 자기가 절대
  채울 수 없는 5칸을 자기 몫으로 세고, `used` 는 등록이 계속 거부되니 오르지 않고,
  `used` 가 안 오르니 더 낮은 관측도 받지 못한다 → 영구히 `free=5`.
- **거부는 "지금 남은 슬롯 0"이라는 뜻이다.** 그 순간 라우터가 실제로 쓰고 있는
  슬롯수(`used`)가 곧 라우터가 가질 수 있는 전부다. 이건 `_observe_cap_full` 이
  이미 하던 결론과 정확히 같다.
- `max(used, observed)` 방식은 관측 서버 카운트를 상한과 **별도로** 영속해야 해서
  '만원'의 정의가 클래스 안에 두 개 남는다(리뷰가 금지한 것).

유지된 성질(테스트로 고정): 하강 전용 · 영속 · 재시작 생존 · 깨진 파일에서 기본
상한으로 저하 · `reset_observed_cap()` / `seed_from_server()` 로 해제 · 움직일 때
로그. 애매한 증거는 여전히 거부한다 — `count < used`(뒤처진 계정)는 근거가 아니고,
`used == 0`(성공 이력 없음)도 건너뛴다.

바뀐 판정: 기존 `used <= count < cap` → **`used > 0 and count >= used`**.
`count >= cap`(계정이 이미 지금 믿는 상한만큼 들고 있는데도 거부됨)은 예전엔
"낮출 게 없다"며 버렸지만, 새 결론(상한=used)에서는 오히려 **가장 강한 만원 증거**다.
그대로 버리면 수렴 구멍이 그 자리에 남는다. 그래서 테스트 Q3 의 기대값을
`cap 30 유지` → `cap 1 로 수렴` 으로 바꿨다(그 케이스는 used=1, 서버 30 보유).

`rebalance` 도 함께 고쳤다: 틱 시작 시점의 `free` 를 붙들지 않고 매 건 다시 본다
(로컬 계산, 요청 0). 승격 한 건이 '만원'을 알려주면 그 자리에서 멈춘다.

## 2. 요청 산수 (100계정 기준)

| 경로 | 전 | 후 |
|---|---|---|
| 부트스트랩 20브랜드(여유 있음) | `20 × add()` = 20 × 100 × (목록+차단+등록) = **6,000** | `1 × register_all(20)` = 100 × (1 목록 + 20×(차단+등록)) = **4,100** (-32%) |
| 부트스트랩 20브랜드(함대 만원) | 20 × 100 × (목록+차단+등록+실패목록재조회) = **8,000** | 배치 1회 **4,100** + 만원 확정 뒤 나머지 **0** (-49%) |
| 차단 키워드 1개 재시도 | 100 × (목록+차단+**목록재조회**) = **300** | 100 × (목록+차단) = **200** (-33%) |
| 만원 상태 rebalance 1틱(대기 25건) | 25 × 100 × 3 = **7,500** | **0** (`free<=0` 이면 즉시 반환) |
| 여유가 있다고 믿는 상태의 rebalance 1틱(대기 25건) | 25벌(재현 로그의 25) | **1벌** (첫 실패에서 만원 확정 후 중단) |

- Finding 3: `register_many` 는 실패 때마다 계정 목록을 다시 GET 했지만, 답을 이미
  갖고 있었다 — `skip_existing` 경로(라우터의 유일한 경로)에서
  `len(existing) + len(added)` 가 곧 지금 보유수다. 라이브 조회는
  `skip_existing=False` 폴백에만 남겼다.
- Finding 8: `add_many` 는 슬롯에 들어갈 만큼을 `register_all` 한 번으로 묶는다.
  `register_all` 이 계정별 결과를 세 정수로 뭉개 부분 실패를 귀속할 수 없으므로,
  `failed > 0` 이면 배치 결과를 버리고 키워드별로 다시 태운다(그때 이미 들어간 것은
  `skipped` 로 걸러져 등록 요청을 더 쓰지 않는다). 배치가 통째로 거부되면 개별
  재시도 **전에** 상한을 관측해, 이어지는 `add()` 들이 요청 없이 스윕으로 간다.
  반환 모양(키워드별 결과 리스트)은 그대로다 — main.py 가 키워드마다 경로를 로그한다.
- 라우터에는 네트워크 I/O 를 넣지 않았다. `capacity()` 는 로컬 dict 집계뿐이다.

## 3. Finding 10 — 생산자 쪽 커버

`keyword_router_test.py` 섹션 T 에 네트워크 없는 `_StubAPI`(KeywordAlertAPI 서브클래스,
`__init__` 우회로 httpx 미생성) + `_StubMulti`(`_valid` 만 가짜) 를 넣어
`register_many` / `register_all` 본체를 그대로 태운다. 목록 조회 횟수까지 센다.

리뷰어가 살아남았다고 지적한 두 뮤턴트를 실제로 죽이는지 확인:

`register_many` 의 `out["account_count"] = ...` 를 지운 뒤:

```
===== 148/155 PASS =====
  실패: 실패 시 account_count 를 보고한다
  실패: 보고값이 실제 보유수
  실패: 일부 성공 시 보고값 = 기존+추가
  실패: 보고값이 서버 실제와 일치
  실패: register_all 이 observed_count 를 보고한다
  실패: observed_count 는 실패 계정 실측의 최댓값
  실패: 진짜 반환값으로도 free 가 0 으로 수렴
```

`register_all` 의 `total["observed_count"] = ...` 를 지운 뒤:

```
===== 152/155 PASS =====
  실패: register_all 이 observed_count 를 보고한다
  실패: observed_count 는 실패 계정 실측의 최댓값
  실패: 진짜 반환값으로도 free 가 0 으로 수렴
```

(두 뮤턴트 모두 확인 후 `git checkout --` 로 되돌렸고, 되돌린 상태에서 155/155 재확인.)

## 4. 재현 → 수정 전/후

리뷰어 시나리오(서버 상한 20, 이전 경로로 5개 선등록, 라우터 `used=15`)를 섹션 R 로
먼저 넣고 수정 전에 돌린 결과 — 리뷰어가 본 숫자와 일치한다
(`{'cap': 20, 'used': 15, 'free': 5}`, rebalance 1회가 추가로 태운 register_all = 46-21 = 25):

```
  [FAIL] 첫 거부 뒤 free 는 0 (수렴)  {'cap': 20, 'used': 15, 'free': 5}
  [FAIL] 관측 상한은 라우터가 쓸 수 있는 슬롯수(used)로 수렴  {'cap': 20, 'used': 15, 'free': 5}
  [FAIL] 수렴 뒤 새 키워드는 요청 0  21
  [FAIL] 만원이면 rebalance 요청 0  46
  [FAIL] 틱 도중 만원을 알면 즉시 멈춘다(큐 전체를 훑지 않음)  25

===== 110/115 PASS =====
```

수정 후 같은 구간:

```
  [PASS] 첫 거부 뒤 free 는 0 (수렴)  {'cap': 15, 'used': 15, 'free': 0}
  [PASS] 관측 상한은 라우터가 쓸 수 있는 슬롯수(used)로 수렴  {'cap': 15, 'used': 15, 'free': 0}
  [PASS] 수렴 뒤 새 키워드는 요청 0  16
  [PASS] 만원이면 rebalance 무동작
  [PASS] 만원이면 rebalance 요청 0  16
  [PASS] 틱 도중 만원을 알면 즉시 멈춘다(큐 전체를 훑지 않음)  1
```

## 5. git

```
$ git log --oneline -2
e19d526 test: 생산자 보고값 단언을 KeyError 대신 FAIL 로 잡게
87b4790 fix: 관측 상한이 수렴하도록 '만원'의 정의를 하나로

$ git status --short
 M delivery/integrated/manual_gui/main.py
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

내 담당 파일 3개(`daangn_ext/keyword_router.py`, `daangn_ext/keyword_alert_api.py`,
`keyword_router_test.py`)는 전부 커밋되어 작업 트리에 남아 있지 않다.
` M main.py` 는 같은 워크트리에서 작업 중인 다른 에이전트의 변경분이고 나는
손대지 않았다. `??` 는 이 리포트와 다른 에이전트들이 남긴 리포트 파일.

## 6. 테스트 결과 (실제 출력 꼬리)

`delivery/integrated/manual_gui/` 에서 `/Users/younglee/당근부동산_숨고/.venv/bin/python <파일>` 로 실행.

keyword_router_test.py (104 → 155):
```
  [PASS] 진짜 반환값으로도 free 가 0 으로 수렴  {'cap': 15, 'used': 15, 'free': 0}

===== 155/155 PASS =====
```

app_api_test.py:
```
==============================================
44/44 PASS
```

sweep_queue_test.py:
```
  [PASS] touch 가 조건을 안 지움  {'keyword': '샤넬', 'min': 100, 'max': 200, 'exclude': ['가품'], 'at': 77}

===== 29/29 PASS =====
```

article_watch_test.py:
```
  [PASS] 백필 묘비 출처 상수  

===== 191/191 PASS =====
```

notify_test.py:
```
==============================================
54/54 PASS
```

robust_test.py:
```
==============================================
29/29 PASS
```

e2e_chain_test.py:
```
==================================================
10/10 PASS
```

**건너뛴 것**: `unified_tab_wiring_test.py`, `headless_sweep_test.py` — 둘 다
`main.py` 를 import 하는데 다른 에이전트가 지금 `main.py` 를 편집 중이라 결과가
내 변경분의 것인지 구분되지 않는다. 다만 두 파일이 의존하는 라우터 공개 API는
그대로다: `add_many(keywords, min, max, exclude, core_only=, log=)` 시그니처와
키워드별 결과 리스트 반환 모양을 유지했다(main.py:2619·2645·4717 이 그대로 동작).

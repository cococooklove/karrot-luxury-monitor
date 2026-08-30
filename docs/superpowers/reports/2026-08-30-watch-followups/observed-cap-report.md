# 슬롯 상한 관측값(observed cap) — 구현 보고 (개정판: 실측 기반)

## 개정 이유

1차 구현은 `register_all` 반환값에 선택적 `fleet_full` 플래그가 오지 않는 한
절대 관측이 발동하지 않는, 사실상 죽은 코드였다(실제 `keyword_alert_api.py`가
그 필드를 채워 보낸 적이 없어서). "구현했지만 실제로는 절대 안 켜지는 기능"은
안 만든 것보다 나쁘다는 지적을 받아, `keyword_alert_api.py`도 수정 범위에
포함시켜 실제로 서버가 돌려주는 값을 재는 방식으로 다시 만들었다.

## 무엇을 측정하나

`KeywordAlertAPI.register_many()`가 실패가 하나라도 있었을 때만(성공 경로엔
요청을 더 안 태움) `self.keywords()`를 한 번 더 호출해 그 계정이 지금 실제로
몇 개를 들고 있는지(`account_count`)를 반환값에 얹는다. `register_all()`은
계정들을 순회하며 실패가 있었던 계정들의 `account_count` 중 **최댓값**을
`observed_count`로 모아 기존 세 키(`added`/`skipped`/`failed`)는 그대로 둔
채 나란히 반환한다(그 세 키는 `main.py`와 라우터가 이미 그 모양으로 읽으므로
재구성하지 않았다).

## 판단 규칙과 근거 (`KeywordRouter._observe_measured_count`)

차단 키워드 실패와 진짜 한도 초과는 `register_many` 내부에서만 구분되고(사전
`is_banned` 체크로 걸리는 것과, 실제 등록 시도가 서버에서 거부되는 것) 그
구분은 `register_all`의 반환 모양에서 사라진다 — 그래서 "왜 실패했는가"를
알아내려 하지 않고, 실패한 계정이 실제로 몇 개를 갖고 있는지(`count`)만
본다. 판단은 이 부등식 하나다(`used`/`cap`은 실패 직전에 잰
`capacity()["used"/"cap"]`, add() 안에서 라우트가 바뀌기 전 값):

- `count < used` → **버림**. 이 계정이 다른 계정만큼 아직 못 따라간
  것일 수 있다(막 유효해진 계정 등). "적게 갖고 있다"는 그 자체로 상한의
  증거가 아니다 — 차단 키워드가 실패한 계정이 12개를 갖고 있다고 해서
  상한이 12 라는 뜻은 아니다(요청받은 예시 그대로).
- `count >= cap` → **버림**. 지금 믿는 상한만큼(또는 그 이상) 이미
  갖고 있다는 뜻이라 "더 낮은 상한"의 증거가 아니다. 오히려 로컬 집계
  (`used`)가 실제보다 적게 세고 있다는 신호에 가깝고, 그건
  `seed_from_server`의 몫이지 여기서 다룰 문제가 아니다.
- `used <= count < cap` → **신뢰**. 이 라우터가 이미 밀어 넣었다고
  믿는 만큼은 실제로도 갖고 있는데("따라잡음"), 그런데도 이번 등록은
  거부됐다 — 진짜 한계가 지금 믿는 상한보다 낮다는 가장 직접적인 증거.
- `used <= 0`(성공 이력 없음) → **버림**. 비교 기준 자체가 없다.

`used < cap`은 `add()`의 사전 체크(`capacity()["free"] <= 0`이면 애초에
등록 시도를 안 함) 때문에 이 분기에선 항상 구조적으로 성립한다 — 그래서
"신뢰" 구간(`[used, cap)`)이 논리적으로 항상 존재하고, 실측값이 여기 들어올
때만 실제로 상한이 **내려간다**(그 이하에서는 증거 부족, 그 이상에서는
이미 상한과 같거나 커서 내릴 게 없음 — 두 경우 모두 아무 일도 안 함).

이전에 만든 `fleet_full` 명시 신호 경로(`_observe_cap_full`)는 코드에 남겨
뒀다 — 비용이 없고, 더 나은 증거(서버가 명시적으로 사유를 알려주는 API가
생기는 등)가 나오면 그대로 쓸 자리이기 때문이다. 다만 오늘 실제로 라우터의
상한을 움직이는 것은 이 실측 경로다.

## 관측값을 되돌리는 경로 (변경 없음)

- `reset_observed_cap()` — 평상시 탈출구. 언제나 열려 있다.
- `seed_from_server()` — routes가 비어 있을 때만 열리는 부수적 보너스.

## 그 외 (변경 없음)

- 관측치는 routes 파일에 예약 키 `"  __cap__"`(공백 포함, 사용자 키워드와
  절대 안 겹침)로 함께 저장. 손상되거나 타입이 안 맞으면 기본 상한으로
  안전하게 저하.
- `capacity()`는 `min(slot_cap, observed_cap)`을 `cap`으로 반환.
- 관측은 절대 스스로 오르지 않는다(실측 경로도 `fleet_full` 경로도 동일하게
  "새 값이 기존 관측치보다 낮을 때만" 갱신).
- 상한이 낮아질 때 `log()`로 경고 남김.

## git log (실제 출력)

```
5b99620 fix: 슬롯 상한 관측을 추론이 아니라 실측으로 다시 만듦
e731f8f refactor: 스윕 엔진을 별도 모듈로 분리(daangn/sweep_engine.py)
```
(e731f8f 은 동시 작업 중인 다른 에이전트의 커밋 — 같은 브랜치를 공유하는
워크트리라 히스토리가 섞여 있다.)

## 테스트 결과 (실제 실행 출력 꼬리)

`python3 keyword_router_test.py`:
```
===== 104/104 PASS =====
```
(N~P 섹션: `fleet_full` 명시 신호 경로. Q 섹션: 신규 실측 경로 — used 이상·
cap 미만이면 하향/ used 미만이면 뒤처짐으로 무시/ cap 이상이면 무변화/
used=0이면 무시/ 미상승 불변식/ 재시작 영속/ reset 이 실측 관측치도 지움.)

`python3 sweep_queue_test.py`:
```
===== 29/29 PASS =====
```

`python3 article_watch_test.py`:
```
===== 177/177 PASS =====
```

`python3 unified_tab_wiring_test.py`:
```
===== 122/123 PASS =====
  실패: 헤드리스가 dedupe_new_matches 를 쓴다
```
이 실패는 `main.py` 소스 텍스트("dedupe_new_matches(" in _src)를 검사하는
항목이다 — `main.py`는 지금 다른 에이전트가 동시에 편집 중이며(작업 중간
상태), 이번 변경(`daangn_ext/keyword_router.py`, `daangn_ext/keyword_alert_api.py`,
`keyword_router_test.py`)과는 무관하다. `git diff --stat`로 확인: 이번
커밋에 `main.py`는 포함하지 않았다.

`python3 notify_test.py`: `register_all`/`register_many`를 쓰지 않아 원래
이번 변경과 무관하지만 실행해봤다 — `main.py` import 시점에
`SyntaxError: expected 'except' or 'finally' block` (main.py:4618) 발생.
같은 이유(다른 에이전트의 main.py 동시 편집 중간 상태)로 이번 변경과 무관.

`python3 nationwide_test.py`: `register_all`을 쓰지 않는다.
`FileNotFoundError: proxies.txt` — 이번 변경 이전부터 있던, 저장소에
`proxies.txt`가 없어서 나는 환경 문제이며 이번 변경과 무관.

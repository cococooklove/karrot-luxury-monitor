# 레드 테스트 2건 진단/수정 보고

`git log --oneline -2` (작업 시작 시점 HEAD):
```
50bdd69 test: 오래 빨갛던 레거시 테스트 4종 정리
d7119ff feat: 상태칩을 누르면 해당 고급 패널 항목으로 데려간다
```

## Case 1 — `proxy_test.py`: 임포트 단계 크래시

### 진단
`proxies.txt`(실 프록시 계정, gitignore)가 없는 신규 체크아웃에서는 모듈 최상단
`open("proxies.txt")`에서 `FileNotFoundError`로 죽어 스위트가 시작조차 못 함.
코드 결함이 아니라 "비밀 파일이 없으면 그 부분만 못 돈다"는 자연스러운 상태를
예외로 처리하지 않은 게 문제. 부수적으로 원본은 `OUT.json` 경로도
다른 세션의 스크래치패드 절대경로(`/private/tmp/.../efe67086.../OUT.json`)로
하드코딩돼 있어, proxies.txt가 있는 환경이라도 그 경로에서 또 죽는 잠재 결함이 있었음
(같은 패턴이 `nationwide_test.py`에도 있음 — 아래 "범위 밖" 참고).

### 조치
- ck()/R 표준 테스트 골격으로 전환, 3단 구성:
  1. HTML 파싱 경로(`parse()`) — 네트워크·비밀 무관, 항상 실행. 정상/JSON 깨짐/컨텍스트
     없음 3가지 케이스 검증.
  2. `proxies.txt` 라인 형식 — 저장소에 커밋된 `proxies.example.txt`를 구조 픽스처로 써서
     스킴(`http(s)://`)·`@` 구분자 파싱 가능 여부를 실 프록시 없이 검증.
  3. 실 프록시 연결성/스케일링 — `proxies.txt` 있을 때만 실행. 없으면 `[SKIP]` 한 줄 출력
     (이유 + 무엇을 두고 재실행해야 하는지) 후 그 구간은 `R`에서 제외, exit 0.
- `OUT.json` 경로를 하드코딩 절대경로 → 상대경로(`OUT.json`, 스크립트 자기 디렉터리 기준)로
  수정. 이 저장소엔 실제로 `OUT.json`이 커밋돼 있어(`git ls-files`로 확인) 그냥 존재함 — 없는
  환경 대비로만 대표 지역 1곳(`역삼동-6035`) 폴백을 추가.
- 가짜 프록시(`proxies.example.txt`를 `proxies.txt`로 복사)로 실행해 "있을 때 진짜로
  테스트하는지" 확인: 개별 검증·병렬 스케일링 둘 다 정직하게 FAIL(exit 1) — 가짜 IP라
  연결이 안 되니 당연한 결과. 즉 파일이 있으면 바이패스가 아니라 실제로 검증함.

## Case 2 — `e2e_chain_test.py`: "refresh 토큰도 회전 반영" FAIL

### 진단 — 코드 버그 아님, 테스트 픽스처 결함
`TokenManager.ensure()`(`daangn_ext/token_manager.py`)를 직접 재현:
```python
new_access, new_refresh = self.refresh_fn(acc)
acc.access = new_access
if new_refresh:
    acc.refresh = new_refresh   # ← 정상적으로 회전 반영함
```
격리된 재현 스크립트로 확인한 결과, `ensure()`는 `new_refresh`가 있으면 항상
`acc.refresh`에 반영한다 — 이 로직 자체는 옳다.

실패 원인은 테스트의 `mkjwt(sub, ttl, typ)` 헬퍼: `iat = int(time.time())`(초 단위,
난수 없음)이고 서명은 항상 고정값 `b"s"*32`. 최초 발급(`accounts[0]["refresh"]`,
`ttl=21600`)과 `mock_refresh()`가 만드는 새 refresh(`ttl=21600`, 같은 `sub`)가
같은 1초 안에 생성되면 payload가 완전히 동일해져 **문자열까지 동일한 토큰**이 된다.
스크립트 실행 속도상 거의 항상 같은 초 안에 두 번 호출되므로 결정적으로 실패.

증명: `mkjwt`에 nonce 없이 재현하면 3회 연속 `before == after` `True`.
`mkjwt`에 nonce("orig"/"NEW")를 넣어 두 호출을 구분되게 만들면 즉시
`acc0.refresh != orig_refresh` → `True`로 뒤집힘 — 즉 코드는 옳고, 테스트 픽스처가
회전 여부를 초 단위 우연에 맡기고 있었을 뿐.

### 조치
`e2e_chain_test.py`의 `mkjwt()`에 모듈 전역 증가 카운터 `jti`를 payload에 추가해
같은 초 안에서도 호출마다 항상 다른 토큰 문자열이 나오도록 수정. 어서션은 그대로 두고
(설계 의도는 맞음 — refresh 회전은 실제로 검증해야 할 동작) 픽스처만 고침.

## 두 파일 실행 결과 (literal tail)

`proxy_test.py` (proxies.txt 없는 이 환경):
```
[SKIP] proxies.txt 없음(gitignore) — 실 프록시 연결성/스케일링 실측 생략. 실행하려면 이 디렉터리(...)에 실 프록시 계정을 담은 proxies.txt를 두고(형식은 proxies.example.txt 참고) 재실행할 것.

==================================================
===== 6/6 PASS =====
```
exit 0.

`e2e_chain_test.py`:
```
==================================================
10/10 PASS
```
exit 0.

## 회귀 확인 (지정 15종, literal tail)

| 파일 | tail |
|---|---|
| article_watch_test.py | `===== 191/191 PASS =====` |
| unified_tab_wiring_test.py | `===== 148/148 PASS =====` |
| watch_listing_test.py | `===== 47/47 PASS =====` |
| article_watch_wiring_test.py | `===== 27/27 PASS =====` |
| keyword_router_test.py | `===== 104/104 PASS =====` |
| sweep_queue_test.py | `===== 29/29 PASS =====` |
| supervisor_test.py | `===== 20/20 PASS =====` |
| backfill_test.py | `===== 26/26 PASS =====` |
| sweep_engine_test.py | `===== 57/57 PASS =====` |
| headless_sweep_test.py | `===== 101/101 PASS =====` |
| notify_test.py | `54/54 PASS` |
| robust_test.py | `29/29 PASS` |
| _construct_test.py | `===== 9/9 PASS =====` |
| button_test.py | `===== 30/30 PASS =====` |
| full_test.py | `===== 17/17 PASS =====` |

All exit 0.

## 그 외 이 디렉터리의 `*_test.py` 상태 (수정 안 함, 보고만)

지정 목록·Case 1/2 어디에도 없는 파일 중 4개가 여전히 레드:

- `_area_test.py` — `AssertionError: 강남구 없음` (자동 지역 6537개 로드는 됐지만 "강남구"
  탐색 실패)
- `_pool_test.py` — `proxy_test.py`와 동일한 패턴: 모듈 최상단에서
  `open("proxies.txt")` → `FileNotFoundError`
- `_proxy_ui_test.py` — `AssertionError: 프록시 라벨 없음` (`hasattr(w, "proxyLabel")` /
  `autoProxyLabel` 실패 — UI 위젯 속성명이 바뀌었거나 아직 없는 듯)
- `nationwide_test.py` — `proxy_test.py`와 동일한 패턴(`open("proxies.txt")` at import)
  + 원래 있던 `OUT.json` 절대경로 하드코딩(다른 세션 스크래치패드 경로)도 별도 결함

이 4개는 지시대로 손대지 않음.

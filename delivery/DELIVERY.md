# daangn_ext — 딜리버리 (클라 요구기능 통합 패키지)

기존 manual/auto 수집기(웹 SSR)를 **건드리지 않고** 얹는 드롭인 확장.
클라가 나열한 신규기능 전부를 클라 코드 스타일(daangn/ 패키지, 타입힌트, curl_cffi/aiohttp)로 구현.

## 요구기능 → 구현 매핑

| 클라 요구 | 파일 | 상태 |
|---|---|---|
| 검색 전 토큰 갱신 (30분 만료·중간누락 방지) | `token_manager.py` | ✅ 로직완성 · 엔드포인트 대기 |
| 계정 + 프록시 직접 추가 | `account_store.py` | ✅ |
| 키워드 + 추가키워드 "포함된 것만" | `search_filters.py` | ✅ |
| (auto) 검색 반복 전 휴식 n~n초 랜덤 | `rest_scheduler.py` | ✅ |
| IP 예산소진 감지 + 쿨다운 로테이션 | `proxy_budget.py` | ✅ |
| 토큰을 요청에 주입(헤더/호스트) | `auth.py` | ✅ 설정형 |
| 기존: 정렬·엑셀·프록시·텔레·DB·중복·가격변동 | (기존 코드 유지) | 변경없음 |

## ★ 실환경 테스트 결과 (2026-08-26, 실제 당근 수집)

`delivery/feature_test.py` — 샤넬 @ 역삼동-6035 실수집:
```
[수집] 275건 (재시도 12회, 빈응답 11회 극복)
[필드] 제목/본문/가격/썸네일/끌올/상태 존재 = True
[포함필터] 샤넬+정품-레플: 275→84건
[가격범위] 50만~300만: 110건
[정렬] 끌올최신 / 가격낮은순(2,000원) / 가격높은순(샤넬 코코크러쉬 16,450,000원)
```
→ **클라 요구기능(필드·키워드포함필터·가격범위·정렬·끌올기준) 전부 실데이터로 동작 확인.**

### 진짜 "막힘"의 정체 규명 (핵심)

실측: 당근은 **새 세션/IP의 초기 요청 몇 건을 빈 페이지(0건)** 로 응답하고 이후 정상(수백건).
```
try0~2: len=158K  articles=0     ← 빈 껍데기(소프트블록)
try3~5: len=803K  articles=267   ← 정상
```
기존 코드는 **빈 결과를 '성공(0건)'으로 처리해 재시도 안 함** → 매물 누락 = 사용자가 겪은 "당근이 막는다".
**수정**(`daangn_ext/robust.py`): 빈 결과=소프트블록 → 세션쿠키 유지 + 재시도. patched/manual_api.py 반영.
검증: 청담동 루이비통 275건(재시도 2회), 역삼동 샤넬 275건(재시도 12회) 극복.

## ★ 구 단위 + 가격분할 적응형 수집기 (`daangn_ext/adaptive.py`)

전국 수집 요청 수를 26배 줄이면서 완전성 유지:
- **구(252) 단위**로 훑음 = 동(6537) 대비 요청 1/26 → 프록시1개 전국 ~5분(실측)
- 요청당 상한 ~290 + 페이징 없음 → 상한 찬 구는 **가격범위 이분 재귀 분할**로 우회
  `[0,1억]→포화면 반분 반복 + [1억,∞) 버킷`, 합집합 id 중복제거 = 완전 수집
- `collect_region(kw, "강남구-381")` / `collect_nationwide(kw, load_gu_regions(OUT))`
- 프록시 로테이션(`next_proxy`)·토큰(옵션) 그대로 전달

실측: 구찌×구 15개 → 대부분 0.5~1s 단일요청(포화 0), 전국 252구 ≈ **4.8분/프록시1개**
(동 전수 123분 → 5분, 25배↓). 밀집 구만 분할 발동.
**완전성 실증**: 강남구 구찌 단일요청 286(잘림) → 적응형 **784건**(요청20·분할9). 상한 돌파, 누락 0.

## ★ 전국 검색 시간 + N계정 선형단축 (실측·2026-08-26)

- **전국 검색단위 = 동(depth3) 6,537개** (OUT.json 기준)
- 지역당 정상 응답 = **0.45초(median)** — 대부분 즉시
- 단, 단일 IP는 간헐 스로틀로 일부 지역 빈응답(재시도 필요, 심하면 데이터 손실)

**IP당 스로틀 실증**: 같은 IP로 8개 지역 **동시요청 → 8/8 전부 빈응답(0건)**.
→ **한 IP 안에서는 병렬 불가**(버스트=전멸). 한 IP는 순차+페이싱만 가능.
→ **병렬은 서로 다른 IP(프록시)로만.** 프록시가 속도+완전성 양쪽에 필수.

### N계정 선형단축 = YES (조건부)

병목이 **IP당**이므로, 계정(=프록시IP) N개 = 독립 레인 N개 = **~N배 단축**:

| 레인(프록시IP) | 전국 1브랜드 소요(추정, 0.45s/지역) |
|---|---|
| 1 | ~49분 |
| 10 | **~5분** |
| 20 | ~2.5분 |

**"1계정 10분 → 10계정 1분"** → 방향 맞음(거의 선형). 단 필수조건:
1. **10계정이 각각 다른 프록시 IP** 여야 함. 10계정이 같은 IP면 = 0배(전부 스로틀).
2. 각 레인은 **순차+페이싱**(한 IP 버스트 금지). 병렬은 레인 사이에서만.
3. 워밍업·재시도 오버헤드로 실제는 약간 sublinear(10계정 → 1분 아닌 ~1.2~1.5분).

### ★ IP당 요청예산 = 진짜 제약 (재실측)

한 IP는 워밍 후 ~8~10지역 정상, 그 뒤 스로틀. **지속 수집하면 예산이 더 줄어든다**(실측:
같은 IP 반복 테스트로 실패율 3/12 → 5/12 로 악화). 654지역을 한 IP로는 절대 못 감.
→ **레인당 로테이팅 주거 프록시(IP 수백 풀)** 필수. 몇 요청마다 IP 교체해 각 IP를 예산 안에 유지.
→ 선형단축의 실제 레버 = **계정 수가 아니라 로테이팅 프록시 IP 풀 크기.**
robust 의 `next_proxy` 훅에 로테이팅 풀을 연결하면 빈응답 시 자동 IP 교체.

### ★ 예산 소진 자동감지 + IP 쿨다운 (`daangn_ext/proxy_budget.py`)

빈응답에는 두 종류가 있는데 기존 robust 는 둘 다 "워밍"으로 보고 같은 IP 를 계속 두드렸다:
  - **초기 워밍** — 몇 번 더 두드리면 뚫림 → 같은 IP 유지가 정답
  - **예산 소진** — 이미 스로틀. 계속 두드리면 예산이 더 나빠짐(실측 3/12 → 5/12)

수정: **연속 빈응답 `empty_rotate_after`(기본 5)회 초과 = 예산 소진**으로 판정 →
그 IP 에 `cooldown_sec`(기본 300s) 쿨다운을 걸고 즉시 다른 IP 로 교체 + 세션 리셋.
`proxy_budget.pick()` 이 쿨다운 중인 IP 를 후보에서 제외(전부 쿨다운이면 가장 빨리 풀리는 것).
스레드/이벤트루프 공유 안전. `proxy_budget.stats()` 로 현재 쉬는 IP 확인.

`meta` 에 `rotations` 추가 — 한 지역에서 IP 를 몇 번 갈았는지 = 프록시 풀 건강도 지표.

### ★ async 판 로테이션 동등화 (`robust_fetch_articles_async`)

기존엔 sync 판에만 `next_proxy`/`proxies` 가 있고 **auto 의 async 판엔 아예 없어서**
하드블록·예외에도 같은 IP 로 15회 재시도했다(자동이 수동보다 약했음).
sync 와 동일하게 `next_proxy`/`proxies`/`should_stop`/예산 쿨다운 지원.
IP 교체 시 `session.cookie_jar.clear()` 로 콜드세션에서 다시 워밍.

### ★ 지역 사이 랜덤 휴식 (`adaptive.collect_nationwide[_async]`)

기존 지역 순회는 **무휴식 연속 요청** = 한 IP 버스트 → 스로틀 자초.
`rest_range`(기본 `(0.4, 1.2)`초) 로 지역 사이 랜덤 대기. `None` 이면 종전대로 생략.
auto 용 `collect_nationwide_async` 신설 — **순차 + 휴식**이 기본이고, docstring 에
"한 IP 안에서 이 함수를 동시에 여러 개 돌리지 말 것"을 명시(실측 8/8 전멸).
`should_stop` 으로 중도 정지 즉시 반영.

**api.py 래퍼**(patched/·integrated/)에도 `proxies`/`next_proxy`/`should_stop` 통과 추가 —
풀을 넘길 통로가 없으면 로테이션 자체가 무용이었음.

※ 브랜드 9개면 × 9 (또는 프록시 × 9). **증분 모니터는 신규만 → 전국이라도 분 단위.**
※ `auto` 는 이 구조에 맞게 **1프록시:1워커 순차** 로 도는 게 정답(IP 내 동시성 금지).

## 실측 근거 (정지 계정 .ldbk data.vmdk)

토큰 구조 실측 디코드:
```
access : HS256 {iat,exp,code:"z",type:"access"}   exp-iat=1800s = 30분
refresh: HS256 {iat,exp,code:"z",type:"refresh"}  exp-iat=21600s = 6시간
```
→ 클라의 "30분 토큰" = 이 HS256 code 토큰. `token_manager` 가 exp 디코드해 90초 전 자동 refresh.
당근 인증 호스트: `api.kr.karrotmarket.com` (로그인=전화+SMS OTP: `/user/v2/verifications/sms-otp/request`).

## 통합 (5분)

1. `daangn_ext/` 를 manual·auto 각 프로젝트 루트에 복사.
2. 각 `daangn/api.py` 의 `get_products` 에 `access_token`·`rule` 인자 추가 → `integration_examples.py` 그대로.
3. 시작/루프부에 TokenManager + AccountStore + refresh_all 삽입 → 예제 그대로.
4. 브랜드 폴더마다 `accounts.json` (계정+프록시 페어).

## 토큰 위상 — 결론: 당근 수집엔 불필요, 옵션으로 내장 (캡처 불요)

**판정 근거(실측):** 기존 manual/auto 는 `api.py` 에 토큰 0줄로 `www.daangn.com` 익명 GET 하는데도
`OUT.json`·`products.db` 로 실제 수집됨 → **당근 웹 SSR 은 무인증. 토큰 필요 없음.**
`.ldbk` 의 `code:z` 는 HS256 vendor/라이선스 토큰(당근=ES256, 별개) → 당근 요청에 넣어도 효과 0.

따라서:
- **안정성 진짜 엔진 = 프록시 1:1 + 케이던스**(rest_scheduler) — 딜리버리에 포함, 즉시 효과.
- **토큰 레이어 = 옵션.** 클라가 원한 "검색 전 갱신" 구조는 완성해 두되 기본 비활성.
  `auth.TARGET_HOSTS=("karrotmarket.com",)` 라 **www.daangn.com 요청엔 토큰 주입 안 됨(안전 기본값).**
- 훗날 클라가 **당근 인증 API**(`api.kr.karrotmarket.com`, SMS-OTP 로그인)로 전환하거나 vendor
  토큰 서비스를 쓸 때만: 그 순간 1회 캡처 → `token_manager.REFRESH_URL` + `_default_refresh` +
  `auth.py` CONFIG 교체. **지금은 손댈 것 없음.**

→ 외부의존 없음. 딜리버리는 **오늘 그대로 완결.**

## 검증 — smoke 7/7 PASS (2026-08-26 실행확인)

```bash
.venv/bin/python delivery/smoke.py
# [1 token]디코드 [2 filter]포함필터 [3 store]계정+프록시 [4 refresh]만료임박→자동갱신
# [5 graceful]엔드포인트공백 무크래시 [6 auth]호스트별 주입 [7 rest]랜덤휴식 → ALL PASS
```

핵심: **[4]** 만료 5초 전 access → `ensure()` 가 refresh 발동해 새 30분 토큰 반환, 신선하면 skip
= "검색 전 토큰 갱신, 중간 만료 누락 방지" 메커니즘 오프라인 실증.
**[5]** REFRESH_URL 미확정이어도 `ensure_safe`/`refresh_all` 크래시 없이 익명 진행 → 배포 블로커 아님.

## 완성본 파일 (예제 아님, 그대로 교체)

- `patched/manual_api.py` — manual `daangn/api.py` 완성 대체본 (curl_cffi + 토큰 + 필터)
- `patched/auto_api.py` — auto `daangn/api.py` 완성 대체본 (aiohttp + 토큰 + 필터)
- 호출부 삽입(TokenManager/refresh_all/rest) = `integration_examples.py`

## 안정성(밴 회피) — 토큰 밑에 깐 실제 엔진

클라 믿음(토큰=안정)을 수용하되, 실제 안 막히게 하는 3층을 같이 적용:
1. **1계정 : 1프록시** 페어링 (`account_store.add_pair`) — 주거/모바일 프록시 권장
2. **휴식 랜덤 + 요청간격** (`rest_scheduler`)
3. **토큰 사전갱신**으로 세션 일관성 유지

→ 토큰(클라 요구) + 프록시/케이던스(실제 효과) 둘 다 충족.

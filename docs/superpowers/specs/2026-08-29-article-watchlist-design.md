# 매물 워치리스트 (가격변동 추적) — 설계

작성 2026-08-29. 대상 `delivery/integrated/manual_gui/`.

## 배경

클라 요구는 두 가지다. 새 매물을 빨리 잡는 것, 그리고 이미 잡은 매물의 가격 변동을
아는 것. 앞의 것은 키워드 알림 탭(telefunc 폴링)이 이미 한다. 뒤의 것은 지금 자동
모니터 탭이 지역 전체를 반복 검색해서 가격을 비교하는 방식으로 하고 있고, 요청량이
크다.

실측으로 단건 조회 경로가 열려 있음을 확인했다.

```
GET https://webapp.kr.karrotmarket.com/api/v24/articles/{id}.json
Authorization: Bearer <access>
→ 200, 약 3.3KB
```

응답에 `price`, `status`(ongoing 등), `status_name`, `updated_at`, `published_at`,
`republish_count`, `watches_count`, `chat_rooms_count`, `reads_count`, `destroyed_at`,
`is_unpublished`, `visible` 이 들어 있다. 검색 API 는 `withoutCompleted: true` 라
판매완료 매물이 결과에서 빠지므로 삭제와 구분되지 않는데, 단건 조회는 구분된다.

묶음 조회는 없다. `GET /api/v24/articles.json` 은 `ids` / `article_ids` / `ids[]` /
`id` / 파라미터 없음 전부 `{"status":{"code":"invalid_params"}}` 를 돌려준다.
따라서 재조회는 1건 1요청이고, 요청량은 추적 대상 수와 점검 주기로만 조절한다.

## 범위

이번 단계는 워치리스트만 만든다. 자동 모니터 탭은 그대로 둔다.

**하는 것**

- 키워드 알림으로 잡힌 매물을 워치리스트에 넣는다
- 등급별 주기로 단건 재조회한다
- 가격 인상·인하, 판매완료, 삭제, 끌올을 알림으로 보낸다

**하지 않는 것 (2단계)**

- 지역 스윕 엔진(`app_api`/`adaptive`/`search_filters`)의 알림탭 이관
- 자동 모니터 탭 삭제와 `self._notify` 로딩 분리
- `auto_seen.db` + `match_seen.json` 저장소 통합

## 구성

새 모듈 `daangn_ext/article_watch.py` 하나에 세 단위를 둔다. 각각 따로 테스트된다.

### ArticleDetailAPI

단건 조회만 담당한다. `KeywordAlertAPI` 와 같은 헤더 빌더(`_headers`)와 같은
`data/config.json` 을 쓴다.

```python
class ArticleDetailAPI:
    def __init__(self, access_token, config_path="./data/config.json", proxy=None)
    def fetch(self, article_id: str) -> dict
```

`fetch` 는 정규화된 dict 를 돌려준다: `id`, `price`(int), `status`, `title`,
`published_at`, `updated_at`, `republish_count`, `watches_count`, `chat_rooms_count`,
`destroyed_at`, `is_unpublished`, `visible`. 매물이 사라졌으면 `{"id": ..., "gone": True}`
를 돌려준다. 조회 자체가 실패하면 예외를 던진다 — 호출자가 삭제와 조회 실패를 구분해야
한다.

### WatchStore

sqlite `data/watch.db`, 테이블 하나.

| 컬럼 | 뜻 |
|---|---|
| `id` TEXT PK | article id |
| `title`, `region`, `url` | 알림 문구용 |
| `price` INTEGER | 마지막으로 확인한 가격 |
| `status` TEXT | 마지막으로 확인한 상태 |
| `republish_count` INTEGER | 끌올 감지용 |
| `published_at` INTEGER | 등급 판정 기준(epoch) |
| `first_seen`, `last_check` INTEGER | epoch |
| `next_check` INTEGER | 이 시각 이후면 점검 대상 |
| `tier` TEXT | `fresh` / `aged` / `dead` |
| `fail` INTEGER | 연속 조회 실패 횟수 |

인덱스는 `(tier, next_check)` 하나면 된다.

### WatchTracker

정책과 diff 를 담당한다. 네트워크는 주입받은 `ArticleDetailAPI` 로만 한다.

```python
class WatchTracker:
    def add_from_matches(self, matches: list[dict]) -> int
    def due(self, now: int, limit: int) -> list[str]
    def check_one(self, article_id: str, api) -> list[dict]   # 이벤트 목록
    def sweep(self, api_provider, budget: int, now: int) -> list[dict]
```

`sweep` 은 `due` → `check_one` 을 예산만큼 돌고 이벤트를 모아 돌려준다. 알림 전송은
하지 않는다 — 호출자가 한다.

## 등급과 예산

| 등급 | 조건 | 점검 주기 |
|---|---|---|
| `fresh` | 게시 48시간 이내 | 4시간 |
| `aged` | 게시 2~14일 | 24시간 |
| `dead` | 판매완료·삭제·게시 14일 초과 | 점검 안 함 |

`dead` 행은 지우지 않는다. 같은 매물이 다시 매칭으로 들어왔을 때 중복 알림을 막는다.

활성(`fresh` + `aged`) 상한은 300건. 넘으면 `published_at` 이 오래된 것부터
`aged` 로 내리고, 그래도 넘으면 가장 오래된 것을 `dead` 로 만든다.

예상 요청량은 활성 300건 기준 `fresh` 100건 × 6회 + `aged` 200건 × 1회 = 하루 약
800회다. 유효 토큰 계정으로 라운드로빈해서 나눈다. 계정당 하루 상한은 기본 300회로
두고(`AccountScheduler` 의 `daily_cap` 과 같은 값), 상한에 닿은 계정은 그날 건너뛴다.
`sweep` 의 `budget` 은 호출 주기와 남은 계정 예산에서 계산한다.

## 이벤트

`check_one` 은 저장된 값과 새로 받은 값을 비교해 이벤트를 만든다.

| 이벤트 | 조건 |
|---|---|
| `price_down` | 새 가격 < 저장 가격 |
| `price_up` | 새 가격 > 저장 가격 |
| `sold` | `status` 가 판매완료로 바뀜 |
| `deleted` | 조회 결과 `gone`, 또는 `destroyed_at` 있음, 또는 `is_unpublished` |
| `republished` | `republish_count` 증가 |

각 이벤트는 `{kind, id, title, url, old, new, at}` 형태다. `sold` 와 `deleted` 는
행을 `dead` 로 만든다.

## 오류 처리

- HTTP 404 / 410 → `deleted` 이벤트, `dead` 로
- HTTP 401 → 토큰 만료. 그 계정을 이번 스윕에서 빼고 다음 수확에 맡긴다
- HTTP 429 → 그 계정을 이번 스윕에서 빼고, 해당 매물 `next_check` 를 30분 뒤로
- 네트워크 예외 → `fail += 1`, `next_check` 를 한 주기 뒤로. `fail` 이 5 가 되면
  `dead` 로 내리고 로그만 남긴다(알림 없음)

## 배선

폴링 틱은 이미 있다(`main.py` `_auto_poll_tick` → `on_alert_poll_all`). 매칭 처리
직후 `tracker.add_from_matches(...)` 를 부른다.

재조회는 별도 QTimer 로 10분마다 `tracker.sweep(...)` 를 부른다. 폴링 틱과 붙이지
않는다 — 폴링 주기(기본 120초)와 재조회 주기는 두 자릿수 배 차이라 섞으면 예산
계산이 흐려진다. 야간 감속 배수(`_night_factor`)는 그대로 곱한다.

알림은 텔레그램과 구글시트를 그대로 쓰되 전송 스레드는 따로 둔다. 기존
`_NotifyThread` 는 매칭 문구에 맞춰져 있어 변동 이벤트를 끼워 넣으면 두 형식이
한 클래스에 섞인다. `SheetWriter` 는 워크시트를 고르는 인자가 없으므로 같은 시트에
종류 열(`가격변동`)을 붙여 쌓는다.

헤드리스(`_run_headless`)에도 같은 tracker 를 같은 주기로 넣는다.

GUI 는 키워드 알림 탭 안에 작은 영역 하나만 추가한다: 추적 중 건수, 다음 점검 시각,
최근 변동 20건 목록. 매물 더블클릭은 기존 동작을 따른다.

## 테스트

TDD 로 간다. 네트워크를 타지 않는 단위 테스트가 기본이다.

- `ArticleDetailAPI.fetch` — 저장해 둔 응답 fixture 로 정규화 결과 검증, 404 →
  `gone`, 429 → 예외
- 등급 판정 — 게시 시각별 `fresh` / `aged` / `dead` 경계
- `due` — `next_check` 지난 것만, `dead` 제외, `limit` 준수
- `check_one` — 가격 인상·인하·동일, 판매완료, 삭제, 끌올 각각 이벤트 하나씩
- 상한 — 301건째 투입 시 가장 오래된 것이 강등되는지
- 예산 — 계정 일일 상한에 닿으면 그 계정이 빠지는지
- 실패 누적 — 5회 실패 후 `dead`, 알림 없음

통합 테스트는 서버에서 유효 토큰으로 실제 1건 조회까지만 한다.

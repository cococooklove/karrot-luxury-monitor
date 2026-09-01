# 당근 앱 API — 중고거래 검색 (2026-08-27 캡처 해독)

iPhone + mitmproxy 캡처로 확보. **인증서 피닝 없음** → 탈옥·루팅·Frida 불필요.
**서명/HMAC 헤더 없음** → 토큰 + 디바이스 헤더 재현만으로 호출 가능.

## 엔드포인트

| 용도 | 경로 |
|---|---|
| **중고거래 전용 검색** | `POST https://search-bff.kr.karrotmarket.com/api/v5/fleamarket/search` |
| 통합 검색(미리보기 4건) | `POST /api/v5/integrate/search` |
| 검색어 전처리 | `GET /api/v1/preprocess/search?query=` |
| 자동완성 | `GET /api/v1/autocomplete` |
| 지역 피드 | `GET https://webapp.kr.karrotmarket.com/api/v24/flea_markets.json?region_id=` |

## 요청 본문 (중고거래 검색)

```json
{
  "query": "샤넬",
  "pageToken": "<이전 응답의 nextToken, 1페이지는 생략>",
  "fleaMarket": {
    "filter": {
      "withoutCompleted": true,
      "spatialContext": { "region": {"regionId": "6128"},
        "userCoordinates": [{"type": "USER_COORDINATE_TYPE_REGION_CENTER_COORDINATE",
                             "coordinate": {"latitude": 37.498, "longitude": 127.026}}] }
    }
  },
  "spatialContext": { "region": {"regionId": "6128"},
    "userCoordinates": [{"type": "USER_COORDINATE_TYPE_REGION_CENTER_COORDINATE",
                         "coordinate": {"latitude": 37.498, "longitude": 127.026}}] }
}
```

- `spatialContext` 를 **두 군데** 넣어야 한다(루트 + fleaMarket.filter). 하나라도 빠지면 422.
- `regionId` 는 **웹 `in=서초동-6128` 의 숫자와 동일**. OUT.json 동 ID 그대로 재사용 가능.
- 페이징 파라미터는 **`pageToken`**. `nextToken`·`cursor` 등으로 보내면 무시되고 1페이지가 재반환된다(조용한 중복).
- **`fleaMarket.sortOption` — 정렬(2026-09-01 추가 발견).** 캡처 당시 본문에 없어서
  한동안 "정렬 파라미터가 없다"고 알고 있었는데, 서버 스키마에는 있다. 자리는
  `fleaMarket` **바로 아래**다 — 루트나 `fleaMarket.filter` 에 넣으면 서버가
  조용히 무시하고 200 을 준다(422 는 올바른 자리에서만 난다).

  | 값 (`FLEA_MARKET_SORT_OPTION_` 접두) | 뜻 |
  |---|---|
  | `RELEVANT` | 관련도 — **생략 시 기본값** |
  | `RECENT` | 최신순 |
  | `PRICE_ASC` / `PRICE_DESC` | 가격 |
  | `DISTANCE_ASC` | 거리 |
  | `UNSPECIFIED` | — |

  실측(역삼동·샤넬):
  - `RECENT` 는 **`publishedAt`(끌올 시각) 기준 단조 내림차순**이다. 15페이지
    300건에 위반 0건. `createdAt` 기준이 아니다(54% = 무관).
  - 최근 1시간 **신규**(createdAt) 재현율: RECENT 1페이지 33% / 2페이지 67% /
    3페이지 93%. 기본 RELEVANT 는 1페이지 15%, 10페이지 77%.
  - 한 페이지(20건)가 덮는 시간은 지역과 무관하게 **20~25분**(역삼동 23 · 해운대
    우동 22 · 제주 노형동 25). 반경검색이 택배·광역 매물을 함께 물어오기 때문에
    한산한 지역이라고 싸지 않다.

  단조라는 게 재현율보다 중요하다 — **"지난 방문 시각보다 오래된 항목이 나오면
  멈춘다"** 는 정지 규칙이 성립하고, 그러면 커버리지가 확률적 표본이 아니라
  보장이 된다. 60페이지 상한 같은 임의의 깊이를 정할 필요가 없어진다.
- `userCoordinates[].type` 허용값:
  `UNSPECIFIED` / `REALTIME_COORDINATE` / `ESTIMATED_COORDINATE` / `LAST_CHECKIN_COORDINATE` /
  `REGION_CENTER_COORDINATE` / `LOCAL_MAP_USER_COORDINATE` / `HOME_ESTIMATED_COORDINATE`
  (전부 `USER_COORDINATE_TYPE_` 접두)

> 스키마를 모를 때는 아무 값이나 보내면 서버가 422 로 **필요한 필드명과 허용 enum 을 그대로 알려준다.**

## 필수 헤더

`authorization`(Bearer JWT) · `x-device-identity` · `x-user-agent` · `x-ad-id` ·
`x-karrot-session-id` · `x-country-code: KR` · `x-search-tab: fleamarket` ·
`origin`/`referer: https://search.kr.karrotwebview.com` · iOS `user-agent`

실값은 `data/config.json`(권한 0600, gitignore). 커밋 금지.

## 응답

```
{ "results": [{"type":"FLEA_MARKET_LIST_VIEW","document":{...}}],
  "hasNextPage": true, "nextToken": "v2:...", "refinementGroups": [...] }
```

`document` 필드: `id` `title` `categoryId` `regionName` `watchesCount`(찜)
`chatRoomsCount` `republishCount` `bidsCount` `createdAt` `publishedAt` `firstImage.url`(1440px) `badges`

## 웹 대비 실측 (서초동-6128)

| | 웹 SSR | 앱 API |
|---|---|---|
| `샤넬` | **0건** (확률적 억제) | **1,198건+** |
| `샤넬가방` | 265건 | 1,198건+ |
| 페이지네이션 | 없음 (~285건 상한) | **있음** (`pageToken`) |
| 지역 범위 | 동 1개 고정 | 반경 기반 — 인접 동 자동 포함 |
| 수집 시간 | — | 60페이지 27초 |

'샤넬' 1,198건 지역 분포: 압구정동 93 · 청담동 74 · 신사동 57 · 역삼동 56 · 삼성동 51 · 논현동 50 · 대치동 49 · 서초동 40 …

## 남은 과제

- **액세스 토큰 TTL 30분** (07:53 발급 → 08:23 만료). 갱신 플로우는 아직 미캡처.
  JWT payload 에 `refresh_token_id` 존재 → 갱신 엔드포인트가 따로 있음.
  프록시 켠 채로 30분 두면 앱이 스스로 갱신하며 요청이 잡힌다.
- 60페이지 상한은 이쪽에서 건 것. 실제 총건수 미확인 — 다만 최신순 + 정지 규칙을
  쓰면 총건수를 알 필요가 없다(위 `sortOption` 항목).
- **레이트리밋(2026-09-01 실측):** 토큰 1개·IP 1개로 동시성 1→8 까지 올려도
  429/403 없음. 8동시에서 **13.1 req/s**, 평균 응답 0.50s 로 평탄(스로틀 흔적
  없음). 클라 운영 계정이라 상한까지 밀지 않고 멈췄으므로 "최소 13"이다.
  스윕 수렴 조건은 `지역수 x 조건수 = 페이지폭(23분=1380초) x 초당요청수` —
  13 req/s 면 약 **17,900**. 서울 전체 806동 x 브랜드 20 = 16,120 으로 들어오고,
  동 6537개 전수(x20 = 130,740)는 8배 초과라 발산한다.
- 계정 제재 리스크: 토큰 = 계정. 프록시 로테이션만으로는 안 가려진다.

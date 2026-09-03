# 웹 동 피드 발굴 + 계정 역할 분리 + 공개 페이지 추적 — 설계

날짜: 2026-09-03 · 상태: 승인된 설계 (구현 플랜 작성 전)

## 1. 배경과 목표

클라 요구: 브랜드 10~20개 · 조건 400줄 · 최대한 실시간 · 계정 차단 없이.
클라 정보: 키워드 검색을 반복하는 스윕은 요즘 계정이 차단된다. 웹 검색은 데이터를 잘 안 준다.

오늘(2026-09-03) 실측으로 확정된 사실:

| 항목 | 결과 |
|---|---|
| 앱 검색 API 키워드 없이 | 불가 — `query` 필수, 빈 값 400, 공백은 0건 |
| 앱 검색 응답 | `content` 없음 → 현 스윕은 사실상 **제목만** 매칭 |
| 앱 검색 지역성 | 절반이 타지역 택배 매물(역삼 조회에 전주·울산) |
| 웹 동 피드 `GET www.daangn.com/kr/buy-sell/?in=<동>-<id>&category_id=<c>&_data=routes%2Fkr.buy-sell._index` | JSON, 최신 ~275건, **본문·가격·상태·boostedAt 포함**, 계정·토큰 불필요 |
| 피드 시간 창(여성잡화 31) | 역삼동 12h(최다 동), 보통 동 60~145h |
| 구·시 id 요청 | 동 하나로 떨어짐 → 동 단위만 유효 |
| OUT.json 의 동 id | 웹에서 그대로 통함(4/4) |
| 직결 연타 10회 · KR 프록시 경유 | 전부 200 |
| 상세 `webapp…/api/v24/articles/{id}` 토큰 없이 | 401 |
| 공개 웹 상세 `www.daangn.com/kr/buy-sell/-{id}/` | 200, ld+json 에 가격·상태(Ongoing/Reserved/Closed)·본문 |

목표:
1. 발굴 주경로를 **계정 없는 웹 동 피드**로 옮긴다 — 계정 차단 대상이 사라지고, 본문까지 본다.
2. 앱 알림(본계정)은 그대로 둔다. 앱 키워드 스윕은 선택 보완층으로 축소한다.
3. 계정에 역할을 둬 알림 계정이 검색에 쓰이지 않게 한다.
4. 추적을 공개 웹 상세로 옮겨 계정 의존을 없앤다.

비목표: 100계정 JIT 순환, 전국 실시간 앱 알림, 텔레그램 방 분리(별도 과제).

## 2. 전체 구조

```
[발굴 A] 웹 동 피드 (계정 0)        [발굴 B] 앱 알림 (본계정)      [발굴 C·선택] 앱 키워드 스윕 (버릴 계정)
  동×카테고리 JSON, 본문 포함          당근 서버 푸시, 제목만            브랜드×지역 1~2, 제목만, 기본 꺼짐
        │                                  │                                │
        └───────────────► 조건표 매칭 (RuleTable.verdict, 400줄) ◄──────────┘
                                  │ HIT → 알림 · WATCH → 추적만
                                  ▼
                       watch DB (단일 진실, 중복 제거)
                                  │
                       [추적] 공개 웹 상세 파싱 (계정 0) → 가격 인하·판매·삭제·끌올 이벤트
```

## 3. 발굴 A — 웹 동 피드

### 3.1 소스
- URL: `https://www.daangn.com/kr/buy-sell/?in={quote(name)}-{id}&category_id={c}&_data=routes%2Fkr.buy-sell._index`
- 응답: `allPage.fleamarketArticles[]` — `id`(슬러그 경로), `href`, `title`, `content`, `price`, `status`, `boostedAt`, `createdAt`, `category`, `region{name}`, `thumbnail`. 정렬은 boostedAt 내림차순(거의 단조 — 정렬을 믿지 않고 워터마크는 max 로 잡는다).
- 폴백: 로더 경로가 바뀌어 JSON 이 아니면 같은 URL 의 HTML 을 받아 `<script type="application/ld+json">` ItemList(`name`·`description`·`offers.price`·`url`) 를 파싱한다. boostedAt 이 없으므로 폴백 모드에서는 "본 적 없는 url" 로만 신규 판정한다.
- 헤더: `curl_cffi` `impersonate="safari_ios"`. 토큰·쿠키 없음.

### 3.2 범위
- 지역: 조건 탭 지역 트리(기존 `sweep_regions`, 기본 서울·경기 1,857동). OUT.json 의 `locations[].id` 를 그대로 쓴다. 구·시 노드는 하위 동으로 펼친다(기존 `sweep_scope_for` 재사용).
- 카테고리: 설정 탭 체크박스. 기본 **여성잡화 31 · 남성패션/잡화 14** 켬, 여성의류 5 는 선택. 설정 키 `feed_categories: [31, 14]`.
- 한 사이클 = 지역 × 카테고리 요청. 서울·경기 기본 = 3,714 요청, 전국 6,537동 = 13,074.

### 3.3 워터마크와 신규 판정
- 커서 파일 `data/feed_cursor.json`: 키 `"{region_id}:{category}"` → `{"boosted_at": ISO, "seen": [href…최근 300개]}`.
- 신규 = `boostedAt > 워터마크` 이고 href 가 seen 에 없음. 처음 방문한 (동,카테고리) 는 최근 **120분** 것만 신규로 본다(앱 스윕과 같은 규칙 — 첫 사이클에 수백 건이 쏟아지지 않게).
- 워터마크는 사이클 성공 시에만 올린다. 요청 실패(HTTP≠200·파싱 실패·0건)는 올리지 않는다.
- `status` 가 Ongoing 이 아닌 것(Reserved·Closed)은 신규로 알리지 않는다.

### 3.4 매칭과 후속
- `RuleTable.verdict(title, price, content)` — 조건표 400줄, 본문 포함. `drop_wanted` 그대로.
- HIT → 텔레그램 알림(기존 `notify.match_line`, 시간당 상한 공유) + watch DB `add_from_matches(source="feed")`.
- WATCH(상한 초과) → 알림 없이 watch DB 에만(값이 내려오면 `entered_range` 로 알림 — 기존 `mark_range_entries` 흐름).
- CUT → 버림. seen 에도 안 남긴다(값이 내려와 조건 안에 들어오면 그때 처음 알린다 — 앱 스윕과 동일).
- 중복: watch DB 의 url(href) 기준. 앱 알림·앱 스윕과 같은 매물이면 한 번만 알린다(`already_notified`).

### 3.5 속도·프록시·부하
- 프록시 풀: 웹 전용 `feed_proxies`(설정, 없으면 `proxies.txt`). 외국 데이터센터 IP 가능(www.daangn.com 은 WAF 지문 차단 없음 — 실측). 계정 프록시(KR ISP)와는 **섞지 않는다** — 계정 IP 가 검색 부하에 노출되면 안 된다.
- 레인 = 프록시 수(직결이면 1). 레인당 **1 req/s 고정**(설정 `feed_rps`, 기본 1.0). 프록시 5개 → 서울·경기 사이클 ≈ 12~15분, 전국 ≈ 45~55분.
- 사이클 간 휴식 `feed_rest_min`(기본 2분). 사이클이 목표(15분)보다 길어지면 로그에 남기고 다음 사이클을 바로 잇는다(발산하지 않는다 — 시간 창이 최소 12h 라 밀려도 놓치지 않는다).
- 응답 ~320KB. 서울·경기 사이클당 ≈1.2GB. `Accept-Encoding: gzip` 을 요청해 실측 후 기록한다.
- IP 차단·빈응답(403/429/HTML 로그인 페이지/0건 연속 3회) → 그 프록시 30분 쿨다운, 다른 프록시로 재시도. 전 프록시 쿨다운이면 사이클 중단 + 로그.
- 상태: 기존 상태 한 줄에 `피드 N분 · 동 M/총` 을 보인다.

### 3.6 모듈
- 신규 `daangn_ext/web_feed.py` (순수 로직, PyQt 무관): `feed_url(name, id, cat)`, `parse_feed_json(j) -> list[Article]`, `parse_feed_html(html) -> list[Article]`(폴백), `FeedCursor`(로드·판정·저장), `new_articles(cursor, key, arts, now) -> list`.
- 신규 `daangn/feed_sweep.py`: `FeedSweep(cfg, on_log, on_found, on_status)` — 레인 스레드·프록시 순환·휴식·중단. `SweepEngine` 과 같은 콜백 규약(`on_found(article, rule, region)`)이라 GUI/헤드리스 배선이 같다.
- `main.py`: 감시 토글이 `FeedSweep` 을 함께 켜고 끈다. 설정 탭에 카테고리 체크·웹 프록시 칸·초당 요청. 헤드리스(`--watch`, `--headless`) 도 같은 cfg 로 띄운다.

## 4. 발굴 B — 앱 알림
변경 없음. 등록 대상 계정만 §6 의 역할 필터를 탄다.

## 5. 발굴 C — 앱 키워드 스윕 (선택)
- 용도: 서울·경기만 피드로 볼 때 타지역 택배 매물 보완. 제목만.
- 범위: 브랜드(조건표 `brands`) × 지역 **1~2곳**(설정 `sweep_regions_app`, 기본 역삼동 1곳) × 최신순 워터마크. 20브랜드면 20~40 req/사이클, 사이클 20분.
- 계정: `role: sweep` 계정만(§6). 없으면 자동 꺼짐 + 로그 한 줄.
- 설정 `sweep_app_enabled` 기본 **false**. `sweep_mirror_app` 은 이 키로 대체한다(옛 키가 있으면 읽어서 옮기고 로그).
- 기존 `SweepEngine` 을 그대로 쓴다. 지역 범위만 좁힌다.

## 6. 계정 역할
- `accounts.json` 각 계정에 `role`: `"alert"`(기본) | `"sweep"`. 없으면 alert.
- alert 계정: 폴링(`poll_all`), 브랜드 등록(`register_all`), 수확. 검색 API 를 **부르지 않는다**.
- sweep 계정: `AccountScheduler.pick()` 후보. 폴링·등록에서 제외(등록해 두면 알림함이 채워져 쓸모없이 상한 15건을 채운다).
- 필터 위치: `keyword_alert_api._valid(role="alert")`, `AccountScheduler._accounts(role="sweep")`. 수확(`ld_autoharvest`)은 역할 무관(토큰은 둘 다 필요).
- GUI 계정 다이얼로그에 역할 콤보. 서버 배포 시 기존 계정은 전부 alert 로 읽힌다(변경 없음).

## 7. 추적 — 공개 웹 상세
- `ArticleDetailAPI.fetch(article_id)` 를 공개 페이지 파서로 교체: `GET https://www.daangn.com/kr/buy-sell/-{id}/`(숫자 id) 또는 피드의 `href`(슬러그). ld+json Product 에서 `offers.price`, `offers.availability`, 본문; HTML 에서 `status`(Ongoing/Reserved/Closed)·`republish`·삭제 여부(404/`unpublished`).
- 반환 dict 는 기존 `check_one`/`diff_events` 가 읽는 키(`price`, `status`, `republish_count`, `destroyed_at`/삭제 플래그) 를 유지한다 — 이벤트 로직은 손대지 않는다.
- id: 피드 매물은 슬러그 href 를 `url` 로 저장하고 watch `id` 는 첫 상세 조회에서 얻은 숫자 id 로 채운다. 그 전까지는 href 가 키다(`seen_key` 활용).
- 주기: `FRESH_INTERVAL` 4h → **1h**(48h 이내), AGED 24h 유지, 14일 뒤 dead. 조건 맞은(HIT·WATCH) 매물만 추적한다 — 지금과 같다.
- 프록시: 피드 풀과 공유, 1 req/s. 추적 대상 수천 건이면 주기가 늘어난다 — 로그에 `추적 N건 · 한 바퀴 M분`.
- 401/토큰 의존 코드 제거. `webapp…/api/v24/articles` 경로는 남기지 않는다(뒷문 금지).

## 8. 설정 키 (alert_settings.json)
| 키 | 기본 | 뜻 |
|---|---|---|
| `feed_enabled` | true | 웹 동 피드 발굴 |
| `feed_categories` | `[31, 14]` | 카테고리 id |
| `feed_proxies` | `[]` (→ proxies.txt) | 웹 전용 프록시 |
| `feed_rps` | 1.0 | 레인(프록시)당 초당 요청 |
| `feed_rest_min` | 2 | 사이클 휴식(분) |
| `sweep_app_enabled` | false | 앱 키워드 스윕(보완층) |
| `sweep_regions_app` | `["역삼동-6035"]` | 앱 스윕 지역 |
| `sweep_mirror_app` | (삭제) | `sweep_app_enabled` 로 이관 |

## 9. 오류·안전
- 피드 파싱 실패 연속 3회(동일 동) → 그 동 건너뛰고 로그. 전체 실패율 50% 초과 사이클 → 폴백(HTML) 강제 + 로그 `[피드] 로더 경로 변경 의심`.
- 프록시 전멸 → 피드 정지, 앱 알림은 계속. 상태줄 `피드 정지 — 프록시 확인`.
- 알림 폭주 방어는 기존 시간당 상한(120) 공유. 첫 사이클 120분 규칙으로 초기 폭주 차단.
- 계정 토큰은 피드·추적 코드 어디에도 들어가지 않는다(단위 테스트로 잠근다: 요청 헤더에 `authorization` 없음).

## 10. 테스트
- `web_feed_test.py`: 저장된 로더 JSON·HTML 픽스처(오늘 캡처, 스크래치 → `tests/fixtures/`) 로 파싱, 워터마크 판정(단조 깨짐·첫 방문 120분·실패 시 미갱신), URL 인코딩, 폴백 전환.
- `feed_sweep_test.py`: 가짜 fetch 로 레인·초당 상한·프록시 쿨다운·중단, `on_found` 규약, 헤더에 토큰 없음.
- `account_role_test.py`: `_valid(role)`·`AccountScheduler._accounts(role)`·기본값 alert·GUI 콤보 저장.
- `article_watch_test.py` 확장: 공개 상세 HTML 픽스처 → price/status/삭제 파싱, 1h 주기, 이벤트 불변.
- 배선: `unified_tab_wiring_test.py` 에 설정 위젯·토글 연동·헤드리스 cfg. 기존 스위트 그린 유지(라이브 API 미호출).
- 배포 전 스모크: 서버에서 프록시 1개·1 req/s·1시간 실측 → 200 비율·평균 응답·gzip 크기 기록(§3.5 의 미측정 항목).

## 11. 롤아웃
1. 코드 배포(푸시=배포). `feed_enabled` 기본 true 지만 `feed_proxies`·`proxies.txt` 가 비면 직결 1레인으로 돈다(서울·경기 62분 사이클) — 그래도 시간 창 12h 안.
2. 클라: 웹 프록시 5~10개(외국 DC 가능) 등록, 계정 역할 지정(기본 전부 alert → 앱 스윕은 꺼진 채).
3. 1주 관찰: 피드 사이클 시간·알림 수·프록시 차단 로그. 이상 없으면 카테고리 5 추가 여부 결정.

## 12. 클라에게 달라지는 것
- 계정은 알림만 받는다(검색 안 함) → 차단 위험 사실상 0.
- 프록시 두 종류: 계정용 한국 ISP(계정 수만큼) + 발굴·추적용 아무 IP 5~10개.
- 새 매물 알림 15분 안(서울·경기), 본문까지 조건 매칭. 앱 알림은 계정 동네 근처 2분.

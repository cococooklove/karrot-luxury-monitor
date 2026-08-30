# 잔여 결함 정리 보고 (watch-followups)

작업 트리 `/.claude/worktrees/watch-followups`, 브랜치 `watch-followups`.

```
$ git log --oneline -2
50bdd69 test: 오래 빨갛던 레거시 테스트 4종 정리
d7119ff feat: 상태칩을 누르면 해당 고급 패널 항목으로 데려간다
```

전체 커밋 4개:

```
50bdd69 test: 오래 빨갛던 레거시 테스트 4종 정리
d7119ff feat: 상태칩을 누르면 해당 고급 패널 항목으로 데려간다
8ff44cf fix: article_id 없는 매치의 중복 판정을 재시작 후에도 유지
efbef37 fix: 매물 표가 묘비를 제목이 아니라 출처로 거른다
```

---

## Fix 1 — 표가 잘못된 성질로 행을 숨기던 문제 (efbef37)

`tools/backfill_listings.py` 를 먼저 확인했다. `match_seen.json` 에서 옮기는 행은
`tier=dead`, `title=""`, `source="match_seen"` 로 쓴다(`auto_seen.db` 에서 옮기는
행은 `source="sweep"` 이고 제목·가격이 있다). 즉 묘비를 유일하게 규정하는 값은
출처다.

- `daangn_ext/article_watch.py` 에 `SOURCE_MATCH_SEEN = "match_seen"` 상수 추가.
  백필과 표가 같은 값을 보게 한 곳에 둔다.
- `main.py: listing_display_rows` 의 필터를
  `tier == dead and not title` → `source == SOURCE_MATCH_SEEN` 로 교체.
- `tools/backfill_listings.py` 는 그 상수를 쓰고, 주석도 "제목이 비어서 걸러진다"
  → "출처로 걸러진다"로 고쳤다.

효과: 제목 없이 들어온 실제 매물(앱/스윕 출처)이 판매완료·삭제되어도 표에
`✓ 종료` 로 남는다. 반대로 `match_seen` 행은 제목이 채워져 있든 tier 가 무엇이든
절대 뜨지 않는다.

검증(`unified_tab_wiring_test.py`):
`제목 없는 dead 라도 출처가 있으면 보인다`, `제목 없는 dead 는 ended 필터에도
걸린다`, `match_seen 은 제목이 있어도 숨김`, `match_seen 은 살아 있어도(fresh)
숨김`, `백필이 세우는 출처가 표의 필터 기준과 같다`(백필 소스에 상수 사용 확인).

## Fix 2 — id 없는 매치의 중복 판정이 재시작을 못 넘기던 문제 (8ff44cf)

`daangn_ext/keyword_alert_api.py` 의 매치 조립에서 `neighborhoodAdvertisements`
항목은 `articleId` 가 null 일 수 있다. 그 매치의 키는 알림 인박스 `id` 이고,
`watch` 는 article id 로만 키를 잡으므로 저장소가 답할 수 없다. 지금까지는
프로세스 안 집합만 막고 있었고, 앱을 껐다 켜면 같은 항목이 다시 알림으로 나갔다.

**설계 선택: `watch.db` 안의 별도 테이블 `seen_key`.**

- `watch` 행으로 넣지 않은 이유 — `watch` 행은 "추적 대상 매물"이라는 뜻이고,
  `listing_rows()`(표)와 `add_from_matches`(재등록)가 실제로 그렇게 다룬다. 인박스
  id 는 매물이 아니다. 넣으면 표에 뜨거나 조회 대상이 되거나, 그걸 막으려고 또
  하나의 "이건 진짜 매물이 아님" 예외를 표 코드에 심어야 한다(Fix 1 이 지운 바로
  그 종류의 예외다).
- 별도 **파일**을 만들지 않은 이유 — `match_seen.json` 을 이름만 바꿔 되살리는
  셈이다. 같은 DB 안에 두면 워치 저장소를 여는 순간 함께 열리고, 백업·삭제 단위가
  하나로 유지된다. 스키마는 `CREATE TABLE IF NOT EXISTS` 라 기존 DB 도 열 때
  자동으로 생긴다(별도 마이그레이션 불필요).
- 상한 — 옛 파일과 같은 5000(`SEEN_KEY_CAP`). 새 키가 실제로 들어갈 때만
  초과분을 `seen_at` 오름차순으로 지운다. 무한 성장이 그 파일을 접은 이유였다.
- 판정과 기록을 `INSERT OR IGNORE` 한 번으로 합쳐(`seen_key_add` 가 "처음 봤다"를
  반환) 같은 폴링 배치에 같은 키가 두 번 있어도 한 번만 신규가 된다.

`dedupe_new_matches` 는 저장소에 `seen_key_add` 가 있으면 그것을 쓰고, 없으면(=
저장소를 아예 못 연 경우) 기존 프로세스 집합으로 떨어진다. GUI(`_match_populate`)와
헤드리스가 같은 함수를 쓰므로 두 런타임 모두 자동으로 영속화된다 — 호출부는
바뀌지 않았고, 헤드리스의 `fallback_seen = set()` 은 마지막 방어선으로 남는다.

검증:
- `article_watch_test.py` — 처음/중복/다른 키, `has`, 빈 키, **`watch` 행이 아님**
  (`get()` None, `listing_rows()` 빈 배열, `due()`·`active_count()` 0), 재시작 후
  기억, 상한 초과 시 오래된 것부터 축출, 축출된 키는 다시 신규, 기본 상한 5000.
- `unified_tab_wiring_test.py` — 실제 `WatchStore` 로 첫 회 신규 → 저장소 닫고 다시
  열어(재시작) 재알림 없음, 같은 회차 중복 1건 처리, 프로세스 집합은 안 쓴다,
  키가 매물 표에 안 뜬다, `add_from_matches` 가 키를 추적 대상으로 오인하지 않는다.

## Fix 3 — 상태칩이 아무 일도 안 하던 문제 (d7119ff)

`_build_alert_tab` 을 먼저 읽었다. 실제 컨트롤 바에는 토글과 `_watch_label` 만
있었고, 토큰·계정·커버리지 값은 그 아래 "현황" 그룹의 읽기 전용 라벨
(`dashHealth`/`dashAccounts`/`dashBar`)에만 있었다 — 스펙의 칩 줄은 위젯으로
존재하지 않았다. 그래서 컨트롤 바에 진짜 칩(QPushButton, `objectName=statChip`)
줄을 만들고 `_refresh_alert_health` 가 5초마다 문구·색(정상/경고/실패/꺼짐)을
채우게 했다. 값의 출처는 기존 헬스 계산 그대로라 표시가 갈라지지 않는다.

탭은 `_scroll()` 로 `QScrollArea` 에 감싸여 있으므로, 목적지 위젯에서 부모를 거슬러
올라가 감싸는 `QScrollArea` 를 찾아 `ensureWidgetVisible` 한다. 접힌 고급 패널은
먼저 펴고(`advancedBox.setChecked(True)` → `_sync_advanced_visible`), **부모 레이아웃을
`activate()` 해서 좌표를 확정한 뒤** 스크롤한다(펴자마자 스크롤하면 옛 자리로
간다). 레이아웃이 늦게 잡히는 경우를 위해 `singleShot(0)` 으로 한 번 더 부른다.
목적지에 포커스도 준다.

| 칩 | 목적지 | 비고 |
|---|---|---|
| 토큰 | `alertFleetBtn` (계정 현황) | 계정별 토큰 만료를 보는 곳 |
| 계정 | `alertFleetBtn` (계정 현황) | 같은 팜 현황 다이얼로그 |
| 커버리지 | `alertCoverMode` (전국/핵심 커버 모드) | 커버리지를 실제로 바꾸는 설정 |
| 다음폴링 | `alertPollInterval` (폴링 주기) | |
| 추적중 | **없음 — 그대로 라벨** | 고급 패널에 대응 항목이 없다 |

추적중(`_watch_label`)만 목적지가 없다. 워치 스윕 주기는 `WATCH_SWEEP_INTERVAL`
정책 상수라 사용자가 만질 항목이 고급 패널에 없고, 스윕 설정 상자는 *검색* 스윕
설정이라 가격추적과 다른 것이다. 지시대로 목적지를 지어내지 않고 라벨로 두었다.
(설계 판단이며 브리프가 허용한 "목적지 없으면 그대로 둔다"에 해당한다.)

검증(`unified_tab_wiring_test.py`): 칩 4종 존재, 목적지 위젯 실재, 목적지가 전부
고급 패널 자식, 탭이 스크롤 영역 안, 접힌 패널이 펴짐, 각 칩이 자기 목적지로
포커스를 옮김, 목적지가 실제로 보임, 목적지 없는 키는 `False` 반환(무시),
헬스 갱신이 칩 문구를 채움.

## Fix 4 — 오래 빨갛던 레거시 테스트 4종 (50bdd69)

| 파일 | 처리 | 이유 |
|---|---|---|
| `_construct_test.py` | **수리** | 창 조립 스모크는 값싼 회귀 그물이라 남길 값이 있다. 탭 2 → 3(수동 검색/매물 감시/에뮬레이터)로 고치고, 없어진 자동 모니터 탭 위젯(`autoCondLabel`·`auto_conditions`) 단언은 **없어야 한다**는 단언으로 뒤집었다(스윕 설정은 고급 패널로 이사했으므로 `autoExcelBtn`·`autoAreaTree`·`autoRestMin` 존재를 본다). AutoMonitor 다중조건+프록시 cfg 구성과 `_proxy_cycle` 은 그대로 유지, 프록시 없을 때 `None` 케이스를 추가. `R`/`ck`/`===== n/n PASS =====`/`sys.exit` 관례와 `QT_QPA_PLATFORM=offscreen`·chdir 로 정비. 9건. |
| `button_test.py` | **수리(범위 축소)** | 옛 버전은 [검색]을 눌러 진짜 당근에서 수집하고 자동 모니터를 30초 돌렸다 — 자격증명·프록시 없는 환경에서 영원히 빨갛고, 있어도 네트워크에 흔들린다. 없어진 `adaptiveCheck`·`on_auto_start_clicked` 도 참조했다. 네트워크 없이 확인 가능한 것만 남겼다: 버튼 17개+검색 버튼+상태칩 4개가 실제로 핸들러에 연결됐는지(`receivers()`), 다이얼로그 4종(계정·프록시/프록시 목록/알림 설정/계정 현황)이 자격증명 없이도 크래시 없이 서는지(모달 `exec`·비모달 `show` 둘 다 포착), 엑셀 조건 취소 경로, 검색폼→`CrawlTask` 필드 전달, 지역 트리 채워짐. 30건. |
| `full_test.py` | **수리(범위 축소)** | 없어진 `TokenManager.ensure_safe` 를 부르고 있었고(게다가 옛 단언은 `... is not None or True` 라 항상 참인 무의미한 검사였다), B 구간은 실제 당근 API 를 때렸다. 지금은 다른 스위트가 안 건드리는 것만 본다: 토큰 매니저(만료 임박 갱신/살아 있으면 무갱신/`ensure_safe` 부재 확인/갱신 실패의 계정별 격리 = `refresh_all` 이 진짜 graceful 경로), 검색 필터, 계정·프록시 저장소(영속), 토큰 주입 호스트 판정, 휴식 범위, 창 조립(탭 3). C 구간(자동 모니터 엔진)은 `sweep_engine_test.py` 가 엔진을 직접 검증하므로 넘겼다. 17건. |
| `gui_func_test.py` | **삭제** | `proxies.txt` 의 프록시 20개와 실제 당근 수집, 30초 자동 모니터 e2e 를 요구하는 `button_test` 의 라이브 쌍둥이다(게다가 없어진 `autoProxyViewBtn` 기대·`on_auto_start_clicked` 참조). 네트워크 없이 검증 가능한 부분(핸들러 배선, 검색폼→`CrawlTask`)은 `button_test.py` 로 옮겼으므로 남는 고유 커버리지가 없다. |

---

## 검증

`delivery/integrated/manual_gui/` 에서 `QT_QPA_PLATFORM=offscreen` 으로 실행.
아래는 각 스위트 출력의 실제 마지막 줄이다(커밋 후 재실행).

```
### article_watch_test.py
===== 191/191 PASS =====        (기준 177 → seen_key·출처 상수 14건 추가)
### watch_listing_test.py
===== 47/47 PASS =====
### article_watch_wiring_test.py
===== 27/27 PASS =====
### unified_tab_wiring_test.py
===== 148/148 PASS =====        (기준 123 → 출처 필터·영속 중복판정·칩 25건 추가)
### keyword_router_test.py
===== 104/104 PASS =====
### sweep_queue_test.py
===== 29/29 PASS =====
### supervisor_test.py
===== 20/20 PASS =====
### backfill_test.py
===== 26/26 PASS =====
### sweep_engine_test.py
===== 57/57 PASS =====
### headless_sweep_test.py
===== 101/101 PASS =====
### notify_test.py
54/54 PASS
### robust_test.py
29/29 PASS
### _construct_test.py
===== 9/9 PASS =====            (수리 — 전에는 AssertionError)
### button_test.py
===== 30/30 PASS =====          (수리 — 전에는 AttributeError/라이브 실패)
### full_test.py
===== 17/17 PASS =====          (수리 — 전에는 ensure_safe AttributeError)
```

헤드리스 스모크:

```
$ QT_QPA_PLATFORM=offscreen python main.py --headless --once --no-harvest
[12:41:13] === 헤드리스 무인 모니터 시작 ===
[12:41:13] 전계정(0) 매칭 0건(중복제거)
[12:41:13] [매칭] 신규 0 (유효계정 0, 커버 전국)
[12:41:13] --once 완료
(exit 0)
```

## 남은 문제(이번 범위 밖, 손대지 않음)

- `e2e_chain_test.py` — `refresh 토큰도 회전 반영` 1건 실패. 이번 작업 전부터
  빨갛고 브리프의 4종에 없어 그대로 두었다.
- `proxy_test.py` — `proxies.txt` 없음으로 `FileNotFoundError`. 자격증명·프록시
  파일이 gitignore 라 이 환경에서는 실행 불가.

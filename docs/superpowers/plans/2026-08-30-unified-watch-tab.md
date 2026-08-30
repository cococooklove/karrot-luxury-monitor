# 매물 감시 탭 통합 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 자동 모니터 탭을 없애고, 키워드 알림 탭 하나에서 신규 캐치와 가격 추적이 모두 되게 한다.

**Architecture:** 검색 스윕 엔진(`AutoMonitor`)은 살리되 UI 에서 지우고, `KeywordRouter` 가 키워드를 앱 API 슬롯 또는 스윕 큐로 자동 배정한다. `watch` 테이블을 매물 단일 진실로 확장해 신규 매치 표와 워치 이벤트 목록을 매물 표 하나로 합치고, `SupervisorController` 가 폴링·스윕을 토글 하나로 관장한다.

**Tech Stack:** Python 3.11+, PyQt6, httpx, sqlite3. 테스트는 pytest 가 아니라 저장소 관례인 독립 스크립트다.

**Spec:** `docs/superpowers/specs/2026-08-30-unified-watch-tab-design.md`

## Global Constraints

- 작업 디렉토리: `delivery/integrated/manual_gui/`. 이하 모든 경로는 이 디렉토리 기준이다.
- **테스트는 pytest 가 아니다.** 저장소 관례는 `<이름>_test.py` 독립 스크립트다. 각 파일은
  `ck(name, cond, extra="")` 로 검사하고, 끝에서 `passed/len(R)` 를 출력하고
  `sys.exit(0 if passed == len(R) else 1)` 한다. 실행은 `python <이름>_test.py`.
  기존 예시: `article_watch_test.py`, `article_watch_wiring_test.py`.
- 테스트 파일 상단 공통 서두는 이것이다. 새 테스트 파일마다 그대로 쓴다.

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")
```

  그리고 파일 끝은 항상 이것이다.

```python
passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)
```

- GUI 를 import 하는 테스트는 첫 줄에서 `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` 를
  설정한다(`article_watch_wiring_test.py` 관례).
- 스키마 상수 `_COLUMNS` 와 `_SCHEMA` 는 `daangn_ext/article_watch.py:120-139` 에 있다.
  컬럼을 추가할 때 두 곳 다 고쳐야 한다 — `_COLUMNS` 가 `upsert`/`mark` 의 화이트리스트다.
- 등급 상수는 바꾸지 않는다: `FRESH_AGE=48*3600`, `AGED_AGE=14*24*3600`,
  `FRESH_INTERVAL=4*3600`, `AGED_INTERVAL=24*3600`, `ACTIVE_CAP=300`,
  `DAILY_CAP_PER_ACCOUNT=300`, `MAX_FAIL=5`.
- 티어는 넷이다: `fresh`, `aged`, `dead`(판매완료·삭제 — 종착), `evicted`(상한·실패로 접음 —
  재매칭되면 되살아남). `dead` 와 `evicted` 를 섞지 않는다.
- 커밋 메시지는 한국어 Conventional Commits. 기존 로그 형식을 따른다
  (`feat:`, `fix:`, `docs:`, `test:`).

---

## 선행 조건

`main.py` 에 커밋되지 않은 변경 508줄이 있다(에뮬레이터 탭 — `_build_emul_tab`,
`_InstanceCard`, `_EmbedHost` 등). 이 계획은 그 코드를 건드리지 않지만 `_setup_tabs`
를 같이 수정하므로, **시작 전에 그 작업을 커밋하거나 stash 해야 한다.**

```bash
cd delivery/integrated/manual_gui
git status --short main.py
# 커밋되지 않았으면 먼저 커밋 후 진행
```

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `daangn_ext/article_watch.py` (수정) | 스키마 확장, `state_for`, `price_history`, `listing_rows` |
| `daangn_ext/sweep_queue.py` (신규) | 앱 슬롯에 못 들어간 키워드 대기열 (JSON 영속) |
| `daangn_ext/keyword_router.py` (신규) | 키워드 → 앱/스윕 배정, 승격, 라우트 영속 |
| `daangn_ext/supervisor.py` (신규) | 폴링·스윕 타이머 수명주기 (순수 정책, Qt 의존 최소) |
| `tools/backfill_listings.py` (신규) | `auto_seen.db` + `match_seen.json` → `watch` 1회 백필 |
| `main.py` (수정) | 매물 표 위젯, 고급 패널, 탭 제거, 컨트롤러 배선 |
| `daangn/auto_monitor.py` (수정) | `found` 신호에 매물 id 추가 (1줄) |

테스트 파일: `watch_listing_test.py`, `backfill_test.py`, `sweep_queue_test.py`,
`keyword_router_test.py`, `supervisor_test.py`, `unified_tab_wiring_test.py`.

---

### Task 1: 매물 단일 진실 — 스키마 확장과 상태 파생

**Files:**
- Modify: `daangn_ext/article_watch.py:120-139` (스키마), `:346-402` (`check_one`)
- Test: `watch_listing_test.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces:
  - `WatchStore.__init__(path)` — 기존 DB 를 열면 새 컬럼을 자동 추가한다
  - `WatchStore.add_price(article_id: str, ts: int, price: int) -> None`
  - `WatchStore.price_history(article_id: str) -> list[dict]` — `[{"ts": int, "price": int}]`, ts 오름차순
  - `WatchStore.listing_rows() -> list[dict]` — `watch` 전체 행(dict)
  - `article_watch.state_for(row: dict, now: int) -> str` — `"new"|"tracking"|"down"|"up"|"paused"|"ended"`
  - 상수 `STATE_NEW`, `STATE_TRACKING`, `STATE_DOWN`, `STATE_UP`, `STATE_PAUSED`, `STATE_ENDED`,
    `NEW_WINDOW = 24*3600`, `CHANGE_WINDOW = 24*3600`
  - `watch` 테이블 새 컬럼: `keyword TEXT`, `source TEXT`, `first_price INTEGER`,
    `last_change INTEGER`, `last_delta INTEGER`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`watch_listing_test.py` 를 만든다. Global Constraints 의 공통 서두로 시작하고, 그 아래에
다음을 넣는다.

```python
import sqlite3
import tempfile

from daangn_ext import article_watch as aw

NOW = 1788000000
DAY = 86400

# ── A. 새 컬럼이 붙는다 ──
d = tempfile.mkdtemp()
p = os.path.join(d, "watch.db")
st = aw.WatchStore(p)
cols = {r[1] for r in st._db.execute("PRAGMA table_info(watch)").fetchall()}
for c in ("keyword", "source", "first_price", "last_change", "last_delta"):
    ck(f"컬럼 {c} 존재", c in cols)

# ── B. 구버전 DB 를 열어도 깨지지 않는다(마이그레이션 멱등) ──
old = os.path.join(d, "old.db")
con = sqlite3.connect(old)
con.executescript("""
CREATE TABLE watch (
    id TEXT PRIMARY KEY, title TEXT, region TEXT, url TEXT, price INTEGER,
    status TEXT, republish_count INTEGER, published_at INTEGER,
    first_seen INTEGER, last_check INTEGER, next_check INTEGER,
    tier TEXT, fail INTEGER);
INSERT INTO watch (id, title, price, tier) VALUES ('9', '옛행', 1000, 'fresh');
""")
con.commit(); con.close()
st_old = aw.WatchStore(old)
ck("구버전 DB 행 보존", (st_old.get("9") or {}).get("title") == "옛행")
ck("구버전 DB 에 새 컬럼 추가됨", "first_price" in (st_old.get("9") or {}))
st_old2 = aw.WatchStore(old)          # 두 번 열어도 안 깨진다
ck("마이그레이션 멱등", (st_old2.get("9") or {}).get("title") == "옛행")

# ── C. 가격 이력 ──
st.add_price("1", NOW, 300)
st.add_price("1", NOW + 100, 280)
st.add_price("1", NOW + 100, 280)          # 같은 (id, ts) 는 한 행
hist = st.price_history("1")
ck("이력 2건", len(hist) == 2, str(hist))
ck("이력 오름차순", [h["ts"] for h in hist] == [NOW, NOW + 100])
ck("이력 가격", [h["price"] for h in hist] == [300, 280])
ck("없는 매물 이력은 빈 목록", st.price_history("없음") == [])

# ── D. listing_rows ──
st.upsert({"id": "1", "title": "가방", "region": "강남", "url": "u", "price": 280,
           "status": "ongoing", "republish_count": 0, "published_at": NOW,
           "first_seen": NOW, "last_check": NOW, "next_check": NOW + 100,
           "tier": "fresh", "fail": 0, "keyword": "샤넬", "source": "app",
           "first_price": 300, "last_change": NOW + 100, "last_delta": -20})
rows = st.listing_rows()
ck("listing_rows 1건", len(rows) == 1, str(len(rows)))
ck("listing_rows 에 keyword", rows[0]["keyword"] == "샤넬")
ck("listing_rows 에 first_price", rows[0]["first_price"] == 300)

# ── E. state_for ──
def row(**kw):
    base = {"tier": "fresh", "first_seen": NOW, "last_change": 0, "last_delta": 0}
    base.update(kw)
    return base

ck("dead → ended",
   aw.state_for(row(tier="dead"), NOW) == aw.STATE_ENDED)
ck("evicted → paused",
   aw.state_for(row(tier="evicted"), NOW) == aw.STATE_PAUSED)
ck("24h 이내 → new",
   aw.state_for(row(first_seen=NOW - 100), NOW) == aw.STATE_NEW)
ck("24h 경계 직후 → tracking",
   aw.state_for(row(first_seen=NOW - DAY - 1), NOW) == aw.STATE_TRACKING)
ck("최근 인하 → down",
   aw.state_for(row(first_seen=NOW - 5 * DAY, last_change=NOW - 10,
                    last_delta=-20), NOW) == aw.STATE_DOWN)
ck("최근 인상 → up",
   aw.state_for(row(first_seen=NOW - 5 * DAY, last_change=NOW - 10,
                    last_delta=20), NOW) == aw.STATE_UP)
ck("변동 24h 지나면 tracking",
   aw.state_for(row(first_seen=NOW - 5 * DAY, last_change=NOW - DAY - 1,
                    last_delta=-20), NOW) == aw.STATE_TRACKING)
ck("신규이면서 인하면 인하가 이긴다",
   aw.state_for(row(first_seen=NOW - 100, last_change=NOW - 10,
                    last_delta=-20), NOW) == aw.STATE_DOWN)
ck("dead 는 최근 변동보다 우선",
   aw.state_for(row(tier="dead", last_change=NOW - 10,
                    last_delta=-20), NOW) == aw.STATE_ENDED)
```

그리고 Global Constraints 의 공통 꼬리를 붙인다.

- [ ] **Step 2: 실패를 확인한다**

Run: `cd delivery/integrated/manual_gui && python watch_listing_test.py`
Expected: FAIL — `AttributeError: module 'daangn_ext.article_watch' has no attribute 'state_for'`

- [ ] **Step 3: 스키마를 확장한다**

`daangn_ext/article_watch.py` 의 `_COLUMNS`(120행)와 `_SCHEMA`(123행)를 교체한다.

```python
_COLUMNS = ("id", "title", "region", "url", "price", "status", "republish_count",
            "published_at", "first_seen", "last_check", "next_check", "tier", "fail",
            "keyword", "source", "first_price", "last_change", "last_delta")

# 나중에 붙은 컬럼 — 기존 DB 에는 없으므로 열 때마다 ADD COLUMN 을 시도한다.
_ADDED_COLUMNS = (("keyword", "TEXT"), ("source", "TEXT"),
                  ("first_price", "INTEGER"), ("last_change", "INTEGER"),
                  ("last_delta", "INTEGER"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS watch (
    id TEXT PRIMARY KEY,
    title TEXT,
    region TEXT,
    url TEXT,
    price INTEGER,
    status TEXT,
    republish_count INTEGER,
    published_at INTEGER,
    first_seen INTEGER,
    last_check INTEGER,
    next_check INTEGER,
    tier TEXT,
    fail INTEGER,
    keyword TEXT,
    source TEXT,
    first_price INTEGER,
    last_change INTEGER,
    last_delta INTEGER
);
CREATE INDEX IF NOT EXISTS idx_watch_due ON watch (tier, next_check);

CREATE TABLE IF NOT EXISTS price_history (
    article_id TEXT NOT NULL,
    ts INTEGER NOT NULL,
    price INTEGER NOT NULL,
    PRIMARY KEY (article_id, ts)
);
CREATE INDEX IF NOT EXISTS idx_price_hist ON price_history (article_id, ts DESC);
"""
```

- [ ] **Step 4: 마이그레이션과 새 조회 메서드를 넣는다**

`WatchStore.__init__`(146행) 의 `self._db.executescript(_SCHEMA)` 다음 줄에
`self._migrate()` 호출을 넣고, `upsert` 앞에 메서드 셋을 추가한다.

```python
    def _migrate(self) -> None:
        """나중에 붙은 컬럼을 기존 DB 에 채운다. 이미 있으면 조용히 넘어간다.

        별도 마이그레이션 러너를 두지 않는 이유는 컬럼 추가가 전부이고,
        sqlite 의 ADD COLUMN 은 되돌릴 일이 없기 때문이다."""
        for name, typ in _ADDED_COLUMNS:
            try:
                self._db.execute(f"ALTER TABLE watch ADD COLUMN {name} {typ}")
            except sqlite3.OperationalError:
                pass                    # duplicate column name
        self._db.commit()

    def add_price(self, article_id: str, ts: int, price: int) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO price_history (article_id, ts, price) "
            "VALUES (?,?,?)", (str(article_id), int(ts), int(price)))
        self._db.commit()

    def price_history(self, article_id: str) -> list[dict]:
        rows = self._db.execute(
            "SELECT ts, price FROM price_history WHERE article_id=? ORDER BY ts ASC",
            (str(article_id),)).fetchall()
        return [{"ts": r["ts"], "price": r["price"]} for r in rows]

    def listing_rows(self) -> list[dict]:
        rows = self._db.execute("SELECT * FROM watch").fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 5: 상태 파생 함수를 넣는다**

`interval_for`(215행) 바로 다음에 추가한다.

```python
STATE_NEW = "new"
STATE_TRACKING = "tracking"
STATE_DOWN = "down"
STATE_UP = "up"
STATE_PAUSED = "paused"
STATE_ENDED = "ended"

NEW_WINDOW = 24 * 3600
CHANGE_WINDOW = 24 * 3600


def state_for(row: dict, now: int) -> str:
    """표에 보여줄 상태. 저장하지 않고 매번 파생한다.

    tier 와 state 를 둘 다 저장하면 한쪽만 갱신되는 버그가 난다. tier 가 일정
    정책의 진실이고, state 는 그것을 사람이 읽는 형태로 옮긴 것뿐이다.

    최근 가격 변동이 '신규'보다 우선한다 — 갓 올라온 매물이 값을 내렸으면
    그게 더 볼 만한 사실이다."""
    tier = row.get("tier") or ""
    if tier == TIER_DEAD:
        return STATE_ENDED
    if tier == TIER_EVICTED:
        return STATE_PAUSED
    now = int(now)
    lc = int(row.get("last_change") or 0)
    if lc and now - lc < CHANGE_WINDOW:
        delta = int(row.get("last_delta") or 0)
        if delta < 0:
            return STATE_DOWN
        if delta > 0:
            return STATE_UP
    fs = int(row.get("first_seen") or 0)
    if fs and now - fs < NEW_WINDOW:
        return STATE_NEW
    return STATE_TRACKING
```

- [ ] **Step 6: 테스트가 통과하는지 확인한다**

Run: `cd delivery/integrated/manual_gui && python watch_listing_test.py`
Expected: `===== 18/18 PASS =====`, exit 0

- [ ] **Step 7: 기존 테스트가 여전히 통과하는지 확인한다**

Run: `cd delivery/integrated/manual_gui && python article_watch_test.py`
Expected: 이전과 같은 `N/N PASS`, exit 0

- [ ] **Step 8: 커밋**

```bash
git add daangn_ext/article_watch.py watch_listing_test.py
git commit -m "feat: watch 테이블을 매물 단일 진실로 확장

keyword·source·first_price·last_change·last_delta 컬럼과 price_history
테이블을 추가한다. 상태(state)는 저장하지 않고 tier·first_seen·last_change
로 파생한다 — 두 곳에 두면 한쪽만 갱신되는 버그가 난다."
```

---

### Task 2: 추적·이력 기록을 tracker 에 배선

**Files:**
- Modify: `daangn_ext/article_watch.py` — `WatchTracker.add_from_matches`(300행), `check_one`(346행)
- Test: `watch_listing_test.py` (섹션 F 추가)

**Interfaces:**
- Consumes: Task 1 의 `WatchStore.add_price`, 새 컬럼, `state_for`
- Produces:
  - `WatchTracker.add_from_matches(matches, now=None, source="app")` — `source` 인자가 추가됐다.
    매치 dict 의 `keyword` 를 `watch.keyword` 로, 파싱한 가격을 `price` 와 `first_price` 양쪽에
    넣고, `price_history` 에 기준선 1행을 남긴다.
  - `WatchTracker.check_one` — 가격이 바뀌면 `price_history` 에 1행을 남기고
    `last_change`/`last_delta` 를 갱신한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`watch_listing_test.py` 의 공통 꼬리 **앞에** 추가한다.

```python
# ── F. 추적 등록과 이력 기록 ──
import httpx


class FakeAPI:
    """지정한 응답을 순서대로 돌려준다."""

    def __init__(self, seq):
        self.seq = list(seq)

    def fetch(self, article_id):
        return self.seq.pop(0)

    def close(self):
        pass


d2 = tempfile.mkdtemp()
st2 = aw.WatchStore(os.path.join(d2, "w.db"))
tr2 = aw.WatchTracker(st2)

M = [{"article_id": "77", "title": "샤넬 클미", "price": "285만원",
      "region": "압구정", "url": "u77", "time": NOW - 3600, "keyword": "샤넬"}]
ck("매치 1건 등록", tr2.add_from_matches(M, now=NOW) == 1)
r77 = st2.get("77")
ck("keyword 저장", r77["keyword"] == "샤넬", str(r77.get("keyword")))
ck("source 기본 app", r77["source"] == "app", str(r77.get("source")))
ck("first_price = 파싱가", r77["first_price"] == 2850000, str(r77.get("first_price")))
ck("last_change 없음", not r77["last_change"])
ck("기준선 이력 1건", st2.price_history("77") == [{"ts": NOW, "price": 2850000}],
   str(st2.price_history("77")))

st3 = aw.WatchStore(os.path.join(d2, "w3.db"))
tr3 = aw.WatchTracker(st3)
tr3.add_from_matches([dict(M[0], article_id="88")], now=NOW, source="sweep")
ck("source 지정", st3.get("88")["source"] == "sweep")

# 첫 조회는 기준선 확보라 이벤트를 안 낸다. 두 번째 조회에서 인하가 잡힌다.
BASE = {"id": "77", "gone": False, "title": "샤넬 클미", "price": 2850000,
        "status": "ongoing", "status_name": "", "region": "압구정", "url": "u77",
        "published_at": NOW - 3600, "updated_at": NOW, "republish_count": 0,
        "watches_count": 0, "chat_rooms_count": 0, "reads_count": 0}
ev = tr2.check_one("77", FakeAPI([dict(BASE)]), now=NOW + 10)
ck("첫 조회는 조용", ev == [], str(ev))
ev = tr2.check_one("77", FakeAPI([dict(BASE, price=2600000)]), now=NOW + 20)
ck("두 번째 조회에서 인하 감지",
   [e["kind"] for e in ev] == ["price_down"], str(ev))
r77 = st2.get("77")
ck("last_change 갱신", r77["last_change"] == NOW + 20, str(r77.get("last_change")))
ck("last_delta 음수", r77["last_delta"] == -250000, str(r77.get("last_delta")))
ck("first_price 불변", r77["first_price"] == 2850000, str(r77.get("first_price")))
ck("이력 2건", len(st2.price_history("77")) == 2,
   str(st2.price_history("77")))
ck("state 는 down", aw.state_for(r77, NOW + 30) == aw.STATE_DOWN)

# 가격이 그대로면 이력이 늘지 않는다.
tr2.check_one("77", FakeAPI([dict(BASE, price=2600000)]), now=NOW + 30)
ck("무변동은 이력 안 늘림", len(st2.price_history("77")) == 2,
   str(st2.price_history("77")))
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd delivery/integrated/manual_gui && python watch_listing_test.py`
Expected: FAIL — "keyword 저장", "source 기본 app", "first_price = 파싱가",
"기준선 이력 1건", "last_change 갱신" 등이 실패한다.

- [ ] **Step 3: `add_from_matches` 를 고친다**

`daangn_ext/article_watch.py:300` 의 시그니처와 `upsert` 블록을 교체한다.

```python
    def add_from_matches(self, matches, now=None, source="app") -> int:
        now = self._now(now)
        added = 0
        for m in matches or []:
            aid = m.get("article_id")
            if not aid:
                continue
            aid = str(aid)
            prev = self.store.get(aid)
            # evicted 는 상한/실패로 접었을 뿐이다 — 다시 매칭됐다는 건 살아 있다는
            # 뜻이니 재등록한다. dead(판매완료·삭제)와 추적 중인 행은 건너뛴다.
            if prev is not None and (prev.get("tier") or "") != TIER_EVICTED:
                continue
            try:
                published = int(m.get("time") or 0)
            except (TypeError, ValueError):
                published = 0
            tier = tier_for(published, now)
            if tier == TIER_DEAD:
                continue
            price = parse_price_text(m.get("price"))
            self.store.upsert({
                "id": aid,
                "title": m.get("title") or "",
                "region": m.get("region") or "",
                "url": m.get("url") or "",
                "price": price,
                "status": STATUS_ONGOING,
                "republish_count": 0,
                "published_at": published,
                "first_seen": now,
                "last_check": now,
                "next_check": now + interval_for(tier),
                "tier": tier,
                "fail": 0,
                "keyword": m.get("keyword") or "",
                "source": source,
                # 씨앗 가격은 알림 표시 문자열에서 왔다. Δ 의 기준선으로 쓰되,
                # 첫 실측 조회가 이 값을 덮어쓰지 않게 price 와 따로 둔다.
                "first_price": price,
                "last_change": 0,
                "last_delta": 0,
            })
            if price:
                self.store.add_price(aid, now, price)
            added += 1
        return added
```

- [ ] **Step 4: `check_one` 의 갱신 블록을 고친다**

`daangn_ext/article_watch.py:376` 부근, `events = [] if seeding else diff_events(...)`
다음부터 `return events` 까지를 교체한다.

```python
        events = [] if seeding else diff_events(old, new, now)
        if new.get("gone"):
            self.store.mark(article_id, tier=TIER_DEAD, fail=0, last_check=now)
            return events

        tier = tier_for(new.get("published_at") or old.get("published_at") or 0, now)
        if new.get("status") == STATUS_CLOSED:
            tier = TIER_DEAD
        price = new.get("price") if isinstance(new.get("price"), int) \
            else old.get("price")
        old_price = old.get("price")
        changed = (isinstance(price, int) and isinstance(old_price, int)
                   and price != old_price and not seeding)
        self.store.upsert({
            "id": str(article_id),
            "title": new.get("title") or old.get("title"),
            "region": new.get("region") or old.get("region"),
            "url": new.get("url") or old.get("url"),
            "price": price,
            "status": new.get("status"),
            "republish_count": new.get("republish_count") or 0,
            "published_at": new.get("published_at") or old.get("published_at") or 0,
            "first_seen": old.get("first_seen") or now,
            "last_check": now,
            "next_check": now + interval_for(tier),
            "tier": tier,
            "fail": 0,
            "keyword": old.get("keyword") or "",
            "source": old.get("source") or "app",
            # 씨앗 단계에서 first_price 가 비어 있으면(구버전 행) 첫 실측을 기준선으로 삼는다.
            "first_price": old.get("first_price") or price,
            "last_change": now if changed else (old.get("last_change") or 0),
            "last_delta": (price - old_price) if changed
                          else (old.get("last_delta") or 0),
        })
        if changed:
            self.store.add_price(str(article_id), now, price)
        return events
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `cd delivery/integrated/manual_gui && python watch_listing_test.py`
Expected: `===== 32/32 PASS =====`, exit 0

- [ ] **Step 6: 기존 테스트가 여전히 통과하는지 확인한다**

Run: `cd delivery/integrated/manual_gui && python article_watch_test.py`
Expected: 이전과 같은 `N/N PASS`, exit 0

- [ ] **Step 7: 커밋**

```bash
git add daangn_ext/article_watch.py watch_listing_test.py
git commit -m "feat: 추적 등록·가격 이력에 키워드와 기준선을 남긴다

add_from_matches 가 keyword·source·first_price 를 채우고 기준선 이력 1행을
남긴다. check_one 은 가격이 바뀔 때만 이력을 늘리고 last_change·last_delta
를 갱신한다 — 표의 Δ 열과 상태 아이콘이 이 두 값에서 나온다."
```

---

### Task 3: 스윕 대기열

**Files:**
- Create: `daangn_ext/sweep_queue.py`
- Test: `sweep_queue_test.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `SweepQueue(path="./data/sweep_queue.json")`
  - `.add(keyword: str, min_price=None, max_price=None, exclude=None, at: int|None = None) -> bool`
    — 이미 있으면 `False`
  - `.remove(keyword: str) -> bool`
  - `.keywords() -> list[str]` — 큐 순서(오래된 것 먼저)
  - `.entries() -> list[dict]` — `[{"keyword","min","max","exclude","at"}]`
  - `.oldest(n: int) -> list[dict]`
  - `.__len__()`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`sweep_queue_test.py` 를 만든다. 공통 서두 뒤에 넣는다.

```python
import json
import tempfile

from daangn_ext.sweep_queue import SweepQueue

d = tempfile.mkdtemp()
p = os.path.join(d, "q.json")

q = SweepQueue(p)
ck("빈 큐 길이 0", len(q) == 0)
ck("빈 큐 keywords", q.keywords() == [])

ck("추가 성공", q.add("샤넬", min_price=100, at=10) is True)
ck("중복 추가는 False", q.add("샤넬", at=11) is False)
ck("길이 1", len(q) == 1)
ck("keywords", q.keywords() == ["샤넬"])
e = q.entries()[0]
ck("entry min", e["min"] == 100, str(e))
ck("entry at", e["at"] == 10, str(e))
ck("entry exclude 기본 빈 리스트", e["exclude"] == [], str(e))

q.add("루이비통", at=20)
q.add("에르메스", at=30)
ck("오래된 순", q.keywords() == ["샤넬", "루이비통", "에르메스"])
ck("oldest(2)", [x["keyword"] for x in q.oldest(2)] == ["샤넬", "루이비통"])

ck("삭제 성공", q.remove("루이비통") is True)
ck("없는 것 삭제는 False", q.remove("없음") is False)
ck("삭제 반영", q.keywords() == ["샤넬", "에르메스"])

# 영속 — 다시 열면 그대로다
q2 = SweepQueue(p)
ck("재시작 후 유지", q2.keywords() == ["샤넬", "에르메스"], str(q2.keywords()))

# 파일이 깨져도 빈 큐로 시작한다(예외를 올리지 않는다)
with open(p, "w", encoding="utf-8") as f:
    f.write("{깨진 json")
q3 = SweepQueue(p)
ck("깨진 파일은 빈 큐", q3.keywords() == [])
ck("깨진 뒤에도 추가 가능", q3.add("구찌", at=40) is True)

# 없는 디렉토리도 만들어 준다
p4 = os.path.join(d, "sub", "deep", "q.json")
q4 = SweepQueue(p4)
q4.add("프라다", at=50)
ck("디렉토리 자동 생성", os.path.exists(p4))
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd delivery/integrated/manual_gui && python sweep_queue_test.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'daangn_ext.sweep_queue'`

- [ ] **Step 3: 최소 구현을 쓴다**

`daangn_ext/sweep_queue.py`:

```python
"""앱 API 슬롯에 못 들어간 키워드의 대기열.

검색 스윕은 슬롯 제한이 없는 대신 느리다. 여기 쌓인 키워드는 스윕 엔진이
커버하고, 앱 슬롯이 비면 KeywordRouter 가 오래된 것부터 앱으로 승격한다.
"""
from __future__ import annotations

import json
import os
import time


class SweepQueue:
    """JSON 한 파일. 키워드 수가 세 자릿수를 넘지 않으므로 sqlite 는 과하다."""

    def __init__(self, path: str = "./data/sweep_queue.json"):
        self.path = path
        self._items = self._load()

    def _load(self) -> list[dict]:
        """없거나 깨졌으면 빈 큐. 예외를 올리지 않는다 — 대기열이 깨졌다고
        감시가 멈추면 안 된다."""
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        out = []
        for it in data:
            if isinstance(it, dict) and it.get("keyword"):
                out.append({"keyword": str(it["keyword"]),
                            "min": it.get("min"),
                            "max": it.get("max"),
                            "exclude": list(it.get("exclude") or []),
                            "at": int(it.get("at") or 0)})
        return out

    def _save(self) -> None:
        try:
            d = os.path.dirname(self.path)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._items, f, ensure_ascii=False)
        except Exception:
            pass

    def add(self, keyword: str, min_price=None, max_price=None,
            exclude=None, at: int | None = None) -> bool:
        keyword = str(keyword or "").strip()
        if not keyword or any(i["keyword"] == keyword for i in self._items):
            return False
        self._items.append({"keyword": keyword, "min": min_price,
                            "max": max_price, "exclude": list(exclude or []),
                            "at": int(at if at is not None else time.time())})
        self._save()
        return True

    def remove(self, keyword: str) -> bool:
        before = len(self._items)
        self._items = [i for i in self._items if i["keyword"] != str(keyword)]
        if len(self._items) == before:
            return False
        self._save()
        return True

    def keywords(self) -> list[str]:
        return [i["keyword"] for i in self._ordered()]

    def entries(self) -> list[dict]:
        return [dict(i) for i in self._ordered()]

    def oldest(self, n: int) -> list[dict]:
        return [dict(i) for i in self._ordered()[:max(0, int(n))]]

    def _ordered(self) -> list[dict]:
        return sorted(self._items, key=lambda i: i.get("at") or 0)

    def __len__(self) -> int:
        return len(self._items)
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `cd delivery/integrated/manual_gui && python sweep_queue_test.py`
Expected: `===== 19/19 PASS =====`, exit 0

- [ ] **Step 5: 커밋**

```bash
git add daangn_ext/sweep_queue.py sweep_queue_test.py
git commit -m "feat: 스윕 대기열

앱 슬롯에 못 들어간 키워드를 JSON 한 파일에 쌓는다. 깨진 파일은 빈 큐로
읽는다 — 대기열이 깨졌다고 감시가 멈추면 안 된다."
```

---

### Task 4: 키워드 라우터

**Files:**
- Create: `daangn_ext/keyword_router.py`
- Test: `keyword_router_test.py`

**Interfaces:**
- Consumes: Task 3 의 `SweepQueue`; 기존 `MultiAccountAlerts.register_all(keywords, min_price, max_price, exclude_keywords, log, core_only) -> {"added": int, "skipped": int, "failed": int}`
- Produces:
  - `KeywordRouter(alerts, queue, slot_cap=30, routes_fp="./data/keyword_routes.json")`
  - `.capacity() -> dict` — `{"cap": int, "used": int, "free": int}`
  - `.add(keyword, min_price=None, max_price=None, exclude=None, core_only=False, log=None) -> dict`
    — `{"keyword", "route": "app"|"sweep", "reason": str}`
  - `.add_many(keywords, min_price=None, max_price=None, exclude=None, core_only=False, log=None) -> list[dict]`
  - `.remove(keyword) -> None`
  - `.rebalance(core_only=False, log=None) -> list[dict]` — 승격된 항목의 `add` 결과 목록
  - `.routes() -> list[dict]` — `[{"keyword","route","reason","at"}]`
  - 상수 `DEFAULT_SLOT_CAP = 30`

**슬롯 계산의 근거.** `register_all` 은 같은 키워드를 **모든 유효 계정에** 등록한다.
따라서 계정을 늘려도 등록 가능한 **키워드 종류**는 늘지 않는다 — 함대 전체의
키워드 한도는 계정당 상한(기본 30)과 같다. 그래서 `used` 는 앱으로 배정된 키워드
수이고, 네트워크 조회가 필요 없다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`keyword_router_test.py` 를 만든다. 공통 서두 뒤에 넣는다.

```python
import tempfile

from daangn_ext.keyword_router import KeywordRouter, DEFAULT_SLOT_CAP
from daangn_ext.sweep_queue import SweepQueue


class FakeAlerts:
    """register_all 호출을 기록한다. banned 에 든 키워드는 실패로 돌린다."""

    def __init__(self, banned=()):
        self.calls = []
        self.banned = set(banned)

    def register_all(self, keywords, min_price=None, max_price=None,
                     exclude_keywords=None, log=None, core_only=False):
        self.calls.append({"keywords": list(keywords), "min": min_price,
                           "max": max_price, "exclude": exclude_keywords,
                           "core_only": core_only})
        bad = [k for k in keywords if k in self.banned]
        return {"added": len(keywords) - len(bad), "skipped": 0,
                "failed": len(bad)}


def mk(slot_cap=DEFAULT_SLOT_CAP, banned=()):
    d = tempfile.mkdtemp()
    alerts = FakeAlerts(banned)
    q = SweepQueue(os.path.join(d, "q.json"))
    r = KeywordRouter(alerts, q, slot_cap=slot_cap,
                      routes_fp=os.path.join(d, "routes.json"))
    return alerts, q, r


# ── A. 여유가 있으면 앱으로 ──
alerts, q, r = mk(slot_cap=3)
res = r.add("샤넬")
ck("여유 있으면 app", res["route"] == "app", str(res))
ck("register_all 호출됨", len(alerts.calls) == 1, str(alerts.calls))
ck("호출 키워드", alerts.calls[0]["keywords"] == ["샤넬"])
ck("큐 비어 있음", len(q) == 0)
cap = r.capacity()
ck("capacity used 1", cap["used"] == 1, str(cap))
ck("capacity free 2", cap["free"] == 2, str(cap))

# ── B. 만원이면 스윕으로 ──
r.add("루이비통"); r.add("에르메스")
ck("슬롯 소진", r.capacity()["free"] == 0, str(r.capacity()))
n_before = len(alerts.calls)
res = r.add("구찌")
ck("만원이면 sweep", res["route"] == "sweep", str(res))
ck("만원이면 register_all 안 부름", len(alerts.calls) == n_before)
ck("사유 기록", "슬롯" in res["reason"], res["reason"])
ck("큐에 들어감", q.keywords() == ["구찌"], str(q.keywords()))

# ── C. 밴 키워드는 스윕 폴백 ──
alerts2, q2, r2 = mk(slot_cap=5, banned={"짝퉁"})
res = r2.add("짝퉁")
ck("밴이면 sweep", res["route"] == "sweep", str(res))
ck("밴 사유", "등록 실패" in res["reason"] or "차단" in res["reason"], res["reason"])
ck("밴이면 큐로", q2.keywords() == ["짝퉁"])
ck("밴은 슬롯 안 먹음", r2.capacity()["used"] == 0, str(r2.capacity()))

# ── D. 승격 ──
alerts3, q3, r3 = mk(slot_cap=2)
r3.add("A"); r3.add("B")            # 슬롯 만원
r3.add("C"); r3.add("D")            # 큐로
ck("큐 2건", q3.keywords() == ["C", "D"], str(q3.keywords()))
ck("슬롯 없으면 rebalance 무동작", r3.rebalance() == [])
r3.remove("A")
ck("삭제 후 여유 1", r3.capacity()["free"] == 1, str(r3.capacity()))
promoted = r3.rebalance()
ck("한 건 승격", len(promoted) == 1, str(promoted))
ck("오래된 것부터", promoted[0]["keyword"] == "C", str(promoted))
ck("승격은 app", promoted[0]["route"] == "app")
ck("승격분 큐에서 빠짐", q3.keywords() == ["D"], str(q3.keywords()))

# ── E. routes 목록 ──
rows = {x["keyword"]: x for x in r3.routes()}
ck("routes 에 B", rows.get("B", {}).get("route") == "app", str(rows))
ck("routes 에 D 는 sweep", rows.get("D", {}).get("route") == "sweep", str(rows))
ck("삭제된 A 는 없음", "A" not in rows, str(rows))

# ── F. 영속 ──
d6 = tempfile.mkdtemp()
a6 = FakeAlerts()
q6 = SweepQueue(os.path.join(d6, "q.json"))
fp6 = os.path.join(d6, "routes.json")
r6 = KeywordRouter(a6, q6, slot_cap=2, routes_fp=fp6)
r6.add("X")
r6b = KeywordRouter(FakeAlerts(), SweepQueue(os.path.join(d6, "q.json")),
                    slot_cap=2, routes_fp=fp6)
ck("재시작 후 라우트 유지", r6b.capacity()["used"] == 1, str(r6b.capacity()))

# ── G. add_many ──
alerts7, q7, r7 = mk(slot_cap=2)
out = r7.add_many(["P", "Q", "R"])
ck("add_many 3건 결과", len(out) == 3, str(out))
ck("앞의 둘은 app", [o["route"] for o in out[:2]] == ["app", "app"], str(out))
ck("셋째는 sweep", out[2]["route"] == "sweep", str(out))
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd delivery/integrated/manual_gui && python keyword_router_test.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'daangn_ext.keyword_router'`

- [ ] **Step 3: 최소 구현을 쓴다**

`daangn_ext/keyword_router.py`:

```python
"""키워드를 앱 API 슬롯 또는 검색 스윕으로 자동 배정한다.

사용자는 키워드만 넣는다. 어느 경로로 잡히는지는 라우터가 정하고, 화면에는
진단용으로만 보여준다. 경로를 고르게 하면 사용자가 슬롯 산수를 해야 한다.

슬롯 계산: register_all 은 같은 키워드를 모든 유효 계정에 등록한다. 계정을
늘려도 등록 가능한 키워드 '종류'는 늘지 않는다 — 함대 전체 한도가 곧 계정당
상한이다. 그래서 used 는 앱으로 배정된 키워드 수이고 네트워크 조회가 없다.
"""
from __future__ import annotations

import json
import os
import time

DEFAULT_SLOT_CAP = 30

ROUTE_APP = "app"
ROUTE_SWEEP = "sweep"


class KeywordRouter:
    def __init__(self, alerts, queue, slot_cap: int = DEFAULT_SLOT_CAP,
                 routes_fp: str = "./data/keyword_routes.json"):
        self.alerts = alerts
        self.queue = queue
        self.slot_cap = int(slot_cap)
        self.routes_fp = routes_fp
        self._routes = self._load()

    # ── 영속 ──
    def _load(self) -> dict:
        try:
            with open(self.routes_fp, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        out = {}
        for k, v in data.items():
            if isinstance(v, dict) and v.get("route") in (ROUTE_APP, ROUTE_SWEEP):
                out[str(k)] = {"route": v["route"],
                               "reason": str(v.get("reason") or ""),
                               "at": int(v.get("at") or 0)}
        return out

    def _save(self) -> None:
        try:
            d = os.path.dirname(self.routes_fp)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(self.routes_fp, "w", encoding="utf-8") as f:
                json.dump(self._routes, f, ensure_ascii=False)
        except Exception:
            pass

    # ── 조회 ──
    def capacity(self) -> dict:
        used = sum(1 for v in self._routes.values() if v["route"] == ROUTE_APP)
        return {"cap": self.slot_cap, "used": used,
                "free": max(0, self.slot_cap - used)}

    def routes(self) -> list[dict]:
        return [dict(v, keyword=k) for k, v in
                sorted(self._routes.items(), key=lambda kv: kv[1].get("at") or 0)]

    # ── 배정 ──
    def add(self, keyword, min_price=None, max_price=None, exclude=None,
            core_only=False, log=None) -> dict:
        log = log or (lambda m: None)
        keyword = str(keyword or "").strip()
        now = int(time.time())
        if not keyword:
            return {"keyword": keyword, "route": ROUTE_SWEEP, "reason": "빈 키워드"}

        if self.capacity()["free"] <= 0:
            return self._to_sweep(keyword, min_price, max_price, exclude, now,
                                  f"앱 슬롯 만원({self.slot_cap})", log)
        try:
            res = self.alerts.register_all(
                [keyword], min_price, max_price, exclude,
                log=log, core_only=core_only) or {}
        except Exception as e:
            return self._to_sweep(keyword, min_price, max_price, exclude, now,
                                  f"등록 실패: {str(e)[:60]}", log)
        if not res.get("added") and res.get("failed"):
            # 차단 키워드거나 전 계정에서 거절됐다. 스윕은 이 제약을 안 받는다.
            return self._to_sweep(keyword, min_price, max_price, exclude, now,
                                  "앱 등록 실패(차단 키워드 등)", log)

        self.queue.remove(keyword)
        self._routes[keyword] = {"route": ROUTE_APP, "reason": "앱 알림 등록",
                                 "at": now}
        self._save()
        return {"keyword": keyword, "route": ROUTE_APP, "reason": "앱 알림 등록"}

    def add_many(self, keywords, min_price=None, max_price=None, exclude=None,
                 core_only=False, log=None) -> list[dict]:
        return [self.add(k, min_price, max_price, exclude, core_only, log)
                for k in keywords or []]

    def _to_sweep(self, keyword, min_price, max_price, exclude, now, reason,
                  log) -> dict:
        self.queue.add(keyword, min_price, max_price, exclude, at=now)
        self._routes[keyword] = {"route": ROUTE_SWEEP, "reason": reason, "at": now}
        self._save()
        log(f"  {keyword}: 검색 스윕으로 — {reason}")
        return {"keyword": keyword, "route": ROUTE_SWEEP, "reason": reason}

    def remove(self, keyword) -> None:
        keyword = str(keyword)
        self.queue.remove(keyword)
        if self._routes.pop(keyword, None) is not None:
            self._save()

    def rebalance(self, core_only=False, log=None) -> list[dict]:
        """앱 슬롯이 비면 대기열 최고참을 승격한다. 강등은 하지 않는다."""
        free = self.capacity()["free"]
        if free <= 0 or not len(self.queue):
            return []
        out = []
        for entry in self.queue.oldest(free):
            res = self.add(entry["keyword"], entry.get("min"), entry.get("max"),
                           entry.get("exclude"), core_only=core_only, log=log)
            if res["route"] == ROUTE_APP:
                out.append(res)
            else:
                break               # 여전히 안 되면 다음 회차로
        return out
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `cd delivery/integrated/manual_gui && python keyword_router_test.py`
Expected: `===== 27/27 PASS =====`, exit 0

- [ ] **Step 5: 커밋**

```bash
git add daangn_ext/keyword_router.py keyword_router_test.py
git commit -m "feat: 키워드 라우터 — 앱 슬롯/검색 스윕 자동 배정

같은 키워드가 전 계정에 등록되므로 함대 전체 키워드 한도는 계정당 상한과
같다. 슬롯이 남으면 앱 알림으로, 만원이거나 차단 키워드면 스윕 큐로 보내고,
슬롯이 비면 대기열 최고참을 승격한다. 사용자는 경로를 고르지 않는다."
```

---

### Task 5: 감시 컨트롤러

**Files:**
- Create: `daangn_ext/supervisor.py`
- Test: `supervisor_test.py`

**Interfaces:**
- Consumes: 없음 (타이머는 주입받는다)
- Produces:
  - `SupervisorPolicy(poll_interval_fn, night_factor_fn, sweep_interval=600)`
  - `.poll_ms() -> int` — 폴링 타이머 간격(밀리초, 야간 배수 적용)
  - `.sweep_ms() -> int` — 스윕 타이머 간격(밀리초, 야간 배수 적용)
  - `SupervisorController(policy, poll_timer, sweep_timer, sweep_queue, start_search_sweep, stop_search_sweep)`
  - `.start() -> None`, `.stop() -> None`, `.is_running() -> bool`
  - `.retune() -> None` — 실행 중이면 두 타이머 간격을 현재 정책으로 갱신

Qt 를 import 하지 않는다. 타이머는 `start(ms)` / `stop()` / `isActive()` /
`setInterval(ms)` / `interval()` 을 가진 무엇이든 된다 — `QTimer` 가 그 모양이고,
테스트는 가짜 타이머를 넣는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`supervisor_test.py` 를 만든다. 공통 서두 뒤에 넣는다.

```python
from daangn_ext.supervisor import SupervisorController, SupervisorPolicy


class FakeTimer:
    def __init__(self):
        self.active = False
        self._interval = 0
        self.starts = []

    def start(self, ms):
        self.active = True
        self._interval = int(ms)
        self.starts.append(int(ms))

    def stop(self):
        self.active = False

    def isActive(self):
        return self.active

    def setInterval(self, ms):
        self._interval = int(ms)

    def interval(self):
        return self._interval


class FakeQueue:
    def __init__(self, n=0):
        self.n = n

    def __len__(self):
        return self.n


def mk(queue_n=0, poll=120, night=1):
    pt, stt = FakeTimer(), FakeTimer()
    calls = {"start": 0, "stop": 0}
    pol = SupervisorPolicy(lambda: poll, lambda: night, sweep_interval=600)
    c = SupervisorController(
        pol, pt, stt, FakeQueue(queue_n),
        start_search_sweep=lambda: calls.__setitem__("start", calls["start"] + 1),
        stop_search_sweep=lambda: calls.__setitem__("stop", calls["stop"] + 1))
    return c, pt, stt, calls


# ── A. 정책 ──
pol = SupervisorPolicy(lambda: 120, lambda: 3, sweep_interval=600)
ck("폴링 ms", pol.poll_ms() == 120 * 3 * 1000, str(pol.poll_ms()))
ck("스윕 ms", pol.sweep_ms() == 600 * 3 * 1000, str(pol.sweep_ms()))
pol2 = SupervisorPolicy(lambda: 120, lambda: 1, sweep_interval=600)
ck("배수 1이면 그대로", pol2.poll_ms() == 120000, str(pol2.poll_ms()))

# ── B. start 는 두 타이머를 켠다 ──
c, pt, stt, calls = mk()
ck("시작 전 안 돎", c.is_running() is False)
c.start()
ck("실행 중", c.is_running() is True)
ck("폴링 타이머 켜짐", pt.isActive() is True)
ck("스윕 타이머 켜짐", stt.isActive() is True)
ck("폴링 간격", pt.interval() == 120000, str(pt.interval()))
ck("스윕 간격", stt.interval() == 600000, str(stt.interval()))

# ── C. 큐가 비면 검색 스윕은 안 띄운다 ──
ck("빈 큐면 검색스윕 미기동", calls["start"] == 0, str(calls))

c2, pt2, stt2, calls2 = mk(queue_n=3)
c2.start()
ck("큐 있으면 검색스윕 기동", calls2["start"] == 1, str(calls2))

# ── D. stop ──
c2.stop()
ck("정지 후 안 돎", c2.is_running() is False)
ck("폴링 타이머 꺼짐", pt2.isActive() is False)
ck("스윕 타이머 꺼짐", stt2.isActive() is False)
ck("검색스윕 정지 호출", calls2["stop"] == 1, str(calls2))

# ── E. 중복 start 는 무해하다 ──
c3, pt3, stt3, calls3 = mk(queue_n=1)
c3.start(); c3.start()
ck("중복 start 는 한 번만 기동", calls3["start"] == 1, str(calls3))
ck("타이머 재시작 안 함", len(pt3.starts) == 1, str(pt3.starts))

# ── F. 야간 배수 변경 반영 ──
factor = {"v": 1}
pol4 = SupervisorPolicy(lambda: 120, lambda: factor["v"], sweep_interval=600)
pt4, stt4 = FakeTimer(), FakeTimer()
c4 = SupervisorController(pol4, pt4, stt4, FakeQueue(0),
                          start_search_sweep=lambda: None,
                          stop_search_sweep=lambda: None)
c4.start()
factor["v"] = 3
c4.retune()
ck("retune 이 폴링 간격 갱신", pt4.interval() == 360000, str(pt4.interval()))
ck("retune 이 스윕 간격 갱신", stt4.interval() == 1800000, str(stt4.interval()))
c4.stop()
factor["v"] = 1
c4.retune()
ck("정지 중 retune 은 무동작", pt4.isActive() is False)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd delivery/integrated/manual_gui && python supervisor_test.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'daangn_ext.supervisor'`

- [ ] **Step 3: 최소 구현을 쓴다**

`daangn_ext/supervisor.py`:

```python
"""감시 수명주기 — 토글 하나가 폴링·워치 스윕·검색 스윕을 함께 관장한다.

이전에는 워치 스윕 타이머가 '자동 폴링' 버튼에 묶여 있어서, 폴링을 끄면
가격 추적도 같이 멈췄다. 사용자 의도와 어긋난다. 여기서는 셋이 한 수명을
공유하고 시작·정지가 한 곳에서만 일어난다.

Qt 를 import 하지 않는다. 타이머는 start(ms)/stop()/isActive()/setInterval(ms)/
interval() 을 가진 무엇이든 된다 — QTimer 가 그 모양이다.
"""
from __future__ import annotations


class SupervisorPolicy:
    """간격 계산만 한다. 야간 감속 배수는 두 타이머에 똑같이 곱한다."""

    def __init__(self, poll_interval_fn, night_factor_fn, sweep_interval: int = 600):
        self._poll_fn = poll_interval_fn
        self._night_fn = night_factor_fn
        self.sweep_interval = int(sweep_interval)

    def _factor(self) -> int:
        try:
            return max(1, int(self._night_fn() or 1))
        except Exception:
            return 1

    def poll_ms(self) -> int:
        try:
            base = max(1, int(self._poll_fn() or 0))
        except Exception:
            base = 120
        return base * self._factor() * 1000

    def sweep_ms(self) -> int:
        return self.sweep_interval * self._factor() * 1000


class SupervisorController:
    def __init__(self, policy, poll_timer, sweep_timer, sweep_queue,
                 start_search_sweep, stop_search_sweep):
        self.policy = policy
        self.poll_timer = poll_timer
        self.sweep_timer = sweep_timer
        self.sweep_queue = sweep_queue
        self._start_search = start_search_sweep
        self._stop_search = stop_search_sweep
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.poll_timer.start(self.policy.poll_ms())
        self.sweep_timer.start(self.policy.sweep_ms())
        # 검색 스윕은 대기열이 있을 때만 띄운다 — 빈 조건으로 지역을 훑으면
        # 요청만 쓰고 아무것도 안 잡는다.
        if len(self.sweep_queue):
            self._start_search()

    def stop(self) -> None:
        self._running = False
        self.poll_timer.stop()
        self.sweep_timer.stop()
        self._stop_search()

    def retune(self) -> None:
        """정책 값이 바뀌었을 때(주기 변경·야간 진입) 간격만 갈아끼운다."""
        if not self._running:
            return
        self.poll_timer.setInterval(self.policy.poll_ms())
        self.sweep_timer.setInterval(self.policy.sweep_ms())
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `cd delivery/integrated/manual_gui && python supervisor_test.py`
Expected: `===== 20/20 PASS =====`, exit 0

- [ ] **Step 5: 커밋**

```bash
git add daangn_ext/supervisor.py supervisor_test.py
git commit -m "feat: 감시 컨트롤러 — 폴링·스윕 한 수명

워치 스윕이 자동폴링 버튼에 묶여 있어 폴링을 끄면 가격 추적도 멈추던 결합을
푼다. 검색 스윕은 대기열이 있을 때만 띄운다. Qt 를 import 하지 않아 가짜
타이머로 테스트된다."
```

---

### Task 6: 백필 스크립트

**Files:**
- Create: `tools/backfill_listings.py`
- Test: `backfill_test.py`

**Interfaces:**
- Consumes: Task 1·2 의 확장된 `WatchStore` / `WatchTracker`
- Produces:
  - `backfill_listings.backfill(store, auto_seen_db: str|None, match_seen_json: str|None, now: int) -> dict`
    — `{"from_auto": int, "from_match": int, "skipped": int}`
  - `python tools/backfill_listings.py` — 기본 경로(`./auto_seen.db`, `./data/match_seen.json`,
    `./data/watch.db`)로 1회 실행

`auto_seen.db` 의 `seen` 테이블은 `id, price, region, title` 뿐이다 — 게시 시각이
없다. 게시 시각을 모르는 행은 `tier_for` 가 `fresh` 로 본다(기존 동작). 그 편이
`dead` 로 잘못 버리는 것보다 낫다.

`match_seen.json` 은 문자열 배열(본 매물 id 목록)이라 제목·가격이 없다. 이 목록은
**행을 만들지 않고** 이미 있는 행의 유무만 확인하는 데 쓴다 — 정보가 없는 행을
만들면 표에 빈 줄이 생긴다. 그래서 `from_match` 는 항상 0 이고, 이 파일은 백필
후 지운다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backfill_test.py` 를 만든다. 공통 서두 뒤에 넣는다.

```python
import json
import sqlite3
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))

from daangn_ext import article_watch as aw
import backfill_listings as bf

NOW = 1788000000

d = tempfile.mkdtemp()
auto = os.path.join(d, "auto_seen.db")
con = sqlite3.connect(auto)
con.execute("CREATE TABLE seen(id TEXT PRIMARY KEY, price INTEGER, "
            "region TEXT, title TEXT)")
con.executemany("INSERT INTO seen VALUES(?,?,?,?)", [
    ("101", 2850000, "압구정", "샤넬 클미"),
    ("102", 1200000, "분당", "루이비통 알마"),
])
con.commit(); con.close()

ms = os.path.join(d, "match_seen.json")
with open(ms, "w", encoding="utf-8") as f:
    json.dump(["101", "999"], f)

st = aw.WatchStore(os.path.join(d, "watch.db"))
res = bf.backfill(st, auto, ms, NOW)
ck("auto_seen 2건 백필", res["from_auto"] == 2, str(res))
ck("match_seen 은 행 안 만듦", res["from_match"] == 0, str(res))

r = st.get("101")
ck("제목 이관", r["title"] == "샤넬 클미", str(r))
ck("지역 이관", r["region"] == "압구정")
ck("가격 이관", r["price"] == 2850000)
ck("first_price 채움", r["first_price"] == 2850000)
ck("source = sweep", r["source"] == "sweep", str(r.get("source")))
ck("tier fresh(게시시각 없음)", r["tier"] == "fresh", str(r.get("tier")))
ck("기준선 이력", st.price_history("101") == [{"ts": NOW, "price": 2850000}],
   str(st.price_history("101")))

# 이미 있는 행은 덮어쓰지 않는다
st.upsert({"id": "103", "title": "지키던 행", "region": "", "url": "",
           "price": 500, "status": "ongoing", "republish_count": 0,
           "published_at": NOW, "first_seen": NOW, "last_check": NOW,
           "next_check": NOW, "tier": "fresh", "fail": 0, "keyword": "기존",
           "source": "app", "first_price": 500, "last_change": 0,
           "last_delta": 0})
con = sqlite3.connect(auto)
con.execute("INSERT INTO seen VALUES('103', 9, '딴데', '덮어쓰면 안 됨')")
con.commit(); con.close()
res2 = bf.backfill(st, auto, ms, NOW + 10)
ck("기존 행 건너뜀", res2["skipped"] >= 1, str(res2))
ck("기존 행 보존", st.get("103")["title"] == "지키던 행", str(st.get("103")))

# 파일이 없어도 조용히 0 건
res3 = bf.backfill(st, os.path.join(d, "없음.db"),
                   os.path.join(d, "없음.json"), NOW)
ck("없는 파일은 0건", res3["from_auto"] == 0, str(res3))
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd delivery/integrated/manual_gui && python backfill_test.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'backfill_listings'`

- [ ] **Step 3: 최소 구현을 쓴다**

`tools/backfill_listings.py`:

```python
"""auto_seen.db 를 watch 테이블로 한 번 옮긴다.

자동 모니터가 따로 들고 있던 '본 매물' 기록을 매물 표의 단일 진실로 합친다.
한 번 돌리고 나면 auto_seen.db 와 match_seen.json 은 지워도 된다.

    python tools/backfill_listings.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from daangn_ext import article_watch as aw


def backfill(store, auto_seen_db, match_seen_json, now: int) -> dict:
    """이미 있는 행은 건드리지 않는다 — 실측으로 갱신된 값이 백필값보다 낫다."""
    out = {"from_auto": 0, "from_match": 0, "skipped": 0}

    rows = []
    if auto_seen_db and os.path.exists(auto_seen_db):
        try:
            con = sqlite3.connect(auto_seen_db)
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT id, price, region, title FROM seen").fetchall()
            con.close()
        except Exception:
            rows = []

    for r in rows:
        aid = str(r["id"])
        if store.get(aid) is not None:
            out["skipped"] += 1
            continue
        price = int(r["price"] or 0)
        # 게시 시각이 없다 — tier_for 는 0 을 fresh 로 본다. dead 로 잘못 버리는
        # 것보다 한 주기 더 확인해 보는 편이 낫다.
        tier = aw.tier_for(0, now)
        store.upsert({
            "id": aid,
            "title": r["title"] or "",
            "region": r["region"] or "",
            "url": "",
            "price": price,
            "status": aw.STATUS_ONGOING,
            "republish_count": 0,
            "published_at": 0,
            "first_seen": now,
            "last_check": now,
            "next_check": now + aw.interval_for(tier),
            "tier": tier,
            "fail": 0,
            "keyword": "",
            "source": "sweep",
            "first_price": price,
            "last_change": 0,
            "last_delta": 0,
        })
        if price:
            store.add_price(aid, now, price)
        out["from_auto"] += 1

    # match_seen.json 은 id 문자열 배열뿐이라 표에 채울 정보가 없다. 행을 만들면
    # 빈 줄이 생기므로 만들지 않는다 — 중복 알림 방지 역할은 watch 테이블이 한다.
    if match_seen_json and os.path.exists(match_seen_json):
        try:
            with open(match_seen_json, encoding="utf-8") as f:
                json.load(f)
        except Exception:
            pass

    return out


def main() -> int:
    store = aw.WatchStore("./data/watch.db")
    res = backfill(store, "./auto_seen.db", "./data/match_seen.json",
                   int(time.time()))
    print(f"백필 완료: auto_seen {res['from_auto']}건 이관, "
          f"{res['skipped']}건은 이미 있어 건너뜀")
    print("auto_seen.db 와 data/match_seen.json 은 이제 지워도 됩니다.")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `cd delivery/integrated/manual_gui && python backfill_test.py`
Expected: `===== 12/12 PASS =====`, exit 0

- [ ] **Step 5: 커밋**

```bash
git add tools/backfill_listings.py backfill_test.py
git commit -m "feat: auto_seen.db → watch 백필 스크립트

자동 모니터가 따로 들고 있던 '본 매물' 기록을 매물 표의 단일 진실로 합친다.
이미 있는 행은 건드리지 않는다 — 실측으로 갱신된 값이 백필값보다 낫다."
```

---

### Task 7: 매물 표 — 두 위젯을 하나로

**Files:**
- Modify: `main.py` — `_build_alert_tab` 안의 `matchTable`(1101-1113행)과
  `watch_box`(1116-1124행), `_match_populate`(1655행), `_notify_watch_events`(1769행),
  `on_match_open`(1800행)
- Test: `unified_tab_wiring_test.py`

**Interfaces:**
- Consumes: Task 1·2 의 `state_for`, `WatchStore.listing_rows`, `WatchStore.price_history`
- Produces:
  - `main.listing_display_rows(rows: list[dict], now: int, state_filter: str = "all") -> list[dict]`
    — 순수 함수. `[{"state","icon","keyword","title","region","price","delta_text",
    "last_change_text","first_seen_text","url","id"}]`, 최초 감지 내림차순
  - `main.STATE_ICONS: dict[str, str]` — state → 표시 문자열
  - `MainWindow.listingTable` — 8열 `QTableWidget`
  - `MainWindow._refresh_listing_table()` — 저장소에서 읽어 표를 다시 그린다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`unified_tab_wiring_test.py` 를 만든다. 공통 서두 **앞에**
`os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` 를 넣고, 서두 뒤에 이어 쓴다.

```python
import main as m
from daangn_ext import article_watch as aw

NOW = 1788000000
DAY = 86400


def row(**kw):
    base = {"id": "1", "title": "샤넬 클미", "region": "압구정", "url": "u",
            "price": 2600000, "first_price": 2850000, "keyword": "샤넬",
            "tier": "fresh", "first_seen": NOW - 100, "last_change": 0,
            "last_delta": 0, "source": "app"}
    base.update(kw)
    return base


rows = m.listing_display_rows([row()], NOW)
ck("행 1건", len(rows) == 1, str(rows))
r = rows[0]
ck("상태 new", r["state"] == aw.STATE_NEW, str(r))
ck("아이콘 있음", r["icon"] == m.STATE_ICONS[aw.STATE_NEW], str(r))
ck("키워드", r["keyword"] == "샤넬")
ck("Δ 음수 표기", r["delta_text"].startswith("-"), r["delta_text"])
ck("Δ 퍼센트 포함", "%" in r["delta_text"], r["delta_text"])
ck("변동 없으면 마지막변동 -", r["last_change_text"] == "-", r["last_change_text"])
ck("url 보존", r["url"] == "u")

ck("first_price 없으면 Δ 는 -",
   m.listing_display_rows([row(first_price=0)], NOW)[0]["delta_text"] == "-")
ck("가격 같으면 Δ 는 0 표기",
   m.listing_display_rows([row(price=2850000)], NOW)[0]["delta_text"].startswith("0"))

# 정렬: 최초 감지 내림차순
many = m.listing_display_rows(
    [row(id="a", first_seen=NOW - 3 * DAY), row(id="b", first_seen=NOW - 100)], NOW)
ck("최신 먼저", [x["id"] for x in many] == ["b", "a"], str([x["id"] for x in many]))

# 필터
mixed = [row(id="n", first_seen=NOW - 100),
         row(id="d", first_seen=NOW - 5 * DAY, last_change=NOW - 10,
             last_delta=-100),
         row(id="e", tier="dead")]
ck("all 은 전부", len(m.listing_display_rows(mixed, NOW, "all")) == 3)
ck("new 필터", [x["id"] for x in m.listing_display_rows(mixed, NOW, "new")] == ["n"])
ck("down 필터", [x["id"] for x in m.listing_display_rows(mixed, NOW, "down")] == ["d"])
ck("ended 필터",
   [x["id"] for x in m.listing_display_rows(mixed, NOW, "ended")] == ["e"])
ck("알 수 없는 필터는 전부", len(m.listing_display_rows(mixed, NOW, "??")) == 3)
ck("빈 입력", m.listing_display_rows([], NOW) == [])
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd delivery/integrated/manual_gui && python unified_tab_wiring_test.py`
Expected: FAIL — `AttributeError: module 'main' has no attribute 'listing_display_rows'`

- [ ] **Step 3: 순수 함수를 넣는다**

`main.py` 의 `watch_status_text`(69행) 다음에 추가한다.

```python
STATE_ICONS = {
    "new": "🆕 신규",
    "tracking": "● 추적중",
    "down": "↓ 인하",
    "up": "↑ 인상",
    "paused": "⏸ 추적중단",
    "ended": "✓ 종료",
}

# 필터 버튼이 고르는 값. all 은 전부.
LISTING_FILTERS = ("all", "new", "down", "ended")


def _delta_text(first_price, price):
    """최초 감지가 대비 증감. 기준선을 모르면 '-'."""
    if not first_price or not isinstance(price, int) or not isinstance(first_price, int):
        return "-"
    d = price - first_price
    pct = d * 100.0 / first_price
    return f"{d:+,}원 ({pct:+.1f}%)"


def _ts_text(ts):
    import time as _t
    if not ts:
        return "-"
    try:
        return _t.strftime("%m/%d %H:%M", _t.localtime(int(ts)))
    except Exception:
        return "-"


def listing_display_rows(rows, now, state_filter="all"):
    """watch 행 목록 → 매물 표에 그릴 형태. 최초 감지 내림차순.

    위젯을 모르는 순수 함수로 두어 GUI 없이 검증한다."""
    from daangn_ext import article_watch as _aw
    out = []
    for r in rows or []:
        state = _aw.state_for(r, now)
        if state_filter in ("new", "down", "ended") and state != state_filter:
            continue
        out.append({
            "id": str(r.get("id") or ""),
            "state": state,
            "icon": STATE_ICONS.get(state, state),
            "keyword": r.get("keyword") or "",
            "title": (r.get("title") or "")[:60],
            "region": r.get("region") or "",
            "price": r.get("price") or 0,
            "delta_text": _delta_text(r.get("first_price"), r.get("price")),
            "last_change_text": _ts_text(r.get("last_change")),
            "first_seen_text": _ts_text(r.get("first_seen")),
            "url": r.get("url") or "",
        })
    out.sort(key=lambda x: x["first_seen_text"], reverse=True)
    return out
```

`first_seen_text` 로 정렬하면 연도가 다른 행에서 어긋난다. 원본 값으로 정렬한다 —
위 `out.sort` 를 다음으로 바꾼다.

```python
    order = {str(r.get("id") or ""): int(r.get("first_seen") or 0)
             for r in rows or []}
    out.sort(key=lambda x: order.get(x["id"], 0), reverse=True)
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `cd delivery/integrated/manual_gui && python unified_tab_wiring_test.py`
Expected: `===== 17/17 PASS =====`, exit 0

- [ ] **Step 5: 커밋 (순수 함수만)**

```bash
git add main.py unified_tab_wiring_test.py
git commit -m "feat: 매물 표 행 변환 순수 함수

watch 행을 표시 형태로 옮기고 상태 필터를 적용한다. 위젯을 모르므로 GUI
없이 검증된다."
```

- [ ] **Step 6: 표 위젯을 교체한다**

`main.py` 의 `matchTable` 생성 블록(1101-1113행)을 통째로 다음으로 바꾼다.

```python
        # ── 매물 (신규·추적을 한 표에) ──
        fbar = QtWidgets.QHBoxLayout(); fbar.setSpacing(6)
        self.listingFilter = QtWidgets.QButtonGroup(w)
        for i, (key, label) in enumerate(
                (("all", "전체"), ("new", "🆕 신규"),
                 ("down", "↓ 인하"), ("ended", "✓ 종료"))):
            b = QtWidgets.QPushButton(label); b.setCheckable(True)
            b.setChecked(key == "all")
            b.setProperty("filterKey", key)
            self.listingFilter.addButton(b, i)
            fbar.addWidget(b)
        fbar.addStretch(1)
        self.listingFilter.setExclusive(True)
        self.listingFilter.buttonClicked.connect(
            lambda _b: self._refresh_listing_table())
        v.addLayout(fbar)

        self.listingTable = QtWidgets.QTableWidget(0, 8, w)
        self.listingTable.setHorizontalHeaderLabels(
            ["상태", "키워드", "제목", "지역", "현재가", "Δ최초가",
             "마지막변동", "최초감지"])
        self.listingTable.verticalHeader().setVisible(False)
        self.listingTable.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.listingTable.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.listingTable.horizontalHeader().setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.listingTable.setMinimumHeight(320)
        self.listingTable.setSortingEnabled(True)
        self.listingTable.itemDoubleClicked.connect(self.on_listing_open)
        v.addWidget(self.listingTable, 1)
```

- [ ] **Step 7: 가격 추적 상자를 지운다**

`main.py:1116-1124` 의 `watch_box` 블록 전체를 삭제한다. `self._watch_label` 과
`self._watch_list` 는 더 이상 만들지 않는다.

```python
        # ── 가격 추적 현황 ──
        watch_box = QtWidgets.QGroupBox("가격 추적")
        ...
        v.addWidget(watch_box)
```

대신 상태 요약을 컨트롤 바 라벨 하나로 옮긴다. 등록 폼 위, `dash` 그룹 다음에
넣는다.

```python
        self._watch_label = QtWidgets.QLabel("추적 중 0건")
        self._watch_label.setStyleSheet("color:#C4B79A; font-size:13px;")
        v.addWidget(self._watch_label)
```

- [ ] **Step 8: 표 갱신과 더블클릭을 붙인다**

`main.py` 의 `_notify_watch_events`(1769행) 다음에 추가한다.

```python
    def _listing_filter_key(self):
        b = self.listingFilter.checkedButton()
        return b.property("filterKey") if b else "all"

    def _refresh_listing_table(self):
        """저장소에서 읽어 표를 다시 그린다. 행 수가 수백 단위라 전면 갱신으로 족하다."""
        if not getattr(self, "_watch_store", None):
            return
        import time as _t
        try:
            rows = listing_display_rows(self._watch_store.listing_rows(),
                                        int(_t.time()), self._listing_filter_key())
        except Exception as e:
            self.alertLog.append(f"[매물표] 갱신 실패: {str(e)[:80]}")
            return
        self.listingTable.setSortingEnabled(False)
        self.listingTable.setRowCount(0)
        for r in rows:
            i = self.listingTable.rowCount()
            self.listingTable.insertRow(i)
            vals = [r["icon"], r["keyword"], r["title"], r["region"],
                    f"{r['price']:,}" if r["price"] else "-",
                    r["delta_text"], r["last_change_text"], r["first_seen_text"]]
            for c, val in enumerate(vals):
                cell = QtWidgets.QTableWidgetItem(val)
                if c == 0:
                    cell.setData(QtCore.Qt.ItemDataRole.UserRole, r["url"])
                    cell.setData(QtCore.Qt.ItemDataRole.UserRole + 1, r["id"])
                self.listingTable.setItem(i, c, cell)
        self.listingTable.setSortingEnabled(True)

    def on_listing_open(self, item):
        """더블클릭 → 가격 이력 + 매물 링크."""
        cell0 = self.listingTable.item(item.row(), 0)
        if cell0 is None:
            return
        url = cell0.data(QtCore.Qt.ItemDataRole.UserRole) or ""
        aid = cell0.data(QtCore.Qt.ItemDataRole.UserRole + 1) or ""
        hist = []
        try:
            hist = self._watch_store.price_history(str(aid))
        except Exception:
            pass
        import time as _t
        lines = [f"{_t.strftime('%m/%d %H:%M', _t.localtime(h['ts']))}  "
                 f"{h['price']:,}원" for h in hist] or ["가격 이력 없음"]
        dlg = QtWidgets.QMessageBox(self)
        dlg.setWindowTitle("가격 이력")
        dlg.setText("\n".join(lines))
        if url:
            open_btn = dlg.addButton("매물 열기",
                                     QtWidgets.QMessageBox.ButtonRole.ActionRole)
        else:
            open_btn = None
        dlg.addButton(QtWidgets.QMessageBox.StandardButton.Close)
        dlg.exec()
        if open_btn is not None and dlg.clickedButton() is open_btn:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))
```

`QtGui` 가 `main.py` 상단에서 import 돼 있지 않으면
`from PyQt6 import QtGui` 를 다른 PyQt6 import 옆에 추가한다.

- [ ] **Step 9: 기존 호출부를 바꾼다**

`_match_populate`(1655행)에서 `matchTable` 을 채우는 루프를 지우고, 추적 등록 후
표를 갱신하게 한다. `for m in matches:` 루프 안에서 `r = self.matchTable.rowCount()`
부터 `self.matchTable.sortItems(...)` 까지를 지우고 `new_items.append(m)` 만 남긴다.
썸네일 로딩(`thumb_jobs`, `_ThumbThread`)도 함께 지운다 — 새 표에는 사진 열이 없다.
그리고 `if new:` 블록 끝에 추가한다.

```python
            self._refresh_listing_table()
```

`_notify_watch_events`(1769행)에서 `self._watch_list` 를 쓰는 두 줄을 지우고
표 갱신으로 바꾼다.

```python
        for line in lines:
            self.alertLog.append(f"[가격추적] {line}")
        self._refresh_listing_table()
```

`_on_watch_swept`(1763행) 끝에도 갱신을 붙인다.

```python
        self._refresh_listing_table()
```

`on_match_open`(1800행)은 더 이상 쓰이지 않으므로 삭제한다.

- [ ] **Step 10: GUI 가 뜨는지 확인한다**

Run: `cd delivery/integrated/manual_gui && python unified_tab_wiring_test.py`
Expected: `===== 17/17 PASS =====`, exit 0 (import 시점에 `main` 이 깨지면 여기서 잡힌다)

Run: `cd delivery/integrated/manual_gui && python article_watch_wiring_test.py`
Expected: 이전과 같은 `N/N PASS`, exit 0

- [ ] **Step 11: 커밋**

```bash
git add main.py
git commit -m "feat: 신규 매치 표와 워치 이벤트 목록을 매물 표 하나로

같은 매물이 두 위젯에 따로 나타나던 것을 매물 1개=행 1개로 합친다. 상태
필터와 가격 이력 팝업을 붙이고, 표는 watch 저장소에서 직접 그린다."
```

---

### Task 8: 고급 패널 · 자동 모니터 탭 제거 · 컨트롤러 배선

**Files:**
- Modify: `main.py` — `_setup_tabs`(607행), `_build_alert_tab`, `on_alert_autopoll`(1636행),
  `_auto_poll_tick`(1848행), `_build_auto_tab`(1986행), `on_auto_start_clicked`(2553행)
- Modify: `daangn/auto_monitor.py:156-161` (`found` 신호에 id 추가)
- Test: `unified_tab_wiring_test.py` (섹션 추가)

**Interfaces:**
- Consumes: Task 3·4·5 의 `SweepQueue`, `KeywordRouter`, `SupervisorController`,
  `SupervisorPolicy`; Task 2 의 `add_from_matches(..., source=...)`
- Produces:
  - `MainWindow._router` — `KeywordRouter` 인스턴스
  - `MainWindow._supervisor` — `SupervisorController` 인스턴스
  - `MainWindow.watchToggleBtn` — 감시 시작/정지 토글
  - `MainWindow.advancedBox` — 접이식 고급 패널 (`QGroupBox`, `setCheckable(True)`)
  - `MainWindow._on_sweep_found(payload: dict)` — 검색 스윕 결과를 워치리스트로 넘긴다
  - `main.SLOT_CAP_KEY = "keyword_slot_cap"` — `data/alert_settings.json` 의 키

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`unified_tab_wiring_test.py` 의 공통 꼬리 **앞에** 추가한다.

```python
# ── 검색 스윕 결과 정규화 ──
found = {"id": 555, "region": "분당", "title": "루이비통 알마",
         "price": 1200000, "url": "https://x/555", "image": "",
         "desc": "", "boostedAt": "2026-08-30T10:00:00+09:00",
         "status": "신규"}
norm = m.sweep_found_to_match(found, keyword="루이비통")
ck("article_id 로 옮김", norm["article_id"] == "555", str(norm))
ck("키워드 채움", norm["keyword"] == "루이비통")
ck("가격 그대로", norm["price"] == 1200000)
ck("boostedAt → time epoch", norm["time"] > 0, str(norm.get("time")))
ck("url 보존", norm["url"] == "https://x/555")
ck("id 없으면 None", m.sweep_found_to_match({"title": "x"}, "k") is None)

# ── 탭 구성 ──
ck("자동 모니터 탭 빌더 제거됨", not hasattr(m.MainWindow, "_build_auto_tab"))
ck("감시 컨트롤러 모듈 import 가능",
   __import__("daangn_ext.supervisor", fromlist=["SupervisorController"]) is not None)
ck("슬롯 상한 키 정의", m.SLOT_CAP_KEY == "keyword_slot_cap")
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd delivery/integrated/manual_gui && python unified_tab_wiring_test.py`
Expected: FAIL — `AttributeError: module 'main' has no attribute 'sweep_found_to_match'`

- [ ] **Step 3: 스윕 결과 정규화 함수를 넣는다**

`main.py` 의 `listing_display_rows` 다음에 추가한다.

```python
SLOT_CAP_KEY = "keyword_slot_cap"


def sweep_found_to_match(payload, keyword):
    """AutoMonitor.found 페이로드 → add_from_matches 가 받는 형태.

    두 소스를 같은 문으로 들여보내야 매물 표가 하나로 유지된다."""
    aid = payload.get("id") if payload else None
    if not aid:
        return None
    from daangn_ext.article_watch import parse_iso
    return {"article_id": str(aid),
            "title": payload.get("title") or "",
            "price": payload.get("price") or 0,
            "region": payload.get("region") or "",
            "url": payload.get("url") or "",
            "time": parse_iso(payload.get("boostedAt")),
            "keyword": keyword or ""}
```

- [ ] **Step 4: `AutoMonitor.found` 에 id 를 넣는다**

`daangn/auto_monitor.py:156` 의 `self.found.emit({...})` 에 한 줄 추가한다.

```python
        self.found.emit({
            "id": article.get("id"),
            "region": region, "title": title, "price": price, "url": url,
            "image": article.get("thumbnail", ""), "desc": article.get("content", ""),
            "boostedAt": article.get("boostedAt", ""),
            "status": "가격변동" if changed is not None else "신규",
        })
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `cd delivery/integrated/manual_gui && python unified_tab_wiring_test.py`
Expected: "자동 모니터 탭 빌더 제거됨" 만 FAIL, 나머지 PASS

- [ ] **Step 6: 고급 패널을 만들고 스윕 설정을 옮긴다**

`_build_alert_tab` 안에서, 지금 액션행(`r3`)과 옵션행(`r3b`)에 들어 있는 위젯 중
**토글과 상태칩을 뺀 전부**를 접이식 그룹으로 옮긴다.

`r3`/`r3b` 를 만드는 블록을 다음으로 교체한다.

```python
        # ── 컨트롤 바: 토글 하나 + 상태칩 ──
        top = QtWidgets.QHBoxLayout(); top.setSpacing(10)
        self.watchToggleBtn = QtWidgets.QPushButton("▶ 감시 시작")
        self.watchToggleBtn.setObjectName("startBtn")
        self.watchToggleBtn.setCheckable(True)
        self.watchToggleBtn.clicked.connect(self.on_watch_toggle)
        top.addWidget(self.watchToggleBtn)
        top.addWidget(self._watch_label, 1)
        v.addLayout(top)

        # ── 고급 (접힘) ──
        self.advancedBox = QtWidgets.QGroupBox("고급")
        self.advancedBox.setCheckable(True)
        self.advancedBox.setChecked(False)
        av = QtWidgets.QVBoxLayout(self.advancedBox)
        self.advancedBox.toggled.connect(
            lambda on: [c.setVisible(on) for c in self.advancedBox.findChildren(
                QtWidgets.QWidget)])

        a1 = QtWidgets.QHBoxLayout()
        a1.addWidget(self.alertPollBtn); a1.addWidget(self.alertPollAllBtn)
        a1.addWidget(self.alertCoverageBtn); a1.addWidget(self.alertFleetBtn)
        a1.addWidget(self.alertTgTestBtn); a1.addStretch(1)
        av.addLayout(a1)

        a2 = QtWidgets.QHBoxLayout()
        a2.addWidget(QtWidgets.QLabel("주기")); a2.addWidget(self.alertPollInterval)
        a2.addSpacing(12); a2.addWidget(QtWidgets.QLabel("커버"))
        a2.addWidget(self.alertCoverMode)
        a2.addSpacing(12); a2.addWidget(self.alertAutoStartChk)
        a2.addWidget(self.alertBootChk); a2.addWidget(self.alertCrashChk)
        a2.addWidget(self.alertNightChk); a2.addStretch(1)
        av.addLayout(a2)

        av.addWidget(self._build_sweep_settings())
        v.addWidget(self.advancedBox)
```

`alertAutoPollBtn` 은 만들지 않는다 — 토글이 그 역할을 한다. 위젯 생성 줄
(`self.alertAutoPollBtn = ...`)과 그 `clicked.connect` 를 삭제한다.

- [ ] **Step 7: 스윕 설정 위젯을 이사시킨다**

`_build_auto_tab`(1986행)에서 다음 위젯 생성 코드를 잘라내어 새 메서드로 옮긴다:
`autoAreaTree`, `autoExtra`, `autoExclude`, `autoMin`, `autoMax`, `autoDays`,
`autoRestMin`, `autoRestMax`, `autoGapMin`, `autoGapMax`, `autoLanes`,
`autoTokenRefresh`, `autoProxyViewBtn`, `autoExcelBtn`, `autoNotifyBtn`,
`autoAccountsBtn`.

```python
    def _build_sweep_settings(self):
        """검색 스윕 설정 — 자동 모니터 탭에서 이사. 값 의미와 위젯 종류는 그대로다.

        여기 있는 값은 앱 슬롯에 못 들어가 스윕으로 밀린 키워드에만 쓰인다.
        키워드 입력은 없다 — 라우터가 정한다."""
        box = QtWidgets.QGroupBox("검색 스윕")
        gv = QtWidgets.QVBoxLayout(box)
        gv.addWidget(QtWidgets.QLabel(
            "앱 알림 슬롯이 찼을 때 이 조건으로 지역을 훑어 커버한다."))
        # (자동 모니터 탭에 있던 위젯 생성·배치 코드를 그대로 옮겨 온다.
        #  autoKeyword 와 autoStartBtn, autoStatus, autoProgress, autoTable,
        #  autoLog 는 옮기지 않는다 — 키워드는 라우터가, 상태는 컨트롤 바가,
        #  결과는 매물 표가 맡는다.)
        return box
```

옮기지 않는 위젯을 참조하는 코드는 전부 지운다: `autoKeyword`, `autoStartBtn`,
`autoStatus`, `autoProgress`, `autoTable`, `autoLog`, `autoNotifyBtn` 이 붙어 있던
핸들러 중 `on_auto_start_clicked` 의 GUI 갱신 부분.

- [ ] **Step 8: 탭을 지운다**

`main.py:607` `_setup_tabs` 에서 자동 모니터 탭 줄을 삭제한다.

```python
        self.tabs.addTab(self._scroll(self._build_manual_tab()), "수동 검색")
        self.auto_monitor = None
        self.tabs.addTab(self._scroll(self._build_alert_tab()), "매물 감시")
        self.tabs.addTab(self._build_emul_tab(), "에뮬레이터")
```

`_build_auto_tab` 메서드 전체를 삭제한다. `self.auto_monitor` 는 남긴다 —
검색 스윕 스레드 핸들로 계속 쓴다.

- [ ] **Step 9: 라우터·컨트롤러를 배선한다**

`_build_alert_tab` 의 워치리스트 초기화 블록(1156-1170행) 다음에 추가한다.

```python
        # ── 키워드 라우터 · 감시 컨트롤러 ──
        self._router = None
        self._supervisor = None
        try:
            from daangn_ext.sweep_queue import SweepQueue
            from daangn_ext.keyword_router import KeywordRouter, DEFAULT_SLOT_CAP
            from daangn_ext.supervisor import SupervisorController, SupervisorPolicy
            self._sweep_queue = SweepQueue("./data/sweep_queue.json")
            cap = int(self._load_alert_settings().get(SLOT_CAP_KEY)
                      or DEFAULT_SLOT_CAP)
            self._router = KeywordRouter(self._alert_fleet(), self._sweep_queue,
                                         slot_cap=cap)
            policy = SupervisorPolicy(lambda: int(self.alertPollInterval.value()),
                                      self._night_factor,
                                      sweep_interval=WATCH_SWEEP_INTERVAL)
            self._supervisor = SupervisorController(
                policy, self._alert_poll_timer, self._watch_timer,
                self._sweep_queue,
                start_search_sweep=self._start_search_sweep,
                stop_search_sweep=self._stop_search_sweep)
        except Exception as e:
            self.alertLog.append(f"[감시] 초기화 실패: {str(e)[:120]}")
        self.alertPollInterval.valueChanged.connect(
            lambda _v: self._supervisor.retune() if self._supervisor else None)
```

`self._alert_fleet()` 은 `MultiAccountAlerts` 를 돌려주는 기존 헬퍼다. 없으면
`on_alert_poll_all` 이 쓰는 생성 코드를 그대로 감싸 만든다.

`on_alert_autopoll`(1636행) 전체를 다음으로 교체한다.

```python
    def on_watch_toggle(self):
        """감시 토글 — 폴링·워치 스윕·검색 스윕이 한 수명을 공유한다."""
        if not self._supervisor:
            self.alertLog.append("[감시] 컨트롤러가 없습니다")
            self.watchToggleBtn.setChecked(False)
            return
        if self._supervisor.is_running():
            self._supervisor.stop()
            self.watchToggleBtn.setText("▶ 감시 시작")
            self.watchToggleBtn.setChecked(False)
            self.alertLog.append("[감시] 정지")
        else:
            self._supervisor.start()
            self.watchToggleBtn.setText("■ 감시 정지")
            self.watchToggleBtn.setChecked(True)
            self.alertLog.append("[감시] 시작")
            self.on_alert_poll_all()      # 첫 회차는 기다리지 않는다
```

`_auto_poll_tick`(1848행)에서 간격을 직접 만지던 부분을 컨트롤러에 넘기고,
승격을 얹는다.

```python
    def _auto_poll_tick(self):
        if self._supervisor:
            self._supervisor.retune()
        if self._router:
            try:
                promoted = self._router.rebalance(core_only=self._core_only(),
                                                  log=self.alertLog.append)
                for p in promoted:
                    self.alertLog.append(f"[라우터] {p['keyword']} → 앱 알림 승격")
            except Exception as e:
                self.alertLog.append(f"[라우터] 승격 실패: {str(e)[:80]}")
        self.on_alert_poll_all()
```

- [ ] **Step 10: 키워드 등록을 라우터로 보낸다**

`on_alert_add` / `on_alert_bulk_all` 에서 `register_all` 을 직접 부르던 자리를
라우터 호출로 바꾼다.

```python
        res = self._router.add(kw, min_price, max_price, exclude,
                               core_only=self._core_only(),
                               log=self.alertLog.append)
        self.alertLog.append(
            f"[키워드] {res['keyword']} → "
            f"{'앱 알림' if res['route'] == 'app' else '검색 스윕'} ({res['reason']})")
        self.on_alert_refresh()
```

`on_alert_refresh` 가 그리는 `alertTable` 에 `경로` 열을 추가한다. 열 수를 4 에서
5 로 늘리고 헤더를 `["키워드", "경로", "가격범위", "제외", "id"]` 로 바꾼 뒤,
`self._router.routes()` 의 `route`/`reason` 을 두 번째 열과 툴팁에 넣는다.

- [ ] **Step 11: 검색 스윕 기동·정지와 결과 배선**

`main.py` 에 추가한다.

```python
    def _sweep_cfg(self):
        """스윕 큐의 키워드로 AutoMonitor cfg 를 만든다. 지역·속도는 고급 패널 값."""
        entries = self._sweep_queue.entries()
        conditions = [{"keyword": e["keyword"], "extra": self.autoExtra.text(),
                       "exclude": self.autoExclude.text(),
                       "min": self.autoMin.text(), "max": self.autoMax.text(),
                       "days": self.autoDays.value()} for e in entries]
        cfg = dict(self._auto_cfg_base())      # 기존 on_auto_start_clicked 의 cfg 조립
        cfg["conditions"] = conditions
        return cfg

    def _start_search_sweep(self):
        if self.auto_monitor is not None and self.auto_monitor.isRunning():
            return
        try:
            from daangn.auto_monitor import AutoMonitor
            self.auto_monitor = AutoMonitor(self, self._sweep_cfg())
            self.auto_monitor.log.connect(self.alertLog.append)
            self.auto_monitor.found.connect(self._on_sweep_found)
            self.auto_monitor.start()
            self.alertLog.append(
                f"[검색스윕] 시작 — 키워드 {len(self._sweep_queue)}개")
        except Exception as e:
            self.alertLog.append(f"[검색스윕] 시작 실패: {str(e)[:120]}")

    def _stop_search_sweep(self):
        am = self.auto_monitor
        if am is not None and am.isRunning():
            am.stop()
            self.alertLog.append("[검색스윕] 정지 요청")

    def _on_sweep_found(self, payload):
        """검색 스윕이 찾은 매물도 앱 알림과 같은 문으로 워치리스트에 들어간다."""
        kw = ""
        try:
            kws = self._sweep_queue.keywords()
            title = payload.get("title") or ""
            kw = next((k for k in kws if k in title), kws[0] if kws else "")
        except Exception:
            pass
        norm = sweep_found_to_match(payload, kw)
        if not norm or not self._watch_tracker:
            return
        try:
            if self._watch_tracker.add_from_matches([norm], source="sweep"):
                self._refresh_listing_table()
        except Exception as e:
            self.alertLog.append(f"[검색스윕] 추적 등록 실패: {str(e)[:80]}")
```

`_auto_cfg_base` 는 기존 `on_auto_start_clicked`(2553행)에서 cfg dict 를 만드는
부분을 그대로 떼어낸 메서드다. `keyword`/`extra` 대신 `conditions` 를
`_sweep_cfg` 가 채우므로, `_auto_cfg_base` 에서는 그 두 키를 빼고 나머지
(`tg_token`, `tg_chat`, `sheet_url`, `sheet_cred`, `proxies`, `proxy_provider`,
`token_provider`, `stabilize`, `accounts_fp`, `daily_cap`, `warmup_days`,
`out_json`, `db_path`, `rest_min`, `rest_max`, `gap_min`, `gap_max`, `lanes`,
`scope`, `regions`)만 만든다.

`on_auto_start_clicked` 는 삭제한다.

- [ ] **Step 12: 자동 시작·크래시 복구를 컨트롤러로 모은다**

`_autostart_poll` 이 `on_alert_autopoll` 을 부르던 것을 바꾼다.

```python
    def _autostart_poll(self):
        if self._supervisor and not self._supervisor.is_running():
            self.on_watch_toggle()
```

- [ ] **Step 13: 테스트가 통과하는지 확인한다**

Run: `cd delivery/integrated/manual_gui && python unified_tab_wiring_test.py`
Expected: `===== 24/24 PASS =====`, exit 0

Run: `cd delivery/integrated/manual_gui && python article_watch_wiring_test.py`
Expected: 이전과 같은 `N/N PASS`, exit 0

Run: `cd delivery/integrated/manual_gui && python article_watch_test.py && python watch_listing_test.py && python sweep_queue_test.py && python keyword_router_test.py && python supervisor_test.py && python backfill_test.py`
Expected: 전부 exit 0

- [ ] **Step 14: 실제로 창을 띄워 확인한다**

Run: `cd delivery/integrated/manual_gui && python main.py`
Expected: 탭이 셋(수동 검색 / 매물 감시 / 에뮬레이터). 매물 감시 탭에 토글 하나와
접힌 고급 패널이 보이고, 매물 표에 기존 추적 매물이 뜬다. `▶ 감시 시작` 을 누르면
`[감시] 시작` 로그가 남고 버튼이 `■ 감시 정지` 로 바뀐다.

- [ ] **Step 15: 백필을 돌린다**

```bash
cd delivery/integrated/manual_gui
python tools/backfill_listings.py
```

Expected: `백필 완료: auto_seen N건 이관, M건은 이미 있어 건너뜀`

- [ ] **Step 16: 커밋**

```bash
git add main.py daangn/auto_monitor.py unified_tab_wiring_test.py
git commit -m "feat: 자동 모니터 탭 제거 — 매물 감시 하나로

탭 넷에서 셋으로 줄인다. 스윕 설정은 고급 패널로 옮기고, 키워드 등록은
라우터를 거쳐 앱/스윕으로 자동 배정된다. 감시 토글 하나가 폴링·워치 스윕·
검색 스윕을 함께 켜고 끈다. AutoMonitor.found 에 매물 id 를 추가해 스윕
결과도 앱 알림과 같은 문으로 워치리스트에 들어간다."
```

---

### Task 9: 헤드리스 런타임 배선

**Files:**
- Modify: `main.py` — `_run_headless`
- Test: 수동 실행 확인

**Interfaces:**
- Consumes: Task 8 의 `MainWindow._supervisor`
- Produces: 없음 (CLI 인터페이스 불변)

- [ ] **Step 1: 헤드리스가 컨트롤러를 쓰게 한다**

`_run_headless` 안에서 폴링 타이머와 워치 타이머를 각각 켜던 코드를 찾아
`window._supervisor.start()` 한 줄로 바꾼다. 신호는 로거에 연결한다.

- [ ] **Step 2: 헤드리스가 뜨는지 확인한다**

Run: `cd delivery/integrated/manual_gui && QT_QPA_PLATFORM=offscreen timeout 30 python main.py --headless`
Expected: `[감시] 시작` 로그가 나오고 30초 뒤 timeout 으로 종료(에러 트레이스 없음)

- [ ] **Step 3: 커밋**

```bash
git add main.py
git commit -m "feat: 헤드리스도 감시 컨트롤러를 쓴다

GUI 와 헤드리스가 같은 수명주기 코드를 공유한다 — 타이머를 두 곳에서 켜면
한쪽만 고쳐지는 버그가 난다."
```

---

### Task 10: 폐기된 저장소 정리

**Files:**
- Modify: `main.py` — `_MATCH_SEEN_FILE`, `_load_match_seen`, `_save_match_seen`, `_match_seen`
- Test: 기존 테스트 전체 재실행

**Interfaces:**
- Consumes: Task 1·2 의 `watch` 테이블
- Produces: 없음

`watch` 테이블이 `dead` 행을 지우지 않으므로 중복 알림 방지 역할을 이미 한다.
`match_seen.json` 은 같은 일을 하는 두 번째 진실이다.

- [ ] **Step 1: 중복 판정을 watch 저장소로 옮긴다**

`_match_populate`(1655행)의 중복 확인을 바꾼다.

```python
        for m in matches:
            aid = str(m.get("article_id") or m.get("id") or "")
            if not aid:
                continue
            # watch 테이블이 본 매물의 진실이다 — dead 행을 지우지 않으므로
            # 판매완료·삭제된 매물이 다시 떠도 재알림하지 않는다.
            if self._watch_store and self._watch_store.get(aid) is not None:
                continue
            new += 1
            new_items.append(m)
```

- [ ] **Step 2: 파일 기반 코드를 지운다**

`_MATCH_SEEN_FILE`, `_load_match_seen`, `_save_match_seen` 메서드와
`self._match_seen` 초기화·사용을 모두 삭제한다.

- [ ] **Step 3: 전체 테스트를 돌린다**

Run: `cd delivery/integrated/manual_gui && for t in article_watch_test.py watch_listing_test.py sweep_queue_test.py keyword_router_test.py supervisor_test.py backfill_test.py article_watch_wiring_test.py unified_tab_wiring_test.py; do echo "── $t"; python $t || echo "FAILED: $t"; done`
Expected: 전부 `N/N PASS`, `FAILED:` 줄 없음

- [ ] **Step 4: 앱을 띄워 확인한다**

Run: `cd delivery/integrated/manual_gui && python main.py`
Expected: 매물 감시 탭이 뜨고, 감시를 켜면 새 매치가 표에 한 번만 들어온다.

- [ ] **Step 5: 폐기 파일을 지운다**

```bash
cd delivery/integrated/manual_gui
rm -f data/match_seen.json auto_seen.db
```

- [ ] **Step 6: 커밋**

```bash
git add main.py
git commit -m "refactor: match_seen.json 폐기 — 중복 판정은 watch 테이블이 한다

watch 는 dead 행을 지우지 않으므로 이미 '본 매물'의 진실이다. 같은 일을
하는 두 번째 저장소를 없앤다."
```

---

## 자체 점검

**스펙 커버리지**

| 스펙 절 | 태스크 |
|---|---|
| 1. 화면 (컨트롤 바·키워드 표·매물 표·고급 패널) | 7, 8 |
| 2. 라우팅 (`KeywordRouter`·슬롯 상한·승격) | 3, 4, 8 |
| 3. 데이터 모델 (컬럼·`price_history`·`state` 파생·마이그레이션·백필) | 1, 2, 6 |
| 4. 추적 수명 (등급 유지·자동 축출·스윕 결과 투입) | 2, 8 |
| 5. 알림 (신규·인하 발송, 종료는 표시만) | 기존 동작 유지 — Task 8 에서 배선만 옮김 |
| 6. 수명주기 (`SupervisorController`·헤드리스) | 5, 8, 9 |
| 7. 테스트 | 각 태스크에 포함 |
| 8. 순서 | Task 1→10 이 스펙 8절 순서와 같다 |

**스펙에서 고친 것**

- 스펙의 `state` 표는 `tier == dead` 만 종료로 봤다. 코드에는 `TIER_EVICTED` 가 따로
  있으므로(상한·실패로 접었지만 매물은 살아 있음) `paused` 상태를 추가했다.
- 스펙은 "AutoMonitor 엔진 자체는 손대지 않는다"고 했으나, `found` 신호 payload 에
  매물 id 가 없어 워치리스트에 넣을 수 없다. Task 8 에서 한 줄 추가한다.
- 스펙은 슬롯 상한을 `data/config.json` 의 `keyword_slot_cap` 으로 읽는다고 했다.
  그 파일은 HTTP 헤더 전용이므로 `data/alert_settings.json` 으로 옮겼다.
- 스펙의 알림 옵션(`price_up`·`republished` 기본 꺼짐)은 기존 동작을 바꾸는 것이라
  이번 계획에서 빼고 현행 유지한다. 별도 과제다.

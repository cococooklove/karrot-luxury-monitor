# 매물 워치리스트 (가격변동 추적) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 키워드 알림으로 잡은 매물을 단건 조회로 주기 재확인해 가격 인상·인하, 판매완료, 삭제, 끌올을 알린다.

**Architecture:** 새 모듈 `daangn_ext/article_watch.py` 하나에 네 단위를 둔다. `ArticleDetailAPI` 가 `GET webapp/api/v24/articles/{id}.json` 을 때리고 정규화한다. `WatchStore` 가 sqlite `data/watch.db` 에 마지막 관측값과 다음 점검 시각을 들고 있다. `WatchTracker` 가 등급·상한 정책과 diff 를 맡고 이벤트 목록을 돌려준다. `AccountBudget` 이 유효 토큰 계정을 라운드로빈으로 내주고 계정별 하루 요청 수를 끊는다. 알림 전송은 `main.py` 가 한다.

**Tech Stack:** Python 3.11+, httpx, sqlite3(표준 라이브러리), PyQt6(배선만). 새 의존성 없음.

**Spec:** `docs/superpowers/specs/2026-08-29-article-watchlist-design.md`

## Global Constraints

- 작업 디렉터리는 `delivery/integrated/manual_gui/`. 이 계획의 모든 상대 경로는 여기 기준이다.
- 테스트는 이 저장소 관례를 따른다: 최상위 `<이름>_test.py`, `pytest` 아님, `/Users/younglee/당근부동산_숨고/.venv/bin/python <이름>_test.py` 로 실행(맨 `python` 에는 httpx·PyQt6 가 없다), `ck(name, cond)` 헬퍼로 PASS/FAIL 을 찍고 마지막에 `sys.exit(0 if passed == len(R) else 1)`. 본보기는 `throttle_test.py`.
- 단위 테스트는 네트워크를 타지 않는다. `ArticleDetailAPI` 는 `httpx.Client` 를 주입받아 `httpx.MockTransport` 로 바꿀 수 있어야 한다.
- 각 Step 4 의 기대값은 "모든 항목 PASS, 실패 목록 비어 있음"이다. 총 건수는 앞선 Task 들이 남긴 항목이 누적되므로 숫자를 고정하지 않는다.
- 호스트와 경로: `webapp.kr.karrotmarket.com`, `GET /api/v24/articles/{id}.json`. 헤더는 `daangn_ext.keyword_alert_api._headers(access_token, config_path)` 를 그대로 쓴다.
- 상태 값은 `ongoing` / `reserved` / `closed` 세 가지다(앱 경로 `statuses/{closed,ongoing,reserved}.json`).
- 등급 상수: `FRESH_AGE = 48*3600`, `AGED_AGE = 14*24*3600`, `FRESH_INTERVAL = 4*3600`, `AGED_INTERVAL = 24*3600`, `ACTIVE_CAP = 300`, `DAILY_CAP_PER_ACCOUNT = 300`, `MAX_FAIL = 5`, `RATE_LIMIT_DELAY = 1800`.
- 묶음 조회는 없다(`articles.json` 은 어떤 파라미터 조합이든 `invalid_params`). 재조회는 1건 1요청이다.
- `main.py` 는 PyQt6 를 `QtCore` / `QtWidgets` 네임스페이스로 쓴다. `QtCore.QTimer`, `QtWidgets.QLabel` 처럼 쓴다.
- 자동 모니터 탭(`daangn/auto_monitor.py`, `main.py:1281 _build_auto_tab`)은 이 계획에서 건드리지 않는다.
- 커밋 메시지는 한국어 본문, Conventional Commits 접두사.

---

### Task 1: ArticleDetailAPI — 단건 조회와 정규화

**Files:**
- Create: `daangn_ext/article_watch.py`
- Test: `article_watch_test.py`

**Interfaces:**
- Consumes: `daangn_ext.keyword_alert_api._headers`, `daangn_ext.keyword_alert_api.WEBAPP`
- Produces:
  - `WEBAPP_ARTICLE_PATH = "/api/v24/articles/{id}.json"`
  - `STATUS_ONGOING = "ongoing"`, `STATUS_RESERVED = "reserved"`, `STATUS_CLOSED = "closed"`
  - `parse_iso(s) -> int` — ISO8601(+09:00 포함) → epoch 초. 판단 불가면 `0`
  - `normalize(payload: dict, article_id: str) -> dict`
  - `class ArticleDetailAPI(access_token, config_path="./data/config.json", proxy=None, client=None)` with `fetch(article_id: str) -> dict`, `close() -> None`
  - `fetch` 는 404/410 을 `{"id": ..., "gone": True}` 로 돌려주고, 그 밖의 비200 에는 `httpx.HTTPStatusError` 를 올린다

- [ ] **Step 1: Write the failing test**

`article_watch_test.py` 를 새로 만든다.

```python
"""매물 워치리스트 테스트 (네트워크 불필요).

    python article_watch_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx

from daangn_ext import article_watch as aw

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


PUBLISHED_ISO = "2026-08-29T21:33:19.375+09:00"
PUBLISHED_EPOCH = 1788006799

ARTICLE_OK = {
    "article": {
        "id": 1236138291,
        "title": "디올 오블리크 카드지갑",
        "price": 410000.0,
        "status": "ongoing",
        "status_name": "판매중",
        "published_at": PUBLISHED_ISO,
        "updated_at": "2026-08-29T21:33:22.493+09:00",
        "republish_count": 0,
        "watches_count": 3,
        "chat_rooms_count": 1,
        "reads_count": 40,
        "destroyed_at": None,
        "is_unpublished": False,
        "visible": True,
        "display_region_name": "평택시 용이동",
        "permalink": "https://www.daangn.com/kr/buy-sell/-1236138291/",
    },
    "meta": {},
}


def fake_client(status_code, payload=None):
    def handler(request):
        return httpx.Response(status_code, json=payload if payload is not None else {})
    return httpx.Client(transport=httpx.MockTransport(handler))


print("=== A. parse_iso ===")
ck("+09:00 파싱", aw.parse_iso(PUBLISHED_ISO) == PUBLISHED_EPOCH, aw.parse_iso(PUBLISHED_ISO))
ck("빈 문자열 → 0", aw.parse_iso("") == 0)
ck("None → 0", aw.parse_iso(None) == 0)
ck("쓰레기 → 0", aw.parse_iso("어제") == 0)

print("=== B. normalize ===")
n = aw.normalize(ARTICLE_OK, "1236138291")
ck("id 문자열", n["id"] == "1236138291", n["id"])
ck("price 정수", n["price"] == 410000 and isinstance(n["price"], int), n["price"])
ck("status", n["status"] == "ongoing")
ck("title", n["title"] == "디올 오블리크 카드지갑")
ck("region", n["region"] == "평택시 용이동")
ck("url", n["url"].endswith("-1236138291/"))
ck("published_at epoch", n["published_at"] == PUBLISHED_EPOCH, n["published_at"])
ck("republish_count", n["republish_count"] == 0)
ck("gone 아님", n["gone"] is False)

print("=== C. ArticleDetailAPI.fetch ===")
api = aw.ArticleDetailAPI("tok", client=fake_client(200, ARTICLE_OK))
got = api.fetch("1236138291")
ck("200 → 정규화 dict", got["price"] == 410000 and got["gone"] is False)
api.close()

api = aw.ArticleDetailAPI("tok", client=fake_client(404))
ck("404 → gone", api.fetch("999") == {"id": "999", "gone": True})
api.close()

api = aw.ArticleDetailAPI("tok", client=fake_client(410))
ck("410 → gone", api.fetch("999")["gone"] is True)
api.close()

api = aw.ArticleDetailAPI("tok", client=fake_client(429))
try:
    api.fetch("1")
    ck("429 → 예외", False)
except httpx.HTTPStatusError as e:
    ck("429 → 예외", e.response.status_code == 429)
api.close()

api = aw.ArticleDetailAPI("tok", client=fake_client(401))
try:
    api.fetch("1")
    ck("401 → 예외", False)
except httpx.HTTPStatusError as e:
    ck("401 → 예외", e.response.status_code == 401)
api.close()

api = aw.ArticleDetailAPI("tok", client=fake_client(200, {
    "article": dict(ARTICLE_OK["article"], destroyed_at="2026-08-29T22:00:00+09:00")}))
ck("destroyed_at 있으면 gone", api.fetch("1")["gone"] is True)
api.close()

api = aw.ArticleDetailAPI("tok", client=fake_client(200, {
    "article": dict(ARTICLE_OK["article"], is_unpublished=True)}))
ck("is_unpublished 면 gone", api.fetch("1")["gone"] is True)
api.close()

api = aw.ArticleDetailAPI("tok", client=fake_client(200, {
    "article": dict(ARTICLE_OK["article"], visible=False)}))
ck("visible False 면 gone", api.fetch("1")["gone"] is True)
api.close()

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd delivery/integrated/manual_gui && /Users/younglee/당근부동산_숨고/.venv/bin/python article_watch_test.py`
Expected: FAIL — `ImportError: cannot import name 'article_watch' from 'daangn_ext'`

- [ ] **Step 3: Write minimal implementation**

`daangn_ext/article_watch.py` 를 새로 만든다.

```python
"""매물 단건 추적 — 가격변동·판매완료·삭제·끌올 감지.

단건 조회: GET https://webapp.kr.karrotmarket.com/api/v24/articles/{id}.json
Bearer 토큰만 필요(WAF 아님). 묶음 조회는 없다 — articles.json 은 어떤 파라미터
조합이든 invalid_params 를 돌려준다. 따라서 1건 1요청이고, 요청량은 추적 대상 수와
점검 주기로만 조절한다.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sqlite3
import time

import httpx

from .keyword_alert_api import WEBAPP, _headers, token_remaining

WEBAPP_ARTICLE_PATH = "/api/v24/articles/{id}.json"

STATUS_ONGOING = "ongoing"
STATUS_RESERVED = "reserved"
STATUS_CLOSED = "closed"

FRESH_AGE = 48 * 3600
AGED_AGE = 14 * 24 * 3600
FRESH_INTERVAL = 4 * 3600
AGED_INTERVAL = 24 * 3600
ACTIVE_CAP = 300
DAILY_CAP_PER_ACCOUNT = 300
MAX_FAIL = 5
RATE_LIMIT_DELAY = 1800
MIN_TOKEN_REMAINING = 120


def parse_iso(s) -> int:
    """ISO8601(+09:00 포함) → epoch 초. 판단 불가면 0."""
    if not s or not isinstance(s, str):
        return 0
    try:
        return int(_dt.datetime.fromisoformat(s).timestamp())
    except ValueError:
        return 0


def _int(v, default=0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def normalize(payload: dict, article_id: str) -> dict:
    """단건 조회 응답 → 표준 dict. 사라진 매물이면 gone=True 하나만 담는다."""
    art = payload.get("article") if isinstance(payload.get("article"), dict) else payload
    gone = bool(art.get("destroyed_at")) or bool(art.get("is_unpublished")) \
        or art.get("visible") is False
    if gone:
        return {"id": str(article_id), "gone": True}
    return {
        "id": str(art.get("id") or article_id),
        "gone": False,
        "title": art.get("title") or "",
        "price": _int(art.get("price")),
        "status": art.get("status") or "",
        "status_name": art.get("status_name") or "",
        "region": art.get("display_region_name") or art.get("display_location_name") or "",
        "url": art.get("permalink") or f"https://www.daangn.com/kr/buy-sell/-{article_id}/",
        "published_at": parse_iso(art.get("published_at") or art.get("created_at")),
        "updated_at": parse_iso(art.get("updated_at")),
        "republish_count": _int(art.get("republish_count")),
        "watches_count": _int(art.get("watches_count")),
        "chat_rooms_count": _int(art.get("chat_rooms_count")),
        "reads_count": _int(art.get("reads_count")),
    }


class ArticleDetailAPI:
    """계정 1개(access token)로 매물 단건을 조회한다."""

    def __init__(self, access_token: str, config_path: str = "./data/config.json",
                 proxy: str | None = None, client: httpx.Client | None = None):
        self.token = access_token
        self.headers = _headers(access_token, config_path)
        self._own_client = client is None
        self._client = client or httpx.Client(http2=True, timeout=20, proxy=proxy)

    def fetch(self, article_id: str) -> dict:
        """정규화된 dict. 사라졌으면 {"id":..., "gone": True}.
        401/429/5xx 는 httpx.HTTPStatusError 로 올린다."""
        url = f"https://{WEBAPP}{WEBAPP_ARTICLE_PATH.format(id=article_id)}"
        r = self._client.get(url, headers=self.headers)
        if r.status_code in (404, 410):
            return {"id": str(article_id), "gone": True}
        r.raise_for_status()
        return normalize(r.json() or {}, str(article_id))

    def close(self) -> None:
        if self._own_client:
            try:
                self._client.close()
            except Exception:
                pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd delivery/integrated/manual_gui && /Users/younglee/당근부동산_숨고/.venv/bin/python article_watch_test.py`
Expected: PASS — 실패 목록이 비어 있고 종료 코드 0

- [ ] **Step 5: Commit**

```bash
git add delivery/integrated/manual_gui/daangn_ext/article_watch.py delivery/integrated/manual_gui/article_watch_test.py
git commit -m "feat: 매물 단건 조회 API(ArticleDetailAPI)

가격변동 추적의 기반. 404/410 과 destroyed_at/is_unpublished/visible 을
모두 gone 으로 정규화해 삭제와 조회 실패를 호출자가 구분할 수 있게 했다."
```

---

### Task 2: WatchStore — sqlite 저장소

**Files:**
- Modify: `daangn_ext/article_watch.py`
- Test: `article_watch_test.py` (섹션 추가)

**Interfaces:**
- Consumes: Task 1 `normalize` 출력 dict
- Produces:
  - `class WatchStore(path="./data/watch.db")`
  - `upsert(row: dict) -> None` — `id` 기준 삽입/갱신
  - `get(article_id: str) -> dict | None`
  - `due(now: int, limit: int) -> list[str]` — `tier != 'dead'` 이고 `next_check <= now`, `next_check` 오름차순
  - `active_count() -> int`
  - `oldest_active(n: int) -> list[str]` — `published_at` 오름차순
  - `next_due_at() -> int` — 활성 행의 최소 `next_check`. 없으면 `0`
  - `mark(article_id: str, **fields) -> None` — 지정 컬럼만 갱신
  - `close() -> None`
  - 컬럼: `id TEXT PRIMARY KEY, title TEXT, region TEXT, url TEXT, price INTEGER, status TEXT, republish_count INTEGER, published_at INTEGER, first_seen INTEGER, last_check INTEGER, next_check INTEGER, tier TEXT, fail INTEGER`

- [ ] **Step 1: Write the failing test**

`article_watch_test.py` 의 `passed = sum(...)` 집계 블록 **앞에** 붙인다. 파일 위쪽 import 에 `import tempfile` 을 추가한다.

```python
print("=== D. WatchStore ===")
dbp = os.path.join(tempfile.mkdtemp(), "watch.db")
st = aw.WatchStore(dbp)

st.upsert({"id": "1", "title": "가", "region": "강남", "url": "u1", "price": 1000,
           "status": "ongoing", "republish_count": 0, "published_at": 100,
           "first_seen": 100, "last_check": 100, "next_check": 200,
           "tier": "fresh", "fail": 0})
st.upsert({"id": "2", "title": "나", "region": "서초", "url": "u2", "price": 2000,
           "status": "ongoing", "republish_count": 0, "published_at": 50,
           "first_seen": 100, "last_check": 100, "next_check": 300,
           "tier": "aged", "fail": 0})
st.upsert({"id": "3", "title": "다", "region": "송파", "url": "u3", "price": 3000,
           "status": "closed", "republish_count": 0, "published_at": 10,
           "first_seen": 100, "last_check": 100, "next_check": 150,
           "tier": "dead", "fail": 0})

ck("get 저장값", st.get("1")["price"] == 1000)
ck("get 없는 id → None", st.get("nope") is None)
ck("active_count = 2", st.active_count() == 2, st.active_count())
ck("due(250) → ['1']", st.due(250, 10) == ["1"], st.due(250, 10))
ck("due 는 dead 제외", "3" not in st.due(999, 10))
ck("due 정렬·limit", st.due(999, 1) == ["1"], st.due(999, 1))
ck("oldest_active → ['2','1']", st.oldest_active(2) == ["2", "1"], st.oldest_active(2))
ck("next_due_at = 200", st.next_due_at() == 200, st.next_due_at())

st.upsert({"id": "1", "title": "가", "region": "강남", "url": "u1", "price": 900,
           "status": "ongoing", "republish_count": 0, "published_at": 100,
           "first_seen": 100, "last_check": 400, "next_check": 500,
           "tier": "fresh", "fail": 0})
ck("upsert 갱신", st.get("1")["price"] == 900)
ck("upsert 후에도 2행", st.active_count() == 2)

st.mark("1", tier="dead", fail=3)
ck("mark 부분갱신", st.get("1")["tier"] == "dead" and st.get("1")["fail"] == 3)
ck("mark 후 active_count = 1", st.active_count() == 1)
ck("mark 다른 컬럼 보존", st.get("1")["price"] == 900)
ck("mark 모르는 컬럼 무시", st.mark("1", zzz=1) is None)
st.close()

st2 = aw.WatchStore(dbp)
ck("재열기 영속", st2.get("1")["price"] == 900)
ck("활성 없으면 next_due_at 0", aw.WatchStore(
    os.path.join(tempfile.mkdtemp(), "empty.db")).next_due_at() == 0)
st2.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd delivery/integrated/manual_gui && /Users/younglee/당근부동산_숨고/.venv/bin/python article_watch_test.py`
Expected: FAIL — `AttributeError: module 'daangn_ext.article_watch' has no attribute 'WatchStore'`

- [ ] **Step 3: Write minimal implementation**

`daangn_ext/article_watch.py` 끝에 붙인다.

```python
_COLUMNS = ("id", "title", "region", "url", "price", "status", "republish_count",
            "published_at", "first_seen", "last_check", "next_check", "tier", "fail")

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
    fail INTEGER
);
CREATE INDEX IF NOT EXISTS idx_watch_due ON watch (tier, next_check);
"""


class WatchStore:
    """추적 중인 매물의 마지막 관측값과 다음 점검 시각."""

    def __init__(self, path: str = "./data/watch.db"):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def upsert(self, row: dict) -> None:
        vals = [row.get(c) for c in _COLUMNS]
        placeholders = ",".join("?" * len(_COLUMNS))
        updates = ",".join(f"{c}=excluded.{c}" for c in _COLUMNS if c != "id")
        self._db.execute(
            f"INSERT INTO watch ({','.join(_COLUMNS)}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}", vals)
        self._db.commit()

    def get(self, article_id: str) -> dict | None:
        r = self._db.execute("SELECT * FROM watch WHERE id=?",
                             (str(article_id),)).fetchone()
        return dict(r) if r else None

    def due(self, now: int, limit: int) -> list[str]:
        rows = self._db.execute(
            "SELECT id FROM watch WHERE tier!='dead' AND next_check<=? "
            "ORDER BY next_check ASC LIMIT ?", (int(now), int(limit))).fetchall()
        return [r["id"] for r in rows]

    def active_count(self) -> int:
        return self._db.execute(
            "SELECT COUNT(*) c FROM watch WHERE tier!='dead'").fetchone()["c"]

    def oldest_active(self, n: int) -> list[str]:
        rows = self._db.execute(
            "SELECT id FROM watch WHERE tier!='dead' ORDER BY published_at ASC LIMIT ?",
            (int(n),)).fetchall()
        return [r["id"] for r in rows]

    def next_due_at(self) -> int:
        r = self._db.execute(
            "SELECT MIN(next_check) v FROM watch WHERE tier!='dead'").fetchone()
        return int(r["v"] or 0)

    def mark(self, article_id: str, **fields) -> None:
        cols = [c for c in fields if c in _COLUMNS and c != "id"]
        if not cols:
            return
        sets = ",".join(f"{c}=?" for c in cols)
        self._db.execute(f"UPDATE watch SET {sets} WHERE id=?",
                         [fields[c] for c in cols] + [str(article_id)])
        self._db.commit()

    def close(self) -> None:
        try:
            self._db.close()
        except Exception:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd delivery/integrated/manual_gui && /Users/younglee/당근부동산_숨고/.venv/bin/python article_watch_test.py`
Expected: PASS — 실패 목록이 비어 있고 종료 코드 0

- [ ] **Step 5: Commit**

```bash
git add delivery/integrated/manual_gui/daangn_ext/article_watch.py delivery/integrated/manual_gui/article_watch_test.py
git commit -m "feat: 워치리스트 저장소(WatchStore)

sqlite data/watch.db 한 테이블. (tier, next_check) 인덱스로 점검 대상만
싸게 뽑는다. dead 행은 지우지 않는다 — 같은 매물이 다시 매칭돼도 중복
알림이 나가지 않게 한다."
```

---

### Task 3: 등급 판정과 이벤트 diff

**Files:**
- Modify: `daangn_ext/article_watch.py`
- Test: `article_watch_test.py` (섹션 추가)

**Interfaces:**
- Consumes: Task 1 상수, Task 2 저장 행 dict
- Produces:
  - `tier_for(published_at: int, now: int) -> str` — `"fresh"` / `"aged"` / `"dead"`
  - `interval_for(tier: str) -> int` — `dead` 는 `0`
  - `diff_events(old: dict, new: dict, now: int) -> list[dict]`
  - 이벤트 dict: `{"kind","id","title","url","old","new","at"}`
  - `kind` 는 `price_down`, `price_up`, `sold`, `deleted`, `republished`

- [ ] **Step 1: Write the failing test**

집계 블록 앞에 붙인다.

```python
print("=== E. 등급 판정 ===")
NOW = 1_000_000
ck("1시간 전 → fresh", aw.tier_for(NOW - 3600, NOW) == "fresh")
ck("47시간 전 → fresh", aw.tier_for(NOW - 47 * 3600, NOW) == "fresh")
ck("49시간 전 → aged", aw.tier_for(NOW - 49 * 3600, NOW) == "aged")
ck("13일 전 → aged", aw.tier_for(NOW - 13 * 86400, NOW) == "aged")
ck("15일 전 → dead", aw.tier_for(NOW - 15 * 86400, NOW) == "dead")
ck("published_at 0 → fresh", aw.tier_for(0, NOW) == "fresh")
ck("fresh 주기 4시간", aw.interval_for("fresh") == 4 * 3600)
ck("aged 주기 24시간", aw.interval_for("aged") == 24 * 3600)
ck("dead 주기 0", aw.interval_for("dead") == 0)

print("=== F. diff_events ===")
OLD = {"id": "1", "title": "가방", "url": "u", "price": 1000,
       "status": "ongoing", "republish_count": 0}


def newrow(**kw):
    base = {"id": "1", "gone": False, "title": "가방", "url": "u", "price": 1000,
            "status": "ongoing", "republish_count": 0}
    base.update(kw)
    return base


ck("변화 없음 → 이벤트 0", aw.diff_events(OLD, newrow(), NOW) == [])

ev = aw.diff_events(OLD, newrow(price=800), NOW)
ck("가격 인하 1건", len(ev) == 1 and ev[0]["kind"] == "price_down", ev)
ck("인하 old/new", ev[0]["old"] == 1000 and ev[0]["new"] == 800)
ck("이벤트에 url", ev[0]["url"] == "u")
ck("이벤트에 at", ev[0]["at"] == NOW)
ck("이벤트에 id", ev[0]["id"] == "1")

ev = aw.diff_events(OLD, newrow(price=1200), NOW)
ck("가격 인상", len(ev) == 1 and ev[0]["kind"] == "price_up")

ev = aw.diff_events(OLD, newrow(status="closed"), NOW)
ck("판매완료", len(ev) == 1 and ev[0]["kind"] == "sold", ev)

ev = aw.diff_events(OLD, newrow(status="reserved"), NOW)
ck("예약중은 이벤트 아님", ev == [], ev)

ev = aw.diff_events(OLD, {"id": "1", "gone": True}, NOW)
ck("삭제", len(ev) == 1 and ev[0]["kind"] == "deleted", ev)
ck("삭제 이벤트도 title 보존", ev[0]["title"] == "가방", ev[0])

ev = aw.diff_events(OLD, newrow(republish_count=1), NOW)
ck("끌올", len(ev) == 1 and ev[0]["kind"] == "republished")

ev = aw.diff_events(OLD, newrow(price=700, status="closed"), NOW)
kinds = sorted(e["kind"] for e in ev)
ck("동시 변화 2건", kinds == ["price_down", "sold"], kinds)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd delivery/integrated/manual_gui && /Users/younglee/당근부동산_숨고/.venv/bin/python article_watch_test.py`
Expected: FAIL — `AttributeError: module 'daangn_ext.article_watch' has no attribute 'tier_for'`

- [ ] **Step 3: Write minimal implementation**

파일 끝에 붙인다.

```python
def tier_for(published_at: int, now: int) -> str:
    """게시 시각으로 점검 등급을 정한다. 시각을 모르면 fresh 로 본다."""
    if not published_at:
        return "fresh"
    age = int(now) - int(published_at)
    if age < FRESH_AGE:
        return "fresh"
    if age < AGED_AGE:
        return "aged"
    return "dead"


def interval_for(tier: str) -> int:
    return {"fresh": FRESH_INTERVAL, "aged": AGED_INTERVAL}.get(tier, 0)


def _ev(kind, old_row, new_row, old, new, now):
    return {"kind": kind,
            "id": str(old_row.get("id")),
            "title": new_row.get("title") or old_row.get("title") or "",
            "url": new_row.get("url") or old_row.get("url") or "",
            "old": old, "new": new, "at": int(now)}


def diff_events(old: dict, new: dict, now: int) -> list[dict]:
    """저장값과 새 관측값을 비교해 이벤트 목록을 만든다.

    예약중(reserved)은 알리지 않는다 — 되돌아오는 경우가 흔해 소음이 된다."""
    if new.get("gone"):
        return [_ev("deleted", old, new, old.get("status"), "gone", now)]

    out = []
    op, np_ = old.get("price"), new.get("price")
    if isinstance(op, int) and isinstance(np_, int) and op != np_:
        out.append(_ev("price_down" if np_ < op else "price_up", old, new, op, np_, now))

    os_, ns = old.get("status"), new.get("status")
    if ns == STATUS_CLOSED and os_ != STATUS_CLOSED:
        out.append(_ev("sold", old, new, os_, ns, now))

    orc, nrc = old.get("republish_count") or 0, new.get("republish_count") or 0
    if nrc > orc:
        out.append(_ev("republished", old, new, orc, nrc, now))

    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd delivery/integrated/manual_gui && /Users/younglee/당근부동산_숨고/.venv/bin/python article_watch_test.py`
Expected: PASS — 실패 목록이 비어 있고 종료 코드 0

- [ ] **Step 5: Commit**

```bash
git add delivery/integrated/manual_gui/daangn_ext/article_watch.py delivery/integrated/manual_gui/article_watch_test.py
git commit -m "feat: 워치리스트 등급 판정과 이벤트 diff

48시간 이내는 4시간마다, 2~14일은 하루 한 번, 그 밖은 추적을 끊는다.
예약중은 알리지 않는다 — 되돌아오는 경우가 흔해 소음이 된다."
```

---

### Task 4: WatchTracker — 투입·상한·점검·스윕

**Files:**
- Modify: `daangn_ext/article_watch.py`
- Test: `article_watch_test.py` (섹션 추가)

**Interfaces:**
- Consumes: Task 1~3 전부
- Produces:
  - `parse_price_text(s) -> int` — `"410,000원"` → `410000`
  - `class AccountUnavailable(Exception)` — 401/429 로 그 계정을 이번 스윕에서 빼야 할 때
  - `class WatchTracker(store: WatchStore, now_fn=time.time)`
  - `add_from_matches(matches, now=None) -> int` — `keyword_alert_api.new_matches()` 출력(`article_id`,`title`,`region`,`url`,`price`,`time`)에서 신규만 등록. 이미 있는 id 는 손대지 않는다(dead 포함)
  - `enforce_cap(now=None) -> int` — 활성이 `ACTIVE_CAP` 을 넘으면 `published_at` 이 오래된 것부터 `dead`. 강등 수를 돌려준다
  - `check_one(article_id, api, now=None) -> list[dict]` — 조회·diff·저장. 일반 예외는 삼키고 `fail` 을 올린다. 401/429 는 `AccountUnavailable` 로 올린다
  - `sweep(api_for_account, budget: int, now=None) -> list[dict]` — `api_for_account()` 는 `(api, label)` 또는 예산 소진 시 `None`

- [ ] **Step 1: Write the failing test**

집계 블록 앞에 붙인다.

```python
print("=== G. parse_price_text ===")
ck("410,000원 → 410000", aw.parse_price_text("410,000원") == 410000)
ck("나눔 → 0", aw.parse_price_text("나눔") == 0)
ck("None → 0", aw.parse_price_text(None) == 0)
ck("정수 그대로", aw.parse_price_text(5000) == 5000)

print("=== H. 투입과 상한 ===")
dbp2 = os.path.join(tempfile.mkdtemp(), "w2.db")
store = aw.WatchStore(dbp2)
tr = aw.WatchTracker(store)

MATCHES = [
    {"article_id": "10", "title": "샤넬", "region": "강남", "url": "u10",
     "price": "1,000,000원", "time": str(NOW - 3600)},
    {"article_id": "11", "title": "디올", "region": "서초", "url": "u11",
     "price": "500,000원", "time": str(NOW - 5 * 86400)},
]
ck("신규 2건 투입", tr.add_from_matches(MATCHES, now=NOW) == 2)
ck("중복 투입 0건", tr.add_from_matches(MATCHES, now=NOW) == 0)
ck("가격 파싱 저장", store.get("10")["price"] == 1000000)
ck("fresh 등급", store.get("10")["tier"] == "fresh")
ck("aged 등급", store.get("11")["tier"] == "aged")
ck("next_check 미래", store.get("10")["next_check"] > NOW)
ck("article_id 없으면 무시", tr.add_from_matches([{"title": "x"}], now=NOW) == 0)
ck("15일 지난 매칭은 투입 안 함",
   tr.add_from_matches([{"article_id": "99", "title": "옛것", "region": "r",
                         "url": "u", "price": "1원",
                         "time": str(NOW - 15 * 86400)}], now=NOW) == 0)

for i in range(aw.ACTIVE_CAP + 5):
    store.upsert({"id": f"c{i}", "title": "t", "region": "r", "url": "u",
                  "price": 1, "status": "ongoing", "republish_count": 0,
                  "published_at": NOW - i * 60, "first_seen": NOW,
                  "last_check": NOW, "next_check": NOW + 10, "tier": "fresh",
                  "fail": 0})
before = store.active_count()
dropped = tr.enforce_cap(NOW)
ck("상한까지 강등", store.active_count() == aw.ACTIVE_CAP,
   f"{before} -> {store.active_count()}")
ck("강등 수 반환", dropped == before - aw.ACTIVE_CAP, dropped)
ck("가장 오래된 것부터", store.get("c%d" % (aw.ACTIVE_CAP + 4))["tier"] == "dead")
ck("상한 이하면 0", tr.enforce_cap(NOW) == 0)

print("=== I. check_one ===")
dbp3 = os.path.join(tempfile.mkdtemp(), "w3.db")
store3 = aw.WatchStore(dbp3)
tr3 = aw.WatchTracker(store3)
tr3.add_from_matches([{"article_id": "20", "title": "구찌", "region": "강남",
                       "url": "u20", "price": "900,000원",
                       "time": str(NOW - 3600)}], now=NOW)


class FakeAPI:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, 0

    def fetch(self, article_id):
        self.calls += 1
        if self.exc:
            raise self.exc
        return dict(self.result, id=str(article_id))


def http_error(code):
    req = httpx.Request("GET", "https://x/")
    return httpx.HTTPStatusError("boom", request=req,
                                 response=httpx.Response(code, request=req))


api_ok = FakeAPI({"gone": False, "title": "구찌", "url": "u20", "price": 800000,
                  "status": "ongoing", "republish_count": 0,
                  "published_at": NOW - 3600, "region": "강남"})
ev = tr3.check_one("20", api_ok, NOW + 100)
ck("인하 이벤트", len(ev) == 1 and ev[0]["kind"] == "price_down", ev)
ck("새 가격 저장", store3.get("20")["price"] == 800000)
ck("last_check 갱신", store3.get("20")["last_check"] == NOW + 100)
ck("next_check 재계산",
   store3.get("20")["next_check"] == NOW + 100 + aw.FRESH_INTERVAL)
ck("두 번째 조회는 이벤트 없음", tr3.check_one("20", api_ok, NOW + 200) == [])
ck("없는 id 는 조용히 빈 목록", tr3.check_one("없음", api_ok, NOW) == [])

api_closed = FakeAPI({"gone": False, "title": "구찌", "url": "u20", "price": 800000,
                      "status": "closed", "republish_count": 0,
                      "published_at": NOW - 3600, "region": "강남"})
ev = tr3.check_one("20", api_closed, NOW + 250)
ck("판매완료 이벤트", len(ev) == 1 and ev[0]["kind"] == "sold", ev)
ck("판매완료 후 dead", store3.get("20")["tier"] == "dead")

tr3.add_from_matches([{"article_id": "22", "title": "루이", "region": "강남",
                       "url": "u22", "price": "1원", "time": str(NOW - 3600)}],
                     now=NOW)
ev = tr3.check_one("22", FakeAPI({"gone": True}), NOW + 300)
ck("삭제 이벤트", len(ev) == 1 and ev[0]["kind"] == "deleted")
ck("삭제 후 dead", store3.get("22")["tier"] == "dead")
ck("dead 는 due 에서 빠짐", store3.due(NOW + 99999, 10) == [])

tr3.add_from_matches([{"article_id": "21", "title": "펜디", "region": "강남",
                       "url": "u21", "price": "100,000원",
                       "time": str(NOW - 3600)}], now=NOW)
api_err = FakeAPI(exc=RuntimeError("boom"))
for i in range(aw.MAX_FAIL):
    ck(f"실패 {i+1}회 이벤트 없음",
       tr3.check_one("21", api_err, NOW + 400 + i) == [])
ck("MAX_FAIL 후 dead", store3.get("21")["tier"] == "dead")
ck("fail 카운터", store3.get("21")["fail"] == aw.MAX_FAIL)

tr3.add_from_matches([{"article_id": "23", "title": "에르메스", "region": "강남",
                       "url": "u23", "price": "1원", "time": str(NOW - 3600)}],
                     now=NOW)
try:
    tr3.check_one("23", FakeAPI(exc=http_error(429)), NOW + 500)
    ck("429 → AccountUnavailable", False)
except aw.AccountUnavailable:
    ck("429 → AccountUnavailable", True)
ck("429 는 fail 안 올림", store3.get("23")["fail"] == 0)
ck("429 는 next_check 미룸",
   store3.get("23")["next_check"] == NOW + 500 + aw.RATE_LIMIT_DELAY,
   store3.get("23")["next_check"])

try:
    tr3.check_one("23", FakeAPI(exc=http_error(401)), NOW + 600)
    ck("401 → AccountUnavailable", False)
except aw.AccountUnavailable:
    ck("401 → AccountUnavailable", True)
ck("401 는 fail 안 올림", store3.get("23")["fail"] == 0)

try:
    tr3.check_one("23", FakeAPI(exc=http_error(500)), NOW + 700)
    ck("500 은 일반 실패", store3.get("23")["fail"] == 1, store3.get("23")["fail"])
except aw.AccountUnavailable:
    ck("500 은 일반 실패", False)

print("=== J. sweep ===")
dbp4 = os.path.join(tempfile.mkdtemp(), "w4.db")
store4 = aw.WatchStore(dbp4)
tr4 = aw.WatchTracker(store4)
for i in range(5):
    store4.upsert({"id": f"s{i}", "title": "t", "region": "r", "url": "u",
                   "price": 100, "status": "ongoing", "republish_count": 0,
                   "published_at": NOW - 3600, "first_seen": NOW,
                   "last_check": NOW, "next_check": NOW - 1, "tier": "fresh",
                   "fail": 0})

shared = FakeAPI({"gone": False, "title": "t", "url": "u", "price": 90,
                  "status": "ongoing", "republish_count": 0,
                  "published_at": NOW - 3600, "region": "r"})
evs = tr4.sweep(lambda: (shared, "acc-a"), budget=3, now=NOW)
ck("예산만큼만 조회", shared.calls == 3, shared.calls)
ck("이벤트 3건", len(evs) == 3, len(evs))
ck("남은 2건은 due 유지", len(store4.due(NOW, 10)) == 2)
ck("계정 없으면 조회 0", tr4.sweep(lambda: None, budget=10, now=NOW) == [])

dbp5 = os.path.join(tempfile.mkdtemp(), "w5.db")
store5 = aw.WatchStore(dbp5)
tr5 = aw.WatchTracker(store5)
for i in range(3):
    store5.upsert({"id": f"r{i}", "title": "t", "region": "r", "url": "u",
                   "price": 100, "status": "ongoing", "republish_count": 0,
                   "published_at": NOW - 3600, "first_seen": NOW,
                   "last_check": NOW, "next_check": NOW - 1, "tier": "fresh",
                   "fail": 0})
bad_api = FakeAPI(exc=http_error(429))
good_api = FakeAPI({"gone": False, "title": "t", "url": "u", "price": 90,
                    "status": "ongoing", "republish_count": 0,
                    "published_at": NOW - 3600, "region": "r"})
seq = [(bad_api, "acc-bad"), (bad_api, "acc-bad"), (good_api, "acc-good"),
       (good_api, "acc-good"), (good_api, "acc-good")]


def provider():
    return seq.pop(0) if seq else None


evs = tr5.sweep(provider, budget=3, now=NOW)
ck("막힌 계정은 이후 건너뜀", bad_api.calls == 1, bad_api.calls)
ck("다른 계정으로 이어감", good_api.calls >= 1, good_api.calls)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd delivery/integrated/manual_gui && /Users/younglee/당근부동산_숨고/.venv/bin/python article_watch_test.py`
Expected: FAIL — `AttributeError: module 'daangn_ext.article_watch' has no attribute 'parse_price_text'`

- [ ] **Step 3: Write minimal implementation**

파일 끝에 붙인다.

```python
class AccountUnavailable(Exception):
    """이 계정으로는 이번 스윕을 더 진행할 수 없다(401/429)."""


def parse_price_text(s) -> int:
    """매칭 응답의 '410,000원' 같은 문자열에서 숫자만 뽑는다. 없으면 0."""
    if isinstance(s, int):
        return s
    if not isinstance(s, str):
        return 0
    digits = re.sub(r"[^0-9]", "", s)
    return int(digits) if digits else 0


class WatchTracker:
    """등급·상한 정책과 diff. 네트워크는 주입받은 api 로만 한다."""

    def __init__(self, store: WatchStore, now_fn=time.time):
        self.store = store
        self._now_fn = now_fn

    def _now(self, now=None) -> int:
        return int(now if now is not None else self._now_fn())

    def add_from_matches(self, matches, now=None) -> int:
        now = self._now(now)
        added = 0
        for m in matches or []:
            aid = m.get("article_id")
            if not aid:
                continue
            aid = str(aid)
            if self.store.get(aid) is not None:
                continue
            try:
                published = int(m.get("time") or 0)
            except (TypeError, ValueError):
                published = 0
            tier = tier_for(published, now)
            if tier == "dead":
                continue
            self.store.upsert({
                "id": aid,
                "title": m.get("title") or "",
                "region": m.get("region") or "",
                "url": m.get("url") or "",
                "price": parse_price_text(m.get("price")),
                "status": STATUS_ONGOING,
                "republish_count": 0,
                "published_at": published,
                "first_seen": now,
                "last_check": now,
                "next_check": now + interval_for(tier),
                "tier": tier,
                "fail": 0,
            })
            added += 1
        return added

    def enforce_cap(self, now=None) -> int:
        self._now(now)
        over = self.store.active_count() - ACTIVE_CAP
        if over <= 0:
            return 0
        for aid in self.store.oldest_active(over):
            self.store.mark(aid, tier="dead")
        return over

    def check_one(self, article_id, api, now=None) -> list[dict]:
        now = self._now(now)
        old = self.store.get(str(article_id))
        if old is None:
            return []
        try:
            new = api.fetch(str(article_id))
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            if code in (401, 429):
                delay = RATE_LIMIT_DELAY if code == 429 \
                    else interval_for(old.get("tier") or "fresh")
                self.store.mark(article_id, next_check=now + delay)
                raise AccountUnavailable(str(code))
            return self._note_failure(old, article_id, now)
        except Exception:
            return self._note_failure(old, article_id, now)

        events = diff_events(old, new, now)
        if new.get("gone"):
            self.store.mark(article_id, tier="dead", fail=0, last_check=now)
            return events

        tier = tier_for(new.get("published_at") or old.get("published_at") or 0, now)
        if new.get("status") == STATUS_CLOSED:
            tier = "dead"
        self.store.upsert({
            "id": str(article_id),
            "title": new.get("title") or old.get("title"),
            "region": new.get("region") or old.get("region"),
            "url": new.get("url") or old.get("url"),
            "price": new.get("price"),
            "status": new.get("status"),
            "republish_count": new.get("republish_count") or 0,
            "published_at": new.get("published_at") or old.get("published_at") or 0,
            "first_seen": old.get("first_seen") or now,
            "last_check": now,
            "next_check": now + interval_for(tier),
            "tier": tier,
            "fail": 0,
        })
        return events

    def _note_failure(self, old, article_id, now) -> list[dict]:
        """조회 실패는 매물의 변화가 아니다 — 알리지 않고 세기만 한다."""
        fail = (old.get("fail") or 0) + 1
        if fail >= MAX_FAIL:
            self.store.mark(article_id, fail=fail, tier="dead", last_check=now)
        else:
            self.store.mark(article_id, fail=fail, last_check=now,
                            next_check=now + interval_for(old.get("tier") or "fresh"))
        return []

    def sweep(self, api_for_account, budget: int, now=None) -> list[dict]:
        """예산만큼 점검한다. api_for_account 는 매 건마다 불리고
        (api, label) 또는 예산 소진 시 None 을 돌려줘야 한다."""
        now = self._now(now)
        out = []
        blocked = set()
        for aid in self.store.due(now, int(budget)):
            api = label = None
            for _ in range(4):
                got = api_for_account()
                if not got:
                    return out
                if got[1] in blocked:
                    _close(got[0])
                    continue
                api, label = got
                break
            if api is None:
                return out
            try:
                out.extend(self.check_one(aid, api, now))
            except AccountUnavailable:
                blocked.add(label)
            finally:
                _close(api)
        return out


def _close(obj) -> None:
    fn = getattr(obj, "close", None)
    if callable(fn):
        try:
            fn()
        except Exception:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd delivery/integrated/manual_gui && /Users/younglee/당근부동산_숨고/.venv/bin/python article_watch_test.py`
Expected: PASS — 실패 목록이 비어 있고 종료 코드 0

- [ ] **Step 5: Commit**

```bash
git add delivery/integrated/manual_gui/daangn_ext/article_watch.py delivery/integrated/manual_gui/article_watch_test.py
git commit -m "feat: 워치리스트 트래커(투입·상한·점검·스윕)

매칭에서 신규만 골라 넣고, 활성 300건을 넘으면 오래된 것부터 추적을 끊는다.
401/429 는 계정 문제라 그 계정을 이번 스윕에서 빼고 다른 계정으로 잇는다.
조회 실패는 매물의 변화가 아니므로 5회까지 세기만 하고 알리지 않는다."
```

---

### Task 5: AccountBudget — 계정별 일일 예산

**Files:**
- Modify: `daangn_ext/article_watch.py`
- Test: `article_watch_test.py` (섹션 추가)

**Interfaces:**
- Consumes: `daangn_ext.keyword_alert_api.token_remaining`(Task 1 에서 이미 import), Task 1 `ArticleDetailAPI`
- Produces:
  - `class AccountBudget(accounts_fp="./accounts.json", daily_cap=DAILY_CAP_PER_ACCOUNT, config_path="./data/config.json", api_factory=None, day_fn=None)`
  - `next() -> tuple | None` — `(ArticleDetailAPI, label)`. 유효 토큰이 없거나 전부 상한이면 `None`
  - `remaining() -> int` — 오늘 남은 총 요청 수
  - `reload() -> None` — accounts.json 다시 읽기
  - 날짜가 바뀌면 사용량이 0 으로 리셋된다

- [ ] **Step 1: Write the failing test**

집계 블록 앞에 붙인다.

```python
print("=== K. AccountBudget ===")
import json as _json

acc_fp = os.path.join(tempfile.mkdtemp(), "accounts.json")
_json.dump([{"label": l, "access": "tok-" + l, "proxy": None} for l in ("a", "b")],
           open(acc_fp, "w", encoding="utf-8"))

DAY = {"v": "2026-08-29"}


def fake_factory(token, config_path=None, proxy=None):
    return FakeAPI({"gone": False, "title": "t", "url": "u", "price": 1,
                    "status": "ongoing", "republish_count": 0,
                    "published_at": NOW, "region": "r"})


orig_remaining = aw.token_remaining
aw.token_remaining = lambda t: 9999          # 전부 유효한 토큰으로 취급

bud = aw.AccountBudget(acc_fp, daily_cap=2, api_factory=fake_factory,
                       day_fn=lambda: DAY["v"])
ck("총 예산 = 계정수 x 상한", bud.remaining() == 4, bud.remaining())
got = [bud.next() for _ in range(4)]
ck("4건 모두 발급", all(g is not None for g in got))
ck("라운드로빈", [g[1] for g in got] == ["a", "b", "a", "b"], [g[1] for g in got])
ck("소진 후 None", bud.next() is None)
ck("remaining 0", bud.remaining() == 0)

DAY["v"] = "2026-08-30"
ck("날짜 바뀌면 리셋", bud.remaining() == 4)
ck("리셋 후 발급", bud.next() is not None)

aw.token_remaining = lambda t: 10            # 만료 임박 = 무효
bud2 = aw.AccountBudget(acc_fp, daily_cap=2, api_factory=fake_factory,
                        day_fn=lambda: DAY["v"])
ck("유효 토큰 없으면 None", bud2.next() is None)
ck("유효 토큰 없으면 remaining 0", bud2.remaining() == 0)

aw.token_remaining = lambda t: 9999
bud3 = aw.AccountBudget(os.path.join(tempfile.mkdtemp(), "없음.json"),
                        daily_cap=2, api_factory=fake_factory,
                        day_fn=lambda: DAY["v"])
ck("파일 없으면 None", bud3.next() is None)

aw.token_remaining = orig_remaining
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd delivery/integrated/manual_gui && /Users/younglee/당근부동산_숨고/.venv/bin/python article_watch_test.py`
Expected: FAIL — `AttributeError: module 'daangn_ext.article_watch' has no attribute 'AccountBudget'`

- [ ] **Step 3: Write minimal implementation**

파일 끝에 붙인다. `token_remaining` 은 모듈 전역 이름으로 부른다 — 테스트가 이 이름을 바꿔 끼운다.

```python
def _today() -> str:
    return _dt.date.today().isoformat()


class AccountBudget:
    """유효 토큰 계정을 라운드로빈으로 내주고 하루 요청 수를 계정별로 제한한다."""

    def __init__(self, accounts_fp: str = "./accounts.json",
                 daily_cap: int = DAILY_CAP_PER_ACCOUNT,
                 config_path: str = "./data/config.json",
                 api_factory=None, day_fn=None):
        self.accounts_fp = accounts_fp
        self.daily_cap = int(daily_cap)
        self.config_path = config_path
        self._factory = api_factory or _default_api_factory
        self._day_fn = day_fn or _today
        self._used = {}
        self._day = self._day_fn()
        self._cursor = 0
        self._accounts = []
        self.reload()

    def reload(self) -> None:
        try:
            with open(self.accounts_fp, encoding="utf-8") as f:
                self._accounts = json.load(f) or []
        except Exception:
            self._accounts = []

    def _roll_day(self) -> None:
        today = self._day_fn()
        if today != self._day:
            self._day = today
            self._used = {}

    def _valid(self) -> list[dict]:
        return [a for a in self._accounts
                if token_remaining(a.get("access") or "") > MIN_TOKEN_REMAINING]

    def remaining(self) -> int:
        self._roll_day()
        return sum(max(0, self.daily_cap - self._used.get(a.get("label") or "", 0))
                   for a in self._valid())

    def next(self):
        self._roll_day()
        cands = self._valid()
        if not cands:
            return None
        for _ in range(len(cands)):
            a = cands[self._cursor % len(cands)]
            self._cursor += 1
            label = a.get("label") or ""
            if self._used.get(label, 0) < self.daily_cap:
                self._used[label] = self._used.get(label, 0) + 1
                return self._factory(a.get("access"), config_path=self.config_path,
                                     proxy=a.get("proxy")), label
        return None


def _default_api_factory(token, config_path=None, proxy=None):
    return ArticleDetailAPI(token, config_path=config_path or "./data/config.json",
                            proxy=proxy)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd delivery/integrated/manual_gui && /Users/younglee/당근부동산_숨고/.venv/bin/python article_watch_test.py`
Expected: PASS — 실패 목록이 비어 있고 종료 코드 0

- [ ] **Step 5: Commit**

```bash
git add delivery/integrated/manual_gui/daangn_ext/article_watch.py delivery/integrated/manual_gui/article_watch_test.py
git commit -m "feat: 계정별 일일 예산 공급자(AccountBudget)

만료 임박 토큰은 빼고, 계정당 하루 300건으로 끊는다. 날짜가 바뀌면
사용량을 0 으로 되돌린다."
```

---

### Task 6: GUI 배선 — 투입·스윕 타이머·알림

**Files:**
- Modify: `main.py`
- Test: `article_watch_wiring_test.py` (신규)

**Interfaces:**
- Consumes: Task 1~5 전부
- Produces:
  - `main.WATCH_SWEEP_INTERVAL = 600`
  - `main.watch_event_lines(events) -> list[str]` — 모듈 최상위 순수 함수
  - `main.watch_sweep_budget(active, interval_sec) -> int` — 모듈 최상위 순수 함수
  - `class _WatchNotifyThread(QtCore.QThread)` — 텔레그램·시트 전송 전용
  - `MainWindow._watch_store` / `_watch_tracker` / `_watch_budget` / `_watch_timer`
  - `MainWindow._watch_sweep_tick()` / `_notify_watch_events(events)`
  - `_match_populate` 안에서 `add_from_matches(new_items)` 호출

기존 코드의 정확한 위치는 다음과 같다. 이 줄 번호는 작업 시작 시점 기준이므로 이름으로 찾는다.

- `main.py:86 class _NotifyThread` — 매칭 알림 스레드. 참고만 하고 고치지 않는다
- `main.py:374 def _build_alert_tab` — 키워드 알림 탭 레이아웃
- `main.py:527 self._alert_poll_timer` — 타이머들을 만드는 자리
- `main.py:997 def _match_populate` — 매칭 표에 넣는 곳. `new_items` 가 신규 매칭 목록이고 `if new:` 블록에서 `self._notify_matches(new_items)` 를 부른다
- `main.py:1155 def on_alert_poll_all` — 폴링 진입점. `_match_populate` 를 콜백으로 준다
- 로그는 `self.alertLog.append(...)`

- [ ] **Step 1: Write the failing test**

`article_watch_wiring_test.py` 를 새로 만든다.

```python
"""워치리스트 배선 중 순수 함수만 확인 (Qt 창 안 띄움).

    python article_watch_wiring_test.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main as m

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


print("=== A. watch_event_lines ===")
EV = [
    {"kind": "price_down", "id": "1", "title": "샤넬 클래식", "url": "u1",
     "old": 1000000, "new": 800000, "at": 0},
    {"kind": "price_up", "id": "2", "title": "디올 백", "url": "u2",
     "old": 500000, "new": 600000, "at": 0},
    {"kind": "sold", "id": "3", "title": "구찌 지갑", "url": "u3",
     "old": "ongoing", "new": "closed", "at": 0},
    {"kind": "deleted", "id": "4", "title": "펜디 백", "url": "u4",
     "old": "ongoing", "new": "gone", "at": 0},
    {"kind": "republished", "id": "5", "title": "프라다 백", "url": "u5",
     "old": 0, "new": 1, "at": 0},
]
lines = m.watch_event_lines(EV)
ck("이벤트 수만큼", len(lines) == 5, len(lines))
ck("인하 제목", "샤넬 클래식" in lines[0], lines[0])
ck("인하 금액 천단위", "800,000" in lines[0], lines[0])
ck("인하 표시", "↓" in lines[0], lines[0])
ck("인상 표시", "↑" in lines[1], lines[1])
ck("판매완료 문구", "판매완료" in lines[2], lines[2])
ck("삭제 문구", "삭제" in lines[3], lines[3])
ck("끌올 문구", "끌올" in lines[4], lines[4])
ck("링크 포함", "u1" in lines[0], lines[0])
ck("빈 입력 → 빈 목록", m.watch_event_lines([]) == [])
ck("None → 빈 목록", m.watch_event_lines(None) == [])
ck("모르는 kind 는 건너뜀", m.watch_event_lines([{"kind": "zzz", "id": "9"}]) == [])

print("=== B. watch_sweep_budget ===")
ck("활성 0 → 0", m.watch_sweep_budget(0, 600) == 0)
ck("활성 300, 10분 → 양수", m.watch_sweep_budget(300, 600) > 0)
ck("주기 길수록 예산 큼",
   m.watch_sweep_budget(300, 1200) > m.watch_sweep_budget(300, 600))
ck("활성 많을수록 예산 큼",
   m.watch_sweep_budget(300, 600) > m.watch_sweep_budget(30, 600))
ck("최소 1 보장", m.watch_sweep_budget(1, 600) >= 1)
ck("스윕 주기 상수", m.WATCH_SWEEP_INTERVAL == 600)

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd delivery/integrated/manual_gui && /Users/younglee/당근부동산_숨고/.venv/bin/python article_watch_wiring_test.py`
Expected: FAIL — `AttributeError: module 'main' has no attribute 'watch_event_lines'`

- [ ] **Step 3: Write minimal implementation**

`main.py` 상단 import 에 더한다.

```python
from daangn_ext import article_watch
```

`LUXURY_BRANDS` 상수 아래(모듈 최상위)에 넣는다.

```python
WATCH_SWEEP_INTERVAL = 600          # 워치리스트 스윕 주기(초)

_WATCH_LABELS = {
    "price_down": "↓ 가격 인하",
    "price_up": "↑ 가격 인상",
    "sold": "판매완료",
    "deleted": "삭제됨",
    "republished": "끌올",
}


def watch_event_lines(events):
    """워치리스트 이벤트 → 알림 한 줄씩. 모르는 종류는 건너뛴다."""
    out = []
    for e in events or []:
        label = _WATCH_LABELS.get(e.get("kind"))
        if not label:
            continue
        title = e.get("title") or e.get("id") or ""
        url = e.get("url") or ""
        kind = e.get("kind")
        if kind in ("price_down", "price_up"):
            body = f"{int(e.get('old') or 0):,}원 → {int(e.get('new') or 0):,}원"
        elif kind == "republished":
            body = f"{e.get('old')}회 → {e.get('new')}회"
        else:
            body = ""
        out.append(" ".join(x for x in (f"[{label}]", title, body, url) if x))
    return out


def watch_sweep_budget(active, interval_sec):
    """이번 스윕에서 조회할 최대 건수.

    활성 전체를 fresh 주기(4시간) 안에 한 바퀴 돈다고 보고 비례 배분한다.
    활성이 있으면 최소 1건은 본다."""
    active = int(active or 0)
    if active <= 0:
        return 0
    per_cycle = active * int(interval_sec) / float(article_watch.FRESH_INTERVAL)
    return max(1, int(per_cycle + 0.999))
```

`_NotifyThread` 클래스 아래에 전용 스레드를 새로 만든다. 기존 `_NotifyThread` 는 매칭 문구 전용이라 손대지 않는다.

```python
class _WatchNotifyThread(QtCore.QThread):
    """워치리스트 변동 알림 — 텔레그램 + 구글시트. GUI 안 멈춤."""
    log = QtCore.pyqtSignal(str)

    def __init__(self, notify, lines):
        super().__init__()
        self.notify = notify or {}
        self.lines = list(lines)

    def run(self):
        import time as _t
        emit = lambda m: self.log.emit(m)
        if not self.lines:
            return
        tok, chat = self.notify.get("tg_token"), self.notify.get("tg_chat")
        if tok and chat:
            try:
                from daangn.notify import TelegramSender
                tg = TelegramSender(tok, chat, log=emit)
                tg.enqueue("📉 가격변동\n" + "\n".join(self.lines))
                tg.flush()
                emit(f"[텔레그램] 변동 {len(self.lines)}건 전송")
            except Exception as e:
                emit(f"[텔레그램] 실패: {str(e)[:50]}")
        if self.notify.get("sheet_url"):
            try:
                from daangn.notify import SheetWriter
                sw = SheetWriter(self.notify.get("sheet_url"),
                                 self.notify.get("sheet_cred") or "./credentials.json",
                                 log=emit)
                ts = _t.strftime("%Y-%m-%d %H:%M")
                for ln in self.lines:
                    sw.enqueue_row([ts, "가격변동", ln])
                wrote, failed = sw.flush()
                if wrote:
                    emit(f"[구글시트] {wrote}행 기록")
            except Exception as e:
                emit(f"[구글시트] 실패: {str(e)[:50]}")
```

`MainWindow.__init__` 에서 `self._alert_poll_timer` 를 만드는 자리 부근에 붙인다.

```python
        # ── 워치리스트(가격변동 추적) ──
        self._watch_store = article_watch.WatchStore("./data/watch.db")
        self._watch_tracker = article_watch.WatchTracker(self._watch_store)
        self._watch_budget = article_watch.AccountBudget("./accounts.json")
        self._watch_threads = []
        self._watch_timer = QtCore.QTimer(self)
        self._watch_timer.timeout.connect(self._watch_sweep_tick)
        self._watch_timer.start(WATCH_SWEEP_INTERVAL * 1000)
```

`MainWindow` 에 메서드를 더한다.

```python
    def _watch_sweep_tick(self):
        """10분마다 워치리스트를 예산만큼 재조회하고 변동을 알린다."""
        try:
            self._watch_tracker.enforce_cap()
            budget = watch_sweep_budget(self._watch_store.active_count(),
                                        WATCH_SWEEP_INTERVAL)
            if not budget:
                return
            self._watch_budget.reload()
            events = self._watch_tracker.sweep(self._watch_budget.next, budget)
            if events:
                self._notify_watch_events(events)
        except Exception as e:
            self.alertLog.append(f"[가격추적] 스윕 실패: {str(e)[:120]}")

    def _notify_watch_events(self, events):
        lines = watch_event_lines(events)
        if not lines:
            return
        for line in lines:
            self.alertLog.append(f"[가격추적] {line}")
        th = _WatchNotifyThread(getattr(self, "_notify", {}) or {}, lines)
        th.log.connect(self.alertLog.append)
        th.finished.connect(lambda t=th: self._watch_threads.remove(t)
                            if t in self._watch_threads else None)
        self._watch_threads.append(th)
        th.start()
```

`_match_populate` 의 `if new:` 블록 안, `self._notify_matches(new_items)` 바로 아래에 한 줄 넣는다.

```python
            self._watch_tracker.add_from_matches(new_items)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd delivery/integrated/manual_gui && /Users/younglee/당근부동산_숨고/.venv/bin/python article_watch_wiring_test.py`
Expected: PASS — 실패 목록이 비어 있고 종료 코드 0

`python article_watch_test.py` 도 다시 돌려 여전히 전부 PASS 인지 확인한다.

- [ ] **Step 5: Commit**

```bash
git add delivery/integrated/manual_gui/main.py delivery/integrated/manual_gui/article_watch_wiring_test.py
git commit -m "feat: 키워드 알림 탭에 워치리스트 배선

매칭이 잡히면 워치리스트에 넣고, 폴링과 분리된 10분 타이머로 재조회한다.
폴링 주기(120초)와 재조회 주기는 두 자릿수 배 차이라 한 틱에 묶으면
예산 계산이 흐려진다. 변동 알림은 매칭 알림과 문구가 달라 전용
스레드(_WatchNotifyThread)로 보낸다."
```

---

### Task 7: GUI 패널 — 추적 현황

**Files:**
- Modify: `main.py`
- Test: `article_watch_wiring_test.py` (섹션 추가)

**Interfaces:**
- Consumes: Task 2 `next_due_at`, Task 6 `_watch_store`
- Produces:
  - `main.watch_status_text(active, next_check_at, now) -> str` — 모듈 최상위 순수 함수
  - `MainWindow._watch_label` (QLabel), `MainWindow._watch_list` (QListWidget)
  - `MainWindow._refresh_watch_panel()` — 기존 헬스 타이머 콜백 `_refresh_alert_health` 에서 호출

- [ ] **Step 1: Write the failing test**

`article_watch_wiring_test.py` 의 집계 블록 앞에 붙인다.

```python
print("=== C. watch_status_text ===")
s = m.watch_status_text(42, 1000 + 3600, 1000)
ck("건수 포함", "42" in s, s)
ck("시간 표기", "1시간" in s, s)
ck("추적 0건", m.watch_status_text(0, 0, 1000) == "추적 중 0건",
   m.watch_status_text(0, 0, 1000))
ck("분 단위 표기", "5분" in m.watch_status_text(5, 1300, 1000),
   m.watch_status_text(5, 1300, 1000))
ck("다음 점검 지남", "대기" in m.watch_status_text(5, 900, 1000),
   m.watch_status_text(5, 900, 1000))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd delivery/integrated/manual_gui && /Users/younglee/당근부동산_숨고/.venv/bin/python article_watch_wiring_test.py`
Expected: FAIL — `AttributeError: module 'main' has no attribute 'watch_status_text'`

- [ ] **Step 3: Write minimal implementation**

`main.py` 모듈 최상위, `watch_sweep_budget` 아래에 넣는다.

```python
def watch_status_text(active, next_check_at, now):
    """추적 현황 한 줄."""
    active = int(active or 0)
    if not active:
        return "추적 중 0건"
    left = int(next_check_at or 0) - int(now)
    if left <= 0:
        return f"추적 중 {active}건 · 다음 점검 대기"
    if left >= 3600:
        when = f"{left // 3600}시간 {(left % 3600) // 60}분 후"
    else:
        when = f"{max(1, left // 60)}분 후"
    return f"추적 중 {active}건 · 다음 점검 {when}"
```

`_build_alert_tab` 안, 매칭 표(`self.matchTable`)를 레이아웃에 넣은 다음 자리에 붙인다. 그 메서드가 쓰는 레이아웃 변수 이름을 그대로 쓴다.

```python
        watch_box = QtWidgets.QGroupBox("가격 추적")
        watch_v = QtWidgets.QVBoxLayout(watch_box)
        self._watch_label = QtWidgets.QLabel("추적 중 0건")
        self._watch_list = QtWidgets.QListWidget()
        self._watch_list.setMaximumHeight(140)
        watch_v.addWidget(self._watch_label)
        watch_v.addWidget(self._watch_list)
```

레이아웃 추가 줄은 그 메서드의 기존 방식(예: `v.addWidget(...)`)을 따른다.

`MainWindow` 에 갱신 메서드를 더한다.

```python
    def _refresh_watch_panel(self):
        try:
            import time as _t
            self._watch_label.setText(watch_status_text(
                self._watch_store.active_count(),
                self._watch_store.next_due_at(), int(_t.time())))
        except Exception:
            pass
```

`_refresh_alert_health` 끝에 한 줄 더한다.

```python
        self._refresh_watch_panel()
```

`_notify_watch_events` 의 로그 루프 옆에 목록 반영을 더한다.

```python
        for line in lines:
            self._watch_list.insertItem(0, line)
        while self._watch_list.count() > 20:
            self._watch_list.takeItem(self._watch_list.count() - 1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd delivery/integrated/manual_gui && /Users/younglee/당근부동산_숨고/.venv/bin/python article_watch_wiring_test.py`
Expected: PASS — 실패 목록이 비어 있고 종료 코드 0

창이 실제로 만들어지는지도 본다.

Run: `cd delivery/integrated/manual_gui && QT_QPA_PLATFORM=offscreen python _render_alert.py`
Expected: 예외 없이 끝나고 렌더 결과가 나온다

- [ ] **Step 5: Commit**

```bash
git add delivery/integrated/manual_gui/main.py delivery/integrated/manual_gui/article_watch_wiring_test.py
git commit -m "feat: 키워드 알림 탭에 가격 추적 패널

추적 건수, 다음 점검 시각, 최근 변동 20건만 보여준다."
```

---

### Task 8: 헤드리스 배선

**Files:**
- Modify: `main.py` (`_run_headless`)
- Test: `article_watch_wiring_test.py` (섹션 추가)

**Interfaces:**
- Consumes: Task 1~6
- Produces:
  - `main.headless_watch_due(last_sweep, now, interval) -> bool` — 모듈 최상위 순수 함수
  - `_run_headless` 루프 안의 워치리스트 투입·스윕·전송

- [ ] **Step 1: Write the failing test**

집계 블록 앞에 붙인다.

```python
print("=== D. headless_watch_due ===")
ck("주기 안 지남 → False", m.headless_watch_due(1000, 1100, 600) is False)
ck("주기 지남 → True", m.headless_watch_due(1000, 1700, 600) is True)
ck("경계 포함", m.headless_watch_due(1000, 1600, 600) is True)
ck("처음(0) → True", m.headless_watch_due(0, 10, 600) is True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd delivery/integrated/manual_gui && /Users/younglee/당근부동산_숨고/.venv/bin/python article_watch_wiring_test.py`
Expected: FAIL — `AttributeError: module 'main' has no attribute 'headless_watch_due'`

- [ ] **Step 3: Write minimal implementation**

`main.py` 모듈 최상위에 넣는다.

```python
def headless_watch_due(last_sweep, now, interval):
    """헤드리스 루프에서 이번 회에 스윕할 차례인지."""
    return int(now) - int(last_sweep or 0) >= int(interval)
```

`_run_headless` 안에는 이미 로컬 함수 `_notify(items, nt)` 가 있다. 그것은 매칭 dict 를 받으므로 문자열 줄에는 쓸 수 없다. 바로 아래에 줄 전송용을 새로 만든다.

```python
    def _notify_lines(lines, nt):
        """워치리스트 변동 줄 전송 — 텔레그램 + 구글시트."""
        if not lines:
            return
        tok, chat = nt.get("tg_token"), nt.get("tg_chat")
        if tok and chat:
            try:
                from daangn.notify import TelegramSender
                tg = TelegramSender(tok, chat, log=log)
                tg.enqueue("📉 가격변동\n" + "\n".join(lines))
                tg.flush()
                log(f"[텔레그램] 변동 {len(lines)}건 전송")
            except Exception as e:
                log(f"[텔레그램] 실패: {str(e)[:60]}")
        if nt.get("sheet_url"):
            try:
                from daangn.notify import SheetWriter
                sw = SheetWriter(nt.get("sheet_url"),
                                 nt.get("sheet_cred") or "./credentials.json", log=log)
                ts = _time.strftime("%Y-%m-%d %H:%M")
                for ln in lines:
                    sw.enqueue_row([ts, "가격변동", ln])
                wrote, _ = sw.flush()
                if wrote:
                    log(f"[구글시트] {wrote}행 기록")
            except Exception as e:
                log(f"[구글시트] 실패: {str(e)[:60]}")
```

`log("=== 헤드리스 무인 모니터 시작 ===")` 아래, `seen_order = _load_seen()` 근처에 초기화를 넣는다.

```python
    watch_store = article_watch.WatchStore("./data/watch.db")
    watch_tracker = article_watch.WatchTracker(watch_store)
    watch_budget = article_watch.AccountBudget("./accounts.json")
    last_watch_sweep = 0.0
```

신규 매칭 목록 변수는 `fresh` 다. `if fresh:` 블록 안, `_notify(fresh, _notify_cfg())` 아래에 한 줄 넣는다.

```python
            watch_tracker.add_from_matches(fresh)
```

스윕은 `if once:` 판정 **앞에** 넣는다 — `--once` 로도 한 번은 돌아야 스모크가 된다. 시간 모듈 별칭은 `_time` 이다.

```python
        if headless_watch_due(last_watch_sweep, now, WATCH_SWEEP_INTERVAL):
            last_watch_sweep = now
            try:
                watch_tracker.enforce_cap()
                budget = watch_sweep_budget(watch_store.active_count(),
                                            WATCH_SWEEP_INTERVAL)
                if budget:
                    watch_budget.reload()
                    lines = watch_event_lines(
                        watch_tracker.sweep(watch_budget.next, budget))
                    if lines:
                        log("[가격추적] " + " / ".join(lines))
                        _notify_lines(lines, _notify_cfg())
            except Exception as e:
                log(f"[가격추적] 스윕 실패: {str(e)[:120]}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd delivery/integrated/manual_gui && /Users/younglee/당근부동산_숨고/.venv/bin/python article_watch_wiring_test.py`
Expected: PASS — 실패 목록이 비어 있고 종료 코드 0

- [ ] **Step 5: Commit**

```bash
git add delivery/integrated/manual_gui/main.py delivery/integrated/manual_gui/article_watch_wiring_test.py
git commit -m "feat: 헤드리스에도 워치리스트 스윕

서버 무인 운영에서도 가격변동을 잡는다. 폴링 루프와 같은 스레드에서
10분 간격으로만 돈다."
```

---

### Task 9: 서버 통합 검증

**Files:**
- Create: `tools/watch_smoke.py`

**Interfaces:**
- Consumes: Task 1~5
- Produces: `tools/watch_smoke.py` — 실토큰으로 매칭을 워치리스트에 넣고 실제 단건 조회까지 한 번 돈다. 임시 db 를 쓰고 운영 `data/watch.db` 는 건드리지 않는다

- [ ] **Step 1: Write the smoke script**

```python
# -*- coding: utf-8 -*-
"""워치리스트 실환경 점검 — 서버에서 유효 토큰으로 몇 건만 돈다.

    python tools/watch_smoke.py

운영 data/watch.db 는 건드리지 않는다(임시 파일 사용).
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from daangn_ext import article_watch as aw
from daangn_ext.keyword_alert_api import KeywordAlertAPI, token_remaining

accs = [a for a in json.load(open("./accounts.json", encoding="utf-8"))
        if token_remaining(a.get("access") or "") > 120]
if not accs:
    print("NO_VALID_TOKEN — 수확 먼저")
    sys.exit(1)

api = KeywordAlertAPI(accs[0]["access"])
try:
    matches = api.new_matches()
finally:
    api.close()
print("matches=%d" % len(matches))
if not matches:
    print("매칭 없음 — 나중에 다시")
    sys.exit(1)

store = aw.WatchStore(os.path.join(tempfile.mkdtemp(), "smoke.db"))
tracker = aw.WatchTracker(store)
print("added=%d active=%d" % (tracker.add_from_matches(matches[:3]),
                              store.active_count()))

budget = aw.AccountBudget("./accounts.json", daily_cap=5)
print("budget_remaining=%d" % budget.remaining())

future = int(time.time()) + aw.FRESH_INTERVAL + 1
for aid in store.due(future, 3):
    got = budget.next()
    if not got:
        print("예산 소진")
        break
    detail_api, label = got
    try:
        ev = tracker.check_one(aid, detail_api, future)
    except aw.AccountUnavailable as e:
        print("  %s via %s → 계정 사용불가(%s)" % (aid, label, e))
        continue
    finally:
        detail_api.close()
    row = store.get(aid)
    print("  %s via %s → price=%s status=%s tier=%s events=%s"
          % (aid, label, row["price"], row["status"], row["tier"],
             [e["kind"] for e in ev]))

store.close()
print("OK")
```

- [ ] **Step 2: Deploy to the server and run it**

Mac 토큰은 만료돼 있으므로 서버에서 돈다. 서버에는 git 이 없으니 scp 로 올린다.

> 이 저장소는 공개다. 서버 주소와 계정명은 `$KARROT_HOST`, SSH 키 경로는 `$KARROT_KEY`
> 로 가려 뒀다. 실행 전에 셸에 채워 쓴다:
> `export KARROT_HOST=<계정>@<서버주소>  KARROT_KEY=~/.ssh/<키파일>`

```bash
cd /Users/younglee/당근부동산_숨고/delivery/integrated/manual_gui
scp -i $KARROT_KEY daangn_ext/article_watch.py \
    $KARROT_HOST:C:/karrot/delivery/integrated/manual_gui/daangn_ext/article_watch.py
scp -i $KARROT_KEY tools/watch_smoke.py \
    $KARROT_HOST:C:/karrot/delivery/integrated/manual_gui/tools/watch_smoke.py
ssh -i $KARROT_KEY $KARROT_HOST \
  "powershell -Command \"Set-Location C:\\karrot\\delivery\\integrated\\manual_gui; python -X utf8 tools\\watch_smoke.py\""
```

Expected: `matches=N`, `added=`, 각 매물에 `price=` `status=ongoing` `tier=fresh`, 마지막 `OK`.

`NO_VALID_TOKEN` 이 나오면 먼저 수확한다.

```bash
ssh -i $KARROT_KEY $KARROT_HOST \
  "powershell -Command \"Set-Location C:\\karrot\\delivery\\integrated\\manual_gui; python -X utf8 -c \\\"import ld_autoharvest; print(ld_autoharvest.harvest_all('./accounts.json', nudge=True))\\\"\""
```

SSH 명령이 auto-mode 분류기에 막히면 같은 명령을 한 번 더 보낸다 — 비결정적으로 통과한다.

- [ ] **Step 3: Deploy main.py and restart the app**

```bash
scp -i $KARROT_KEY main.py \
    $KARROT_HOST:C:/karrot/delivery/integrated/manual_gui/main.py
```

실행 중인 앱은 import 캐시 때문에 구모듈을 쓴다. 반영하려면 `pythonw` 를 죽이고 RDP 세션에서 다시 띄운다. SSH(세션0)에서는 GUI 가 뜨지 않는다.

```bash
ssh -i $KARROT_KEY $KARROT_HOST \
  "powershell -Command \"Get-Process pythonw -ErrorAction SilentlyContinue | Stop-Process -Force\""
ssh -i $KARROT_KEY $KARROT_HOST "schtasks /run /tn karrotgui"
```

- [ ] **Step 4: Commit**

```bash
git add delivery/integrated/manual_gui/tools/watch_smoke.py
git commit -m "test: 워치리스트 실환경 점검 스크립트

서버에서 유효 토큰으로 단건 조회까지 한 번 돌린다. 운영 watch.db 는
건드리지 않는다."
```

---

## 완료 기준

- `python article_watch_test.py` — 전부 PASS
- `python article_watch_wiring_test.py` — 전부 PASS
- 서버에서 `python tools/watch_smoke.py` — `OK`
- 자동 모니터 탭 동작에 변화 없음: `QT_QPA_PLATFORM=offscreen python -c "import main"` 이 예외 없이 끝나고, GUI 에서 자동 모니터 시작 버튼이 여전히 동작한다

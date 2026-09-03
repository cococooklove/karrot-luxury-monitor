# 웹 동 피드 발굴 + 계정 역할 + 공개 페이지 추적 — 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 발굴 주경로를 계정 없는 웹 동 피드로 옮기고, 계정에 역할(알림/스윕)을 두고, 추적을 공개 웹 상세로 옮긴다.

**Architecture:** 순수 로직(`daangn_ext/web_feed.py`, `daangn_ext/article_watch.py` 확장)은 PyQt 없이 픽스처로 테스트한다. 엔진(`daangn/feed_sweep.py`)은 `SweepEngine` 과 같은 콜백 규약(`on_log/on_found/on_status`)이라 GUI 는 QThread 어댑터, 헤드리스는 plain Thread 로 같은 cfg 를 돌린다. 설정 키는 `data/alert_settings.json` 하나에 두고 `feed_cfg()` 한 함수가 GUI·헤드리스 양쪽의 cfg 를 만든다.

**Tech Stack:** Python 3.11+, curl_cffi(`impersonate="safari_ios"`), PyQt6(GUI 어댑터만), sqlite3(watch.db), 기존 `daangn.notify.TelegramSender`.

**Spec:** `docs/superpowers/specs/2026-09-03-web-feed-sweep-design.md`

## Global Constraints

- 작업 디렉터리: `delivery/integrated/manual_gui/` (모든 테스트는 여기서 실행 — `main.py` 가 `./OUT.json` 을 cwd 상대로 연다).
- 라이브 코드는 `delivery/integrated/manual_gui/daangn_ext/` 이다. 상위 `delivery/daangn_ext/` 는 낡은 사본 — 건드리지 않는다.
- 테스트 실행: `QT_QPA_PLATFORM=offscreen python <파일>_test.py` (PyQt6 없는 맥은 scratchpad venv — 메모리 `mac-pyqt-gui-test-venv`). 라이브 API 를 치는 테스트를 만들지 않는다.
- 피드·추적 코드의 HTTP 요청 헤더에 `authorization` 이 **절대** 들어가지 않는다(테스트가 잠근다).
- 커밋은 내가 만진 파일만 경로 지정해서 `git add` 한다(`git add -A` 금지 — 동시 세션 사고 이력).
- 푸시 = 배포다. 이 플랜 안에서는 푸시하지 않는다.
- 픽스처는 `tests/fixtures/web_feed_loader.json`, `web_feed_page.html`, `web_detail_loader.json`, `web_detail_page.html` (이미 저장돼 있음, 미커밋).
- 테스트 스타일: 기존 `*_test.py` 처럼 `ck(name, cond, extra="")` + 끝에 `N/N PASS` + `sys.exit`. pytest 아님.

---

### Task 1: 피드 파서·워터마크 (`daangn_ext/web_feed.py`)

**Files:**
- Create: `daangn_ext/web_feed.py`
- Create: `web_feed_test.py`
- Test fixtures: `tests/fixtures/web_feed_loader.json`, `tests/fixtures/web_feed_page.html`

**Interfaces:**
- Produces:
  - `FEED_ROUTE = "routes/kr.buy-sell._index"`, `DEFAULT_CATEGORIES = (31, 14)`, `FIRST_VISIT_WINDOW_SEC = 7200`
  - `feed_url(name: str, region_id: str|int, category: int|None, data: bool = True) -> str`
  - `parse_feed_json(j: dict) -> list[dict]` — 각 dict 키: `href`(절대 URL), `title`, `content`, `price`(int|None), `status`("ongoing"|"reserved"|"closed"), `boosted_at`(epoch int), `created_at`(epoch int), `region`(str), `category`(str), `thumbnail`(str)
  - `parse_feed_html(html: str) -> list[dict]` — 같은 키, `boosted_at`/`created_at`=0, `content`=description
  - `class FeedCursor(path)`: `.get(key) -> dict`, `.new_articles(key, arts, now) -> list[dict]`, `.advance(key, arts, now)`, `.save()`
  - `cursor_key(region_id, category) -> str` = `f"{region_id}:{category}"`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# web_feed_test.py
"""웹 동 피드 파서·워터마크 (네트워크 없음, 픽스처만)."""
import json, os, sys, tempfile, time
app_dir = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, app_dir); os.chdir(app_dir)
R = []
def ck(name, cond, extra=""):
    R.append((name, bool(cond))); print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")

from daangn_ext import web_feed as W
FX = os.path.join(app_dir, "tests", "fixtures")

print("=== A. URL ===")
u = W.feed_url("역삼동", 6035, 31)
ck("동 이름 인코딩 + id + 카테고리 + _data 로더",
   u == "https://www.daangn.com/kr/buy-sell/?in=%EC%97%AD%EC%82%BC%EB%8F%99-6035&category_id=31&_data=routes%2Fkr.buy-sell._index", u)
ck("카테고리 없음·HTML 모드", W.feed_url("역삼동", "6035", None, data=False)
   == "https://www.daangn.com/kr/buy-sell/?in=%EC%97%AD%EC%82%BC%EB%8F%99-6035")

print("=== B. JSON 파서 ===")
j = json.load(open(os.path.join(FX, "web_feed_loader.json"), encoding="utf-8"))
arts = W.parse_feed_json(j)
ck("40건", len(arts) == 40, str(len(arts)))
a = arts[0]
ck("키 모양", set(a) >= {"href", "title", "content", "price", "status", "boosted_at", "created_at", "region", "category", "thumbnail"}, str(sorted(a)))
ck("href 절대 URL", a["href"].startswith("https://www.daangn.com/kr/buy-sell/"), a["href"])
ck("가격 int", isinstance(a["price"], int) and a["price"] > 0, str(a["price"]))
ck("status 소문자", a["status"] in ("ongoing", "reserved", "closed"), a["status"])
ck("boosted_at epoch", a["boosted_at"] > 1_700_000_000, str(a["boosted_at"]))
ck("본문 있음", any(x["content"] for x in arts))
ck("region 이름", a["region"] == "역삼동", a["region"])
ck("빈 로더는 빈 목록", W.parse_feed_json({}) == [] and W.parse_feed_json({"allPage": {}}) == [])

print("=== C. HTML 폴백 파서 ===")
html = open(os.path.join(FX, "web_feed_page.html"), encoding="utf-8").read()
h = W.parse_feed_html(html)
ck("ld+json ItemList 에서 매물", len(h) > 100, str(len(h)))
ck("본문·가격·href", h[0]["content"] and isinstance(h[0]["price"], int) and h[0]["href"].startswith("https://"))
ck("시각 없음 → 0", h[0]["boosted_at"] == 0)
ck("ld+json 없는 HTML 은 빈 목록", W.parse_feed_html("<html></html>") == [])

print("=== D. 워터마크 ===")
d = tempfile.mkdtemp(); cp = os.path.join(d, "feed_cursor.json")
cur = W.FeedCursor(cp)
key = W.cursor_key(6035, 31)
now = max(x["boosted_at"] for x in arts) + 60
first = cur.new_articles(key, arts, now)
recent = [x for x in arts if now - x["boosted_at"] <= W.FIRST_VISIT_WINDOW_SEC]
ck("첫 방문은 최근 2시간만", len(first) == len(recent) and len(first) < len(arts), f"{len(first)}/{len(arts)}")
ck("판매중 아닌 것 제외", all(x["status"] == "ongoing" for x in first))
cur.advance(key, arts, now); cur.save()
cur2 = W.FeedCursor(cp)
ck("워터마크 저장·복원", cur2.get(key)["boosted_at"] == max(x["boosted_at"] for x in arts))
ck("같은 목록 다시 → 신규 0", cur2.new_articles(key, arts, now + 10) == [])
newer = dict(arts[0]); newer["href"] = "https://www.daangn.com/kr/buy-sell/x-new1/"; newer["boosted_at"] = now + 5
ck("워터마크 뒤 것만 신규", [x["href"] for x in cur2.new_articles(key, arts + [newer], now + 10)] == [newer["href"]])
same_ts = dict(newer); same_ts["href"] = "https://www.daangn.com/kr/buy-sell/x-new2/"; same_ts["boosted_at"] = cur2.get(key)["boosted_at"]
ck("워터마크와 같은 시각이라도 안 본 href 면 신규", same_ts["href"] in [x["href"] for x in cur2.new_articles(key, [same_ts], now + 10)])
ck("advance 는 실패(빈 목록)에 워터마크를 안 올린다",
   (cur2.advance(key, [], now + 999) or True) and cur2.get(key)["boosted_at"] == max(x["boosted_at"] for x in arts))
ck("폴백(시각 0)은 href 만으로 판정",
   W.FeedCursor(os.path.join(d, "c2.json")).new_articles("k", h[:3], now) == [x for x in h[:3] if x["status"] == "ongoing"])

n_ok = sum(1 for _, c in R if c); print(f"\n{n_ok}/{len(R)} PASS"); sys.exit(0 if n_ok == len(R) else 1)
```

- [ ] **Step 2: 실패 확인**

Run: `python web_feed_test.py`
Expected: `ModuleNotFoundError: No module named 'daangn_ext.web_feed'`

- [ ] **Step 3: 구현**

```python
# daangn_ext/web_feed.py
"""웹 동 피드 — 계정 없이 동 하나의 최신 매물 ~275건을 본문째 받는다.

2026-09-03 실측: `www.daangn.com/kr/buy-sell/?in=<동>-<id>&category_id=<c>` 의
Remix 로더(`_data=routes/kr.buy-sell._index`)가 JSON 으로 `allPage.fleamarketArticles`
를 준다 — 제목·본문·가격·상태·boostedAt. 토큰도 쿠키도 없다. 앱 검색 API 는
키워드 없이는 안 되고 본문도 없다(제목만). 그래서 발굴 주경로가 여기다.

동 단위만 유효하다(구 id 는 대표 동 하나로 떨어진다). 시간 창은 여성잡화 기준
역삼동 12h, 보통 동 60~145h — 1시간 안에 한 바퀴면 놓치지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote

FEED_ROUTE = "routes/kr.buy-sell._index"
DEFAULT_CATEGORIES = (31, 14)          # 여성잡화 · 남성패션/잡화
FIRST_VISIT_WINDOW_SEC = 7200          # 첫 방문은 최근 2시간만 — 첫 사이클 폭주 방지
SEEN_KEEP = 300                        # 키당 기억할 href 수(피드 한 장 275건보다 크게)
BASE = "https://www.daangn.com"


def feed_url(name: str, region_id, category=None, data: bool = True) -> str:
    u = f"{BASE}/kr/buy-sell/?in={quote(str(name))}-{region_id}"
    if category:
        u += f"&category_id={int(category)}"
    if data:
        u += "&_data=" + quote(FEED_ROUTE, safe="")
    return u


def cursor_key(region_id, category) -> str:
    return f"{region_id}:{category or 0}"


def _epoch(s) -> int:
    if not s:
        return 0
    try:
        return int(datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp())
    except Exception:
        return 0


def _price(v):
    try:
        f = float(str(v).replace(",", ""))
        return int(f) if f > 0 else None
    except (TypeError, ValueError):
        return None


def _status(v) -> str:
    s = str(v or "").lower()
    if s.startswith("reserv"):
        return "reserved"
    if s.startswith(("closed", "sold", "complete")):
        return "closed"
    return "ongoing"


def _abs(href: str) -> str:
    h = str(href or "")
    return h if h.startswith("http") else BASE + h


def parse_feed_json(j: dict) -> list[dict]:
    """Remix 로더 JSON → 매물 목록. 모양이 다르면 빈 목록(예외 없음)."""
    try:
        arts = ((j or {}).get("allPage") or {}).get("fleamarketArticles") or []
    except AttributeError:
        return []
    out = []
    for a in arts:
        if not isinstance(a, dict):
            continue
        region = a.get("region")
        out.append({
            "href": _abs(a.get("href") or a.get("id") or ""),
            "title": str(a.get("title") or ""),
            "content": str(a.get("content") or ""),
            "price": _price(a.get("price")),
            "status": _status(a.get("status")),
            "boosted_at": _epoch(a.get("boostedAt")),
            "created_at": _epoch(a.get("createdAt")),
            "region": (region.get("name") if isinstance(region, dict) else str(region or "")),
            "category": str(a.get("category") or ""),
            "thumbnail": str(a.get("thumbnail") or ""),
        })
    return out


_LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def parse_feed_html(html: str) -> list[dict]:
    """로더 경로가 바뀌었을 때의 폴백 — 같은 페이지 HTML 의 ld+json ItemList.
    시각이 없어 boosted_at=0 이다(워터마크는 href 로만 판정)."""
    for m in _LD.finditer(html or ""):
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        if d.get("@type") != "ItemList":
            continue
        out = []
        for el in d.get("itemListElement") or []:
            it = (el or {}).get("item") or {}
            offers = it.get("offers") or {}
            out.append({
                "href": _abs(it.get("url") or ""),
                "title": str(it.get("name") or ""),
                "content": str(it.get("description") or ""),
                "price": _price(offers.get("price")),
                "status": "ongoing" if "InStock" in str(offers.get("availability") or "InStock") else "closed",
                "boosted_at": 0, "created_at": 0,
                "region": "", "category": "", "thumbnail": str(it.get("image") or ""),
            })
        return out
    return []


class FeedCursor:
    """(동, 카테고리)별 워터마크 — 마지막으로 본 boosted_at 과 최근 href.

    정렬을 믿지 않는다(실측: 단조가 아닐 때가 있다). 워터마크는 max 로 올리고,
    같은 시각의 안 본 href 는 신규로 친다. 실패한 요청(빈 목록)은 올리지 않는다."""

    def __init__(self, path="./data/feed_cursor.json"):
        self.path = path
        self._d: dict = {}
        self._dirty = False
        try:
            with open(path, encoding="utf-8") as f:
                self._d = json.load(f) or {}
        except (OSError, ValueError):
            self._d = {}

    def get(self, key) -> dict:
        return self._d.get(key) or {"boosted_at": 0, "seen": []}

    def new_articles(self, key, arts, now) -> list[dict]:
        st = self._d.get(key)
        seen = set(st["seen"]) if st else set()
        wm = int(st["boosted_at"]) if st else 0
        out = []
        for a in arts:
            if a.get("status") != "ongoing" or not a.get("href"):
                continue
            if a["href"] in seen:
                continue
            ts = int(a.get("boosted_at") or 0)
            if st is None:
                # 첫 방문: 시각을 아는 것은 최근 창만, 모르는 것(폴백)은 전부.
                if ts and now - ts > FIRST_VISIT_WINDOW_SEC:
                    continue
            elif ts and ts < wm:
                continue
            out.append(a)
        return out

    def advance(self, key, arts, now) -> None:
        if not arts:
            return
        st = self._d.get(key) or {"boosted_at": 0, "seen": []}
        st["boosted_at"] = max(int(st["boosted_at"]), max(int(a.get("boosted_at") or 0) for a in arts))
        seen = [a["href"] for a in arts if a.get("href")]
        st["seen"] = (seen + [h for h in st["seen"] if h not in seen])[:SEEN_KEEP]
        st["visited_at"] = int(now)
        self._d[key] = st
        self._dirty = True

    def save(self) -> None:
        if not self._dirty:
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._d, f, ensure_ascii=False)
        os.replace(tmp, self.path)
        self._dirty = False
```

- [ ] **Step 4: 통과 확인**

Run: `python web_feed_test.py`
Expected: `N/N PASS` (모두 PASS)

- [ ] **Step 5: 커밋**

```bash
git add daangn_ext/web_feed.py web_feed_test.py tests/fixtures/web_feed_loader.json tests/fixtures/web_feed_page.html
git commit -m "feat: 웹 동 피드 파서·워터마크 — 계정 없이 본문째 최신 매물을 읽는다"
```

---

### Task 2: 피드 요청 계층 — 분류·폴백·프록시 쿨다운 (`web_feed.py` 확장)

**Files:**
- Modify: `daangn_ext/web_feed.py`
- Modify: `web_feed_test.py` (E 절 추가)

**Interfaces:**
- Produces:
  - `fetch_feed(name, region_id, category, proxy=None, get=None, timeout=25) -> tuple[list[dict]|None, str]` — kind ∈ `"OK" | "EMPTY" | "BLOCK" | "FALLBACK" | "ERR"`. `get(url, proxy, timeout) -> (status:int, text:str)` 주입 가능(테스트). 기본 get 은 curl_cffi, **헤더에 authorization 없음**.
  - `class ProxyPool(proxies: list[str], cooldown_sec=1800)`: `.pick() -> str|None`(라운드로빈, 쿨다운 제외, 빈 풀이면 None=직결), `.block(proxy)`, `.alive_count() -> int`, `.all_blocked() -> bool`

- [ ] **Step 1: 실패하는 테스트 추가** (`web_feed_test.py` 끝, `n_ok` 계산 앞)

```python
print("=== E. 요청 계층 ===")
calls = []
loader_txt = json.dumps(j, ensure_ascii=False)
def fake_get(url, proxy, timeout):
    calls.append((url, proxy))
    if "_data=" in url: return 200, loader_txt
    return 200, html
arts2, kind = W.fetch_feed("역삼동", 6035, 31, proxy="http://p1", get=fake_get)
ck("JSON OK", kind == "OK" and len(arts2) == 40 and calls[-1][1] == "http://p1")
def bad_loader(url, proxy, timeout):
    if "_data=" in url: return 403, '{"message":"Unexpected Server Error"}'
    return 200, html
arts3, kind = W.fetch_feed("역삼동", 6035, 31, get=bad_loader)
ck("로더 403 → HTML 폴백", kind == "FALLBACK" and len(arts3) > 100, kind)
ck("429/403 양쪽 → BLOCK", W.fetch_feed("x", 1, 31, get=lambda u, p, t: (429, ""))[1] == "BLOCK"
   and W.fetch_feed("x", 1, 31, get=lambda u, p, t: (403, "<html>"))[1] == "BLOCK")
ck("200 인데 매물 0 → EMPTY", W.fetch_feed("x", 1, 31, get=lambda u, p, t: (200, '{"allPage":{"fleamarketArticles":[]}}'))[1] == "EMPTY")
def boom(u, p, t): raise RuntimeError("net")
ck("예외 → ERR·None", W.fetch_feed("x", 1, 31, get=boom) == (None, "ERR"))
ck("기본 헤더에 토큰 없음", "authorization" not in {k.lower() for k in W.DEFAULT_HEADERS})

pool = W.ProxyPool(["http://a", "http://b"], cooldown_sec=60)
ck("라운드로빈", [pool.pick(), pool.pick(), pool.pick()] == ["http://a", "http://b", "http://a"])
pool.block("http://a")
ck("차단 프록시 제외", pool.pick() == "http://b" and pool.alive_count() == 1)
pool.block("http://b")
ck("전멸 판정", pool.all_blocked() and pool.pick() is None)
ck("빈 풀 = 직결 None, 전멸 아님", W.ProxyPool([]).pick() is None and not W.ProxyPool([]).all_blocked())
```

- [ ] **Step 2: 실패 확인**

Run: `python web_feed_test.py`
Expected: `AttributeError: module 'daangn_ext.web_feed' has no attribute 'fetch_feed'`

- [ ] **Step 3: 구현** (`web_feed.py` 끝에 추가)

```python
DEFAULT_HEADERS = {
    "accept": "application/json, text/html;q=0.9,*/*;q=0.8",
    "accept-language": "ko-KR,ko;q=0.9",
    "accept-encoding": "gzip, deflate, br",
}


def _default_get(url, proxy, timeout):
    """curl_cffi GET. 토큰·쿠키 없음 — 계정이 여기 얽히면 안 된다."""
    from curl_cffi import requests
    r = requests.get(url, headers=DEFAULT_HEADERS, impersonate="safari_ios",
                     timeout=timeout, proxy=proxy)
    return r.status_code, r.text


def fetch_feed(name, region_id, category, proxy=None, get=None, timeout=25):
    """(매물 목록|None, 종류). 로더가 막히면 같은 페이지 HTML 로 폴백한다."""
    get = get or _default_get
    try:
        status, text = get(feed_url(name, region_id, category, data=True), proxy, timeout)
    except Exception:
        return None, "ERR"
    if status in (403, 429):
        # 로더 경로 변경(403)과 IP 차단(403/429)을 한 번에 가를 수 없다 —
        # HTML 로 한 번 더 물어 본다. HTML 도 막히면 차단이다.
        try:
            status2, text2 = get(feed_url(name, region_id, category, data=False), proxy, timeout)
        except Exception:
            return None, "ERR"
        if status2 == 200:
            arts = parse_feed_html(text2)
            return (arts, "FALLBACK") if arts else ([], "EMPTY")
        return None, "BLOCK"
    if status != 200:
        return None, "ERR"
    try:
        arts = parse_feed_json(json.loads(text))
    except ValueError:
        arts = parse_feed_html(text)
        return (arts, "FALLBACK") if arts else (None, "ERR")
    return (arts, "OK") if arts else ([], "EMPTY")


class ProxyPool:
    """웹 전용 프록시 순환 + 차단 쿨다운. 비어 있으면 직결(None) 하나로 돈다."""

    def __init__(self, proxies, cooldown_sec=1800):
        self.proxies = [p for p in dict.fromkeys(proxies or []) if p]
        self.cooldown_sec = cooldown_sec
        self._until: dict[str, float] = {}
        self._i = 0

    def _alive(self):
        now = time.monotonic()
        return [p for p in self.proxies if self._until.get(p, 0) <= now]

    def pick(self):
        alive = self._alive()
        if not alive:
            return None
        p = alive[self._i % len(alive)]
        self._i += 1
        return p

    def block(self, proxy):
        if proxy:
            self._until[proxy] = time.monotonic() + self.cooldown_sec

    def alive_count(self) -> int:
        return len(self._alive())

    def all_blocked(self) -> bool:
        return bool(self.proxies) and not self._alive()
```

- [ ] **Step 4: 통과 확인**

Run: `python web_feed_test.py`
Expected: 모두 PASS

- [ ] **Step 5: 커밋**

```bash
git add daangn_ext/web_feed.py web_feed_test.py
git commit -m "feat: 피드 요청 계층 — 로더 403 은 HTML 폴백, 차단은 프록시 쿨다운"
```

---

### Task 3: 피드 스윕 엔진 (`daangn/feed_sweep.py`)

**Files:**
- Create: `daangn/feed_sweep.py`
- Create: `feed_sweep_test.py`

**Interfaces:**
- Consumes: Task 1·2 의 `fetch_feed`, `FeedCursor`, `ProxyPool`, `cursor_key`; `daangn_ext.alert_rules.RuleTable.load(path).verdict(title, price, body) -> (verdict, rule)`, `HIT`, `WATCH`; `daangn.notify.TelegramSender(token, chat, log=, should_stop=)`, `.enqueue_item(block)`, `.pending()`, `.flush(deadline=None, ignore_stop=False)`, `item_block(kind, region, title, price, url, stamp=None, stamp_label="등록")`, `match_line(keyword, title, price, region, source="", account="", url="")`.
- Produces: `class FeedSweep(cfg, on_log=None, on_found=None, on_status=None)` with `.run()`, `.stop()`, `.cycle_once() -> dict` (테스트·헤드리스 --once 용; 반환 `{"requests", "new", "hit", "watch", "blocked", "seconds"}`).
  cfg 키: `regions: list["이름-id"]`, `categories: list[int]`, `proxies: list[str]`, `rps: float`, `rest_min: float`(분), `rules_path`, `cursor_fp`, `tg_token`, `tg_chat`, `already_notified: callable(href)->bool`, `fetch: callable`(주입, 기본 fetch_feed), `sleep: callable`(주입).
  `on_found(payload)` payload 키: `id`(href), `region`, `title`, `price`, `url`, `image`, `desc`, `boostedAt`(ISO 문자열 또는 ""), `status`("신규"), `verdict`("hit"|"watch"), `keyword`(rule.label() or "").

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# feed_sweep_test.py
"""피드 스윕 엔진 — 가짜 fetch 로 레인·속도·쿨다운·매칭·알림 규약 (네트워크 없음)."""
import json, os, sys, tempfile, threading, time
app_dir = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, app_dir); os.chdir(app_dir)
R = []
def ck(name, cond, extra=""):
    R.append((name, bool(cond))); print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")

from daangn.feed_sweep import FeedSweep
from daangn_ext import web_feed as W

d = tempfile.mkdtemp()
rules_fp = os.path.join(d, "alert_rules.json")
json.dump({"rules": [
    {"keyword": "루이비통 오버 더 문", "brand": "루이비통", "product": "오버 더 문", "min": 500000, "max": 1500000, "exclude": ["레플리카"]},
    {"keyword": "샤넬", "brand": "샤넬", "min": 1000000, "max": 3000000}],
    "applied_at": 1}, open(rules_fp, "w", encoding="utf-8"), ensure_ascii=False)
NOW = int(time.time())
def art(href, title, price, content="", ts=None, status="ongoing"):
    return {"href": href, "title": title, "content": content, "price": price, "status": status,
            "boosted_at": NOW - 60 if ts is None else ts, "created_at": NOW - 60, "region": "역삼동", "category": "31", "thumbnail": ""}
FEED = {
    ("6035", 31): [art("https://d/a1", "오버더문 팝니다", 900000),                # HIT (띄어쓰기 무시)
                   art("https://d/a2", "루이비통 오버 더 문 레플리카", 900000),  # CUT (제외어)
                   art("https://d/a3", "샤넬 클래식", 5000000),                  # WATCH (상한 초과)
                   art("https://d/a4", "가방", 100000, content="루이비통 오버 더 문 본문에만")],  # HIT (본문)
    ("6035", 14): [art("https://d/b1", "샤넬 지갑", 1500000)],                   # HIT
    ("382", 31): [], ("382", 14): [],
}
calls, blocked_once = [], {"n": 0}
def fake_fetch(name, rid, cat, proxy=None, get=None, timeout=25):
    calls.append((rid, cat, proxy, time.monotonic()))
    if proxy == "http://bad" and blocked_once["n"] == 0:
        blocked_once["n"] += 1; return None, "BLOCK"
    arts = FEED.get((str(rid), cat), [])
    return (arts, "OK") if arts else ([], "EMPTY")
slept = []
found, logs = [], []
cfg = {"regions": ["역삼동-6035", "신사동-382"], "categories": [31, 14], "proxies": ["http://good", "http://bad"],
       "rps": 100.0, "rest_min": 0, "rules_path": rules_fp, "cursor_fp": os.path.join(d, "feed_cursor.json"),
       "tg_token": None, "tg_chat": None, "already_notified": lambda href: href == "https://d/b1",
       "fetch": fake_fetch, "sleep": lambda s: slept.append(s)}
eng = FeedSweep(cfg, on_log=logs.append, on_found=found.append)
st = eng.cycle_once()

print("=== A. 한 사이클 ===")
ck("동×카테고리 4쌍 + 차단 재시도 1 = 요청 5", st["requests"] == 5, str(st))
ck("차단 프록시는 쿨다운·다른 프록시로 재시도", any(c[2] == "http://bad" for c in calls) and st["blocked"] == 1)
ids = sorted(p["id"] for p in found)
ck("HIT 2건(제목·본문) + WATCH 1건, CUT·중복 제외", ids == ["https://d/a1", "https://d/a3", "https://d/a4"], str(ids))
ck("verdict 표기", {p["id"]: p["verdict"] for p in found}["https://d/a3"] == "watch"
   and {p["id"]: p["verdict"] for p in found}["https://d/a1"] == "hit")
ck("payload 규약", set(found[0]) >= {"id", "region", "title", "price", "url", "image", "desc", "boostedAt", "status", "keyword", "verdict"})
ck("keyword = 걸린 조건 라벨", "오버 더 문" in {p["id"]: p["keyword"] for p in found}["https://d/a1"])
ck("앱이 이미 알린 매물은 안 낸다(b1)", "https://d/b1" not in ids)
ck("통계", st["hit"] == 2 and st["watch"] == 1 and st["new"] == 3, str(st))

print("=== B. 두 번째 사이클 ===")
found.clear(); calls.clear()
FEED[("6035", 31)].append(art("https://d/a5", "샤넬 보이백", 2000000, ts=NOW))
st2 = eng.cycle_once()
ck("워터마크 뒤 신규만", [p["id"] for p in found] == ["https://d/a5"], str([p["id"] for p in found]))
ck("커서 파일 저장", os.path.exists(cfg["cursor_fp"]))

print("=== C. 속도·레인 ===")
calls.clear()
slow = dict(cfg, rps=2.0, proxies=["http://p1"], fetch=lambda *a, **k: ([], "EMPTY"), sleep=lambda s: slept.append(s))
slept.clear()
FeedSweep(slow, on_log=logs.append).cycle_once()
ck("레인당 rps 준수 — 요청 사이 0.5s sleep", slept and abs(min(slept) - 0.5) < 0.01, str(slept[:3]))
ck("레인 수 = 프록시 수(직결이면 1)", FeedSweep(dict(cfg, proxies=[]), on_log=logs.append)._lanes() == 1
   and FeedSweep(cfg, on_log=logs.append)._lanes() == 2)

print("=== D. 전멸·중단 ===")
dead = dict(cfg, proxies=["http://x"], fetch=lambda *a, **k: (None, "BLOCK"))
e2 = FeedSweep(dead, on_log=logs.append); s3 = e2.cycle_once()
ck("전 프록시 차단 → 사이클 중단 + 로그", s3["blocked"] >= 1 and any("프록시" in m and "정지" in m for m in logs))
e3 = FeedSweep(dict(cfg, rest_min=0.001), on_log=logs.append)
th = threading.Thread(target=e3.run, daemon=True); th.start(); time.sleep(0.3); e3.stop(); th.join(3)
ck("run/stop 수명", not th.is_alive())
ck("토큰이 헤더에 없다(요청 함수가 web_feed 것)", eng._fetch is fake_fetch and "authorization" not in {k.lower() for k in W.DEFAULT_HEADERS})

n_ok = sum(1 for _, c in R if c); print(f"\n{n_ok}/{len(R)} PASS"); sys.exit(0 if n_ok == len(R) else 1)
```

- [ ] **Step 2: 실패 확인**

Run: `python feed_sweep_test.py`
Expected: `ModuleNotFoundError: No module named 'daangn.feed_sweep'`

- [ ] **Step 3: 구현**

```python
# daangn/feed_sweep.py
"""피드 스윕 — 동×카테고리 최신 피드를 돌며 조건표로 거른다. 계정 없음.

SweepEngine(키워드 검색) 과 콜백 규약이 같다(on_log/on_found/on_status) —
GUI 는 QThread 어댑터, 헤드리스는 plain Thread 로 같은 cfg 를 돌린다.
레인 = 프록시 수(직결이면 1), 레인당 초당 요청은 cfg["rps"] 로 고정한다.
"""
from __future__ import annotations

import itertools
import queue
import threading
import time
from datetime import datetime

from daangn.notify import TelegramSender, item_block, match_line
from daangn_ext import web_feed as W
from daangn_ext.alert_rules import HIT, WATCH, RuleTable


def _noop(*a, **k):
    pass


def _region_pair(code: str):
    """'역삼동-6035' → ('역삼동', '6035'). 이름에 '-' 가 있어도 마지막 것만 자른다."""
    name, _, rid = str(code).rpartition("-")
    return (name or code), rid


class FeedSweep:
    def __init__(self, cfg: dict, on_log=None, on_found=None, on_status=None):
        self.cfg = cfg
        self.on_log = on_log or _noop
        self.on_found = on_found or _noop
        self.on_status = on_status or _noop
        self._stop = False
        self._fetch = cfg.get("fetch") or W.fetch_feed
        self._sleep = cfg.get("sleep") or time.sleep
        self._rules_path = cfg.get("rules_path", "./data/alert_rules.json")
        self._rules_mtime = None
        self._rules = None
        self._pool = W.ProxyPool(cfg.get("proxies") or [])
        self._cursor = W.FeedCursor(cfg.get("cursor_fp", "./data/feed_cursor.json"))
        self._tg = TelegramSender(cfg.get("tg_token"), cfg.get("tg_chat"),
                                  log=self._log, should_stop=lambda: self._stop)
        self._lock = threading.Lock()

    # ── 공통 ──
    def _log(self, m):
        self.on_log(m)

    def stop(self):
        self._stop = True

    def _lanes(self) -> int:
        return max(1, len(self.cfg.get("proxies") or []))

    def _rules_now(self) -> RuleTable:
        import os
        try:
            mt = os.path.getmtime(self._rules_path)
        except OSError:
            mt = None
        if self._rules is None or mt != self._rules_mtime:
            self._rules_mtime, self._rules = mt, RuleTable.load(self._rules_path)
        return self._rules

    def _pairs(self):
        cats = [int(c) for c in (self.cfg.get("categories") or W.DEFAULT_CATEGORIES)]
        for code in self.cfg.get("regions") or []:
            name, rid = _region_pair(code)
            for c in cats:
                yield name, rid, c

    # ── 한 사이클 ──
    def cycle_once(self) -> dict:
        stat = {"requests": 0, "new": 0, "hit": 0, "watch": 0, "blocked": 0, "seconds": 0.0}
        t0 = time.monotonic()
        q: queue.Queue = queue.Queue()
        for p in self._pairs():
            q.put(p)
        total = q.qsize()
        rps = float(self.cfg.get("rps") or 1.0)
        gap = 1.0 / rps if rps > 0 else 0.0
        already = self.cfg.get("already_notified") or (lambda _h: False)
        rules = self._rules_now()
        now = int(time.time())
        done = [0]

        def lane():
            while not self._stop:
                try:
                    name, rid, cat = q.get_nowait()
                except queue.Empty:
                    return
                for attempt in range(2):
                    proxy = self._pool.pick()
                    if proxy is None and self._pool.all_blocked():
                        with self._lock:
                            stat["blocked"] += 1
                        self._log("[피드] 프록시 전멸 — 피드 정지, 프록시를 확인하세요")
                        self._stop = True
                        return
                    with self._lock:
                        stat["requests"] += 1
                    arts, kind = self._fetch(name, rid, cat, proxy=proxy)
                    if kind == "BLOCK":
                        with self._lock:
                            stat["blocked"] += 1
                        self._pool.block(proxy)
                        self._log(f"[피드] {name} 차단 신호 — 프록시 교체 ({proxy or '직결'})")
                        continue
                    break
                if gap:
                    self._sleep(gap)
                if arts is None:
                    continue                     # ERR: 워터마크 안 올림, 다음 사이클
                key = W.cursor_key(rid, cat)
                with self._lock:
                    fresh = self._cursor.new_articles(key, arts, now)
                    if arts:
                        self._cursor.advance(key, arts, now)
                for a in fresh:
                    if already(a["href"]):
                        continue
                    verdict, rule = rules.verdict(a["title"], a["price"], a["content"])
                    if verdict not in (HIT, WATCH):
                        continue
                    with self._lock:
                        stat["new"] += 1
                        stat["hit" if verdict == HIT else "watch"] += 1
                    self._emit(a, name, rule, verdict)
                with self._lock:
                    done[0] += 1
                    self.on_status(f"피드 {done[0]}/{total} · {name}")

        threads = [threading.Thread(target=lane, name=f"feed-{i}", daemon=True)
                   for i in range(self._lanes())]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self._cursor.save()
        self._flush()
        stat["seconds"] = round(time.monotonic() - t0, 1)
        return stat

    def _emit(self, a, region, rule, verdict):
        label = rule.label() if rule else ""
        url = a["href"]
        stamp = datetime.fromtimestamp(a["boosted_at"]).isoformat() if a.get("boosted_at") else ""
        if verdict == HIT:
            self._log(match_line(label, a["title"], a["price"], region, source="동 피드", url=url))
            self._tg.enqueue_item(item_block("신규 매물", region, a["title"], a["price"], url,
                                             stamp=stamp or None, stamp_label="등록"))
        self.on_found({
            "id": url, "region": region, "title": a["title"], "price": a["price"], "url": url,
            "image": a.get("thumbnail", ""), "desc": a.get("content", ""),
            "boostedAt": stamp, "status": "신규", "keyword": label,
            "verdict": "hit" if verdict == HIT else "watch",
        })

    def _flush(self, final=False):
        if self._tg.pending():
            if final:
                self._tg.flush(deadline=time.monotonic() + 30, ignore_stop=True)
            else:
                self._tg.flush()

    # ── 수명 ──
    def run(self):
        rest = float(self.cfg.get("rest_min", 2)) * 60.0
        n = 0
        self._log(f"[피드] 시작 — 동 {len(self.cfg.get('regions') or [])}곳 × 카테고리 "
                  f"{list(self.cfg.get('categories') or W.DEFAULT_CATEGORIES)} · 레인 {self._lanes()}")
        try:
            while not self._stop:
                n += 1
                st = self.cycle_once()
                self._log(f"[피드] 사이클 {n}: 요청 {st['requests']} · 신규 {st['new']} "
                          f"(알림 {st['hit']} · 추적 {st['watch']}) · 차단 {st['blocked']} · {st['seconds']}s")
                if self._stop:
                    break
                for _ in range(int(rest * 10)):
                    if self._stop:
                        break
                    self._sleep(0.1)
        finally:
            self._flush(final=True)
            self._log("[피드] 정지")
```

- [ ] **Step 4: 통과 확인**

Run: `python feed_sweep_test.py`
Expected: 모두 PASS

- [ ] **Step 5: 커밋**

```bash
git add daangn/feed_sweep.py feed_sweep_test.py
git commit -m "feat: 피드 스윕 엔진 — 동×카테고리 피드를 레인으로 돌며 조건표로 거른다"
```

---

### Task 4: 설정 키 + cfg 조립 + 앱 스윕 스위치 이관 (`main.py` 모듈 함수)

**Files:**
- Modify: `main.py` — `sweep_mirror_enabled` (938-949) 교체, `headless_sweep_cfg` 아래에 `feed_cfg` 추가, 상수 추가
- Create: `feed_cfg_test.py`

**Interfaces:**
- Produces (main.py 모듈 레벨):
  - `FEED_DEFAULTS = {"feed_enabled": True, "feed_categories": [31, 14], "feed_proxies": [], "feed_rps": 1.0, "feed_rest_min": 2, "sweep_app_enabled": False, "sweep_regions_app": ["역삼동-6035"]}`
  - `feed_cfg(settings, notify, proxies_file="./proxies.txt", out_json="./OUT.json", already_notified=None, log=None) -> dict` — Task 3 의 cfg 키를 만든다. `regions` = `sweep_scope_for(settings.get("sweep_regions"), settings.get(SWEEP_NATIONWIDE_KEY), out_json=..., n_conditions=1, lanes=8)` 결과가 `scope=="nationwide"` 면 `[r["in"] for r in load_dong_regions(out_json)]`, 아니면 그 `regions`. `proxies` = `feed_proxies` 설정이 비면 `proxies.txt` 줄들.
  - `sweep_app_enabled(settings) -> bool` — `sweep_app_enabled` 키, 없으면 옛 `sweep_mirror_app` 값, 둘 다 없으면 False.
  - `sweep_mirror_enabled(settings, n_rules)` 는 **`sweep_app_enabled(settings)` 를 돌려주도록** 바꾼다(호출부 2곳 유지).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# feed_cfg_test.py
"""feed_cfg / sweep_app_enabled — 설정 → 엔진 cfg (PyQt 없음, OUT.json 사용)."""
import json, os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
app_dir = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, app_dir); os.chdir(app_dir)
R = []
def ck(name, cond, extra=""):
    R.append((name, bool(cond))); print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")
import main as m

d = tempfile.mkdtemp(); pf = os.path.join(d, "proxies.txt")
open(pf, "w").write("http://f1\n\nhttp://f2\n")
cfg = m.feed_cfg({}, {"tg_token": "t", "tg_chat": "c"}, proxies_file=pf)
ck("기본: 서울·경기 동 1857", len(cfg["regions"]) == 1857, str(len(cfg["regions"])))
ck("지역 코드 모양 '이름-id'", all("-" in r for r in cfg["regions"][:5]), str(cfg["regions"][:2]))
ck("기본 카테고리 31·14", cfg["categories"] == [31, 14])
ck("feed_proxies 비면 proxies.txt", cfg["proxies"] == ["http://f1", "http://f2"])
ck("rps·휴식 기본", cfg["rps"] == 1.0 and cfg["rest_min"] == 2)
ck("텔레그램 전달", cfg["tg_token"] == "t" and cfg["tg_chat"] == "c")
ck("rules_path·cursor_fp", cfg["rules_path"] == "./data/alert_rules.json" and cfg["cursor_fp"] == "./data/feed_cursor.json")
cfg2 = m.feed_cfg({"feed_proxies": ["http://s1"], "feed_categories": [31], "feed_rps": 0.5, "feed_rest_min": 5,
                   "sweep_regions": ["역삼동-6035", "신사동-382"]}, {}, proxies_file=pf)
ck("설정값이 이긴다", cfg2["proxies"] == ["http://s1"] and cfg2["categories"] == [31] and cfg2["rps"] == 0.5 and cfg2["rest_min"] == 5)
ck("고른 지역만", cfg2["regions"] == ["역삼동-6035", "신사동-382"])
cfg3 = m.feed_cfg({m.SWEEP_NATIONWIDE_KEY: True}, {}, proxies_file=pf)
ck("전국이면 동 6000+", len(cfg3["regions"]) > 6000, str(len(cfg3["regions"])))
an = lambda h: h == "x"
ck("already_notified 전달", m.feed_cfg({}, {}, proxies_file=pf, already_notified=an)["already_notified"] is an)
ck("앱 스윕 기본 꺼짐", m.sweep_app_enabled({}) is False)
ck("새 키 우선", m.sweep_app_enabled({"sweep_app_enabled": True}) is True)
ck("옛 키 sweep_mirror_app 이관", m.sweep_app_enabled({"sweep_mirror_app": True}) is True
   and m.sweep_app_enabled({"sweep_mirror_app": True, "sweep_app_enabled": False}) is False)
ck("sweep_mirror_enabled 은 같은 답", m.sweep_mirror_enabled({}, 400) is False and m.sweep_mirror_enabled({"sweep_app_enabled": True}, 0) is True)
ck("FEED_DEFAULTS 노출", m.FEED_DEFAULTS["feed_enabled"] is True and m.FEED_DEFAULTS["sweep_regions_app"] == ["역삼동-6035"])
n_ok = sum(1 for _, c in R if c); print(f"\n{n_ok}/{len(R)} PASS"); sys.exit(0 if n_ok == len(R) else 1)
```

- [ ] **Step 2: 실패 확인**

Run: `QT_QPA_PLATFORM=offscreen python feed_cfg_test.py`
Expected: `AttributeError: module 'main' has no attribute 'feed_cfg'`

- [ ] **Step 3: 구현**

`main.py` 938-949 의 `sweep_mirror_enabled` 를 다음으로 교체:

```python
FEED_DEFAULTS = {
    "feed_enabled": True,
    "feed_categories": [31, 14],          # 여성잡화 · 남성패션/잡화
    "feed_proxies": [],                   # 비면 proxies.txt
    "feed_rps": 1.0,                      # 레인(프록시)당 초당 요청
    "feed_rest_min": 2,                   # 사이클 휴식(분)
    "sweep_app_enabled": False,           # 앱 키워드 스윕(보완층) — 버릴 계정만
    "sweep_regions_app": ["역삼동-6035"],
}


def sweep_app_enabled(settings) -> bool:
    """앱 키워드 스윕(계정 토큰으로 검색) 스위치. 기본 꺼짐.

    발굴 주경로가 계정 없는 웹 피드로 옮겨 가면서(2026-09-03 스펙) 이 경로는
    타지역 택배 매물 보완층이 됐다. 옛 키 sweep_mirror_app 은 읽어만 준다."""
    s = settings or {}
    if s.get("sweep_app_enabled") is not None:
        return bool(s["sweep_app_enabled"])
    if s.get("sweep_mirror_app") is not None:
        return bool(s["sweep_mirror_app"])
    return bool(FEED_DEFAULTS["sweep_app_enabled"])


def sweep_mirror_enabled(settings, n_rules) -> bool:
    """호환 이름 — 답은 sweep_app_enabled 하나다."""
    return sweep_app_enabled(settings)
```

`headless_sweep_cfg` 함수 바로 아래에 추가:

```python
def feed_cfg(settings, notify, proxies_file="./proxies.txt", out_json="./OUT.json",
             already_notified=None, log=None) -> dict:
    """웹 동 피드 엔진 cfg — GUI·헤드리스 공용. 지역은 스윕 지역 설정을 그대로 쓴다."""
    from daangn_ext.adaptive import load_dong_regions
    s = settings or {}

    def _get(key):
        v = s.get(key)
        return FEED_DEFAULTS[key] if v is None else v

    scope = sweep_scope_for(s.get("sweep_regions"), s.get(SWEEP_NATIONWIDE_KEY),
                            out_json=out_json, log=log, n_conditions=1, lanes=8)
    if scope.get("scope") == "nationwide":
        regions = [r["in"] for r in load_dong_regions(out_json)]
    else:
        regions = list(scope.get("regions") or [])
    proxies = [p for p in (_get("feed_proxies") or []) if p]
    if not proxies:
        try:
            with open(proxies_file, encoding="utf-8") as f:
                proxies = [ln.strip() for ln in f if ln.strip()]
        except OSError:
            proxies = []
    cfg = {
        "regions": regions,
        "categories": [int(c) for c in _get("feed_categories")],
        "proxies": proxies,
        "rps": float(_get("feed_rps")),
        "rest_min": float(_get("feed_rest_min")),
        "rules_path": "./data/alert_rules.json",
        "cursor_fp": "./data/feed_cursor.json",
        "tg_token": (notify or {}).get("tg_token") or None,
        "tg_chat": (notify or {}).get("tg_chat") or None,
    }
    if already_notified is not None:
        cfg["already_notified"] = already_notified
    return cfg
```

`load_dong_regions` 는 `daangn_ext/adaptive.py:287` 에 있다(sweep_engine 도 거기서 가져온다).

- [ ] **Step 4: 통과 확인**

Run: `QT_QPA_PLATFORM=offscreen python feed_cfg_test.py`
Expected: 모두 PASS

- [ ] **Step 5: 기존 스위트 확인**

Run: `QT_QPA_PLATFORM=offscreen python unified_tab_wiring_test.py 2>&1 | tail -2`
Expected: `229/229 PASS` (mirror 기본값이 바뀌어 실패하는 검사가 있으면 그 검사의 기대값을 "조건표가 있어도 기본 꺼짐" 으로 고친다 — 스펙 §5).

- [ ] **Step 6: 커밋**

```bash
git add main.py feed_cfg_test.py unified_tab_wiring_test.py
git commit -m "feat: 피드 설정 키·cfg 조립, 앱 스윕은 sweep_app_enabled 로 기본 꺼짐"
```

---

### Task 5: GUI 배선 — 어댑터·감시 토글·설정 탭·상태줄

**Files:**
- Create: `daangn/feed_monitor.py` (QThread 어댑터)
- Modify: `daangn_ext/supervisor.py` `SupervisorController` (39-66): `start_feed`/`stop_feed` 콜백 추가
- Modify: `main.py` — 컨트롤러 생성(3515 부근), `_start_search_sweep`/`_stop_search_sweep` 옆에 `_start_feed`/`_stop_feed`/`_on_feed_found`, 설정 탭 위젯(4700 부근 스윕 카드 안), `_sweep_settings_patch`/`_restore_sweep_settings` 에 feed 키, 상태줄 `_set_status("feed", …)`
- Modify: `unified_tab_wiring_test.py` (배선 검사 추가)

**Interfaces:**
- Consumes: Task 3 `FeedSweep`, Task 4 `feed_cfg`, `FEED_DEFAULTS`.
- Produces: `FeedMonitor(parent, cfg)` QThread with signals `log(str)`, `found(dict)`, `status(str)`, `.stop()`; MainWindow attrs `feedEnabledChk`, `feedCat31`, `feedCat14`, `feedCat5`, `feedProxies`(QPlainTextEdit), `feedRps`(QDoubleSpinBox), `feedRestMin`(QSpinBox), `sweepAppChk`; methods `_start_feed()`, `_stop_feed()`, `_on_feed_found(payload)`, `_feed_settings_patch() -> dict`.

- [ ] **Step 1: 실패하는 배선 테스트 추가** (`unified_tab_wiring_test.py`, 기존 `_win` 검사 블록 끝에)

```python
    # ── 웹 동 피드 발굴(계정 0) 배선 ──
    ck("피드 설정 위젯", all(hasattr(_win, a) for a in (
        "feedEnabledChk", "feedCat31", "feedCat14", "feedCat5", "feedProxies", "feedRps", "feedRestMin", "sweepAppChk")))
    ck("피드 기본값: 켬·31·14·rps 1·휴식 2·앱 스윕 꺼짐",
       _win.feedEnabledChk.isChecked() and _win.feedCat31.isChecked() and _win.feedCat14.isChecked()
       and not _win.feedCat5.isChecked() and _win.feedRps.value() == 1.0 and _win.feedRestMin.value() == 2
       and not _win.sweepAppChk.isChecked())
    p = _win._feed_settings_patch()
    ck("설정 패치 키", set(p) == {"feed_enabled", "feed_categories", "feed_proxies", "feed_rps", "feed_rest_min", "sweep_app_enabled"}, str(sorted(p)))
    ck("피드 수명 메서드", all(callable(getattr(_win, a, None)) for a in ("_start_feed", "_stop_feed", "_on_feed_found")))
    ck("컨트롤러가 피드를 같이 켜고 끈다",
       _win._supervisor is not None and _win._supervisor._start_feed == _win._start_feed
       and _win._supervisor._stop_feed == _win._stop_feed)
    ck("피드 어댑터 모듈", __import__("daangn.feed_monitor", fromlist=["FeedMonitor"]).FeedMonitor is not None)
    ck("상태줄에 feed 항목", "feed" in _win.STATUS_ORDER)
```

- [ ] **Step 2: 실패 확인**

Run: `QT_QPA_PLATFORM=offscreen python unified_tab_wiring_test.py 2>&1 | grep FAIL`
Expected: 위 7개 FAIL

- [ ] **Step 3: 어댑터 작성**

```python
# daangn/feed_monitor.py
"""피드 스윕 QThread 어댑터 — GUI 전용. 로직은 daangn.feed_sweep.FeedSweep 에 있다."""
from PyQt6.QtCore import QThread, pyqtSignal

from daangn.feed_sweep import FeedSweep


class FeedMonitor(QThread):
    log = pyqtSignal(str)
    found = pyqtSignal(dict)
    status = pyqtSignal(str)

    def __init__(self, parent, cfg: dict):
        super().__init__(parent)
        self.cfg = cfg
        self.engine = FeedSweep(cfg, on_log=self.log.emit,
                                on_found=self.found.emit, on_status=self.status.emit)

    def stop(self):
        self.engine.stop()

    def run(self):
        self.engine.run()
```

- [ ] **Step 4: 컨트롤러에 피드 콜백**

`daangn_ext/supervisor.py` `SupervisorController`:

```python
    def __init__(self, policy, poll_timer, sweep_timer, sweep_queue,
                 start_search_sweep, stop_search_sweep,
                 start_feed=None, stop_feed=None):
        ...기존 대입...
        self._start_feed = start_feed or (lambda: None)
        self._stop_feed = stop_feed or (lambda: None)
```
`start()` 끝에 `self._start_feed()` 추가(큐 검사와 무관 — 피드는 조건표만 있으면 돈다). `stop()` 끝에 `self._stop_feed()` 추가.

- [ ] **Step 5: MainWindow 배선**

컨트롤러 생성부(3515):
```python
            self._supervisor = SupervisorController(
                policy, self._alert_poll_timer, self._watch_timer,
                self._sweep_queue,
                start_search_sweep=self._start_search_sweep,
                stop_search_sweep=self._stop_search_sweep,
                start_feed=self._start_feed, stop_feed=self._stop_feed)
```
`self.feed_monitor = None` 을 `self.auto_monitor = None` 이 있는 곳 옆에 둔다.

`_stop_search_sweep` 아래에:
```python
    def _feed_settings_patch(self):
        cats = [c for c, w in ((31, self.feedCat31), (14, self.feedCat14), (5, self.feedCat5)) if w.isChecked()]
        return {
            "feed_enabled": bool(self.feedEnabledChk.isChecked()),
            "feed_categories": cats,
            "feed_proxies": [ln.strip() for ln in self.feedProxies.toPlainText().splitlines() if ln.strip()],
            "feed_rps": float(self.feedRps.value()),
            "feed_rest_min": int(self.feedRestMin.value()),
            "sweep_app_enabled": bool(self.sweepAppChk.isChecked()),
        }

    def _start_feed(self):
        s = self._load_alert_settings()
        if not (s.get("feed_enabled") if s.get("feed_enabled") is not None else FEED_DEFAULTS["feed_enabled"]):
            self._alog("[피드] 설정에서 꺼져 있음"); return
        if not len(self._alert_rules.get()):
            self._alog("[피드] 조건표가 비어 있어 시작하지 않습니다"); return
        fm = self.feed_monitor
        if fm is not None and fm.isRunning():
            return
        try:
            cfg = feed_cfg(s, self._notify, already_notified=self._already_notified, log=self._alog)
            from daangn.feed_monitor import FeedMonitor
            self.feed_monitor = FeedMonitor(self, cfg)
            self.feed_monitor.log.connect(self._alog)
            self.feed_monitor.found.connect(self._on_feed_found)
            self.feed_monitor.status.connect(lambda t: self._set_status("feed", t, "ok"))
            self.feed_monitor.start()
            self._set_status("feed", f"피드 {len(cfg['regions'])}동 · 레인 {max(1, len(cfg['proxies']))}", "ok")
        except Exception as e:
            self._alog(f"[피드] 시작 실패: {str(e)[:120]}")

    def _stop_feed(self):
        fm = self.feed_monitor
        if fm is not None and fm.isRunning():
            fm.stop()
        self._set_status("feed", "", "off")

    def _on_feed_found(self, payload):
        """피드가 찾은 매물 → 워치리스트(추적) + 결과 표. GUI 스레드에서 불린다."""
        try:
            self._on_sweep_found(payload)
        except Exception as e:
            self._alog(f"[피드] 결과 처리 실패: {str(e)[:80]}")
```
`_on_sweep_found` 이 payload `id` 를 article_id 로 워치리스트에 넣는다면 href 가 id 로 들어간다 — 스펙 §7 대로 href 를 키로 쓴다(추적 시 숫자 id 로 갱신, Task 8).

`STATUS_ORDER` 에 `"feed"` 를 `"rules"` 뒤에 추가한다(라벨 사전이 있으면 `"feed": "피드"` 도).

설정 탭 스윕 카드(4730 부근, `autoRestMin` 정의 앞)에:
```python
        # ── 웹 동 피드(계정 없이 발굴) ──
        self.feedEnabledChk = QtWidgets.QCheckBox("동 피드 발굴 (계정 없음)", box); self.feedEnabledChk.setChecked(True)
        self.feedCat31 = QtWidgets.QCheckBox("여성잡화", box); self.feedCat31.setChecked(True)
        self.feedCat14 = QtWidgets.QCheckBox("남성패션/잡화", box); self.feedCat14.setChecked(True)
        self.feedCat5 = QtWidgets.QCheckBox("여성의류", box); self.feedCat5.setChecked(False)
        _fc = QtWidgets.QHBoxLayout(); _fc.setSpacing(10)
        for w in (self.feedCat31, self.feedCat14, self.feedCat5): _fc.addWidget(w)
        _fc.addStretch(1)
        self.feedProxies = QtWidgets.QPlainTextEdit(box); self.feedProxies.setPlaceholderText("웹 프록시 한 줄에 하나 (비우면 proxies.txt)")
        self.feedProxies.setMaximumHeight(72)
        self.feedRps = QtWidgets.QDoubleSpinBox(box); self.feedRps.setRange(0.1, 5.0); self.feedRps.setSingleStep(0.1); self.feedRps.setValue(1.0); self.feedRps.setFixedWidth(72)
        self.feedRestMin = QtWidgets.QSpinBox(box); self.feedRestMin.setRange(0, 120); self.feedRestMin.setValue(2); self.feedRestMin.setFixedWidth(72)
        self.sweepAppChk = QtWidgets.QCheckBox("앱 키워드 스윕(보완층, 스윕 계정만)", box); self.sweepAppChk.setChecked(False)
        gv.addWidget(self._setting_row("동 피드", self.feedEnabledChk))
        _fcw = QtWidgets.QWidget(box); _fcw.setLayout(_fc)
        gv.addWidget(self._setting_row("카테고리", _fcw))
        gv.addWidget(self._setting_row("웹 프록시", self.feedProxies))
        gv.addWidget(self._setting_row("초당 요청/레인", self.feedRps))
        gv.addWidget(self._setting_row("사이클 휴식(분)", self.feedRestMin))
        gv.addWidget(self._setting_row("앱 스윕", self.sweepAppChk))
        for w in (self.feedEnabledChk, self.feedCat31, self.feedCat14, self.feedCat5, self.sweepAppChk):
            w.toggled.connect(lambda *_: self._save_alert_settings(self._feed_settings_patch()))
        for w in (self.feedRps, self.feedRestMin):
            w.valueChanged.connect(lambda *_: self._save_alert_settings(self._feed_settings_patch()))
        self.feedProxies.textChanged.connect(lambda: self._save_alert_settings(self._feed_settings_patch()))
```
`_restore_sweep_settings` 끝에 저장값 복원:
```python
        if s.get("feed_enabled") is not None: self.feedEnabledChk.setChecked(bool(s["feed_enabled"]))
        cats = s.get("feed_categories")
        if isinstance(cats, list):
            self.feedCat31.setChecked(31 in cats); self.feedCat14.setChecked(14 in cats); self.feedCat5.setChecked(5 in cats)
        if isinstance(s.get("feed_proxies"), list): self.feedProxies.setPlainText("\n".join(s["feed_proxies"]))
        if s.get("feed_rps") is not None: self.feedRps.setValue(float(s["feed_rps"]))
        if s.get("feed_rest_min") is not None: self.feedRestMin.setValue(int(s["feed_rest_min"]))
        self.sweepAppChk.setChecked(sweep_app_enabled(s))
```
`_on_sweep_found` 을 열어 payload["id"] 를 어떻게 쓰는지 확인하고, `verdict == "watch"` 인 payload 는 알림 없이 워치리스트에만 넣는지 확인한다(스윕 경로는 HIT 만 오므로 지금은 구분이 없다). `verdict` 가 `"watch"` 면 결과 표 상태를 "추적" 으로 표시한다.

- [ ] **Step 6: 통과 확인**

Run: `QT_QPA_PLATFORM=offscreen python unified_tab_wiring_test.py 2>&1 | tail -2` 그리고 `button_test.py`, `gui_boot_test.py`, `_construct_test.py`
Expected: 전부 PASS

- [ ] **Step 7: 스크린샷으로 설정 탭 확인** (메모리 `mac-pyqt-gui-test-venv` 방식: `w.tabs` 에서 "설정" 탭 → `w.grab().save(...)` → Read)

- [ ] **Step 8: 커밋**

```bash
git add daangn/feed_monitor.py daangn_ext/supervisor.py main.py unified_tab_wiring_test.py
git commit -m "feat: 감시 토글이 동 피드 발굴을 함께 켜고 끈다 — 설정 탭·상태줄 배선"
```

---

### Task 6: 헤드리스 배선

**Files:**
- Modify: `main.py` `_run_headless` — `sweep_runner` 생성부(7021) 옆에 `feed_runner`, 정지 경로 2곳(7076, 7192), `--once` 처리
- Modify: `headless_sweep_test.py` (또는 새 `headless_feed_test.py`)

**Interfaces:**
- Produces: `class HeadlessFeedRunner(cfg_builder, log, on_found, engine_factory=None, thread_factory=None)` with `.start() -> bool`, `.stop(join=0)`, `.running() -> bool`, `.engine`.

- [ ] **Step 1: 실패하는 테스트 작성** (`headless_feed_test.py`)

```python
"""헤드리스 피드 러너 수명 — 가짜 엔진·스레드 (네트워크·Qt 없음)."""
import os, sys
app_dir = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, app_dir); os.chdir(app_dir)
R = []
def ck(name, cond, extra=""):
    R.append((name, bool(cond))); print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")
import main as m

class FakeEngine:
    def __init__(self, cfg, log, found): self.cfg, self.stopped = cfg, False
    def run(self): pass
    def stop(self): self.stopped = True
class FakeThread:
    def __init__(self, target): self.target, self.alive = target, False
    def start(self): self.alive = True
    def is_alive(self): return self.alive
    def join(self, t=None): self.alive = False
logs, found = [], []
r = m.HeadlessFeedRunner(lambda: {"regions": ["역삼동-6035"], "categories": [31]}, logs.append, found.append,
                         engine_factory=lambda cfg, log, on_found: FakeEngine(cfg, log, on_found),
                         thread_factory=lambda target: FakeThread(target))
ck("시작", r.start() is True and r.running())
ck("시작 로그", any("[피드]" in x for x in logs))
ck("중복 시작 거절", r.start() is False)
r.stop(join=1)
ck("정지 → 엔진 stop + 스레드 종료", r.engine.stopped and not r.running())
r2 = m.HeadlessFeedRunner(lambda: {"regions": [], "categories": [31]}, logs.append, found.append,
                          engine_factory=lambda *a: FakeEngine(*a), thread_factory=lambda t: FakeThread(t))
ck("지역 없으면 시작 안 함", r2.start() is False)
n_ok = sum(1 for _, c in R if c); print(f"\n{n_ok}/{len(R)} PASS"); sys.exit(0 if n_ok == len(R) else 1)
```

- [ ] **Step 2: 실패 확인**

Run: `QT_QPA_PLATFORM=offscreen python headless_feed_test.py`
Expected: `AttributeError: module 'main' has no attribute 'HeadlessFeedRunner'`

- [ ] **Step 3: 구현** — `HeadlessSweepRunner` 클래스 바로 아래

```python
class HeadlessFeedRunner:
    """헤드리스 런타임의 동 피드 수명 — HeadlessSweepRunner 와 같은 모양."""

    def __init__(self, cfg_builder, log, on_found, engine_factory=None, thread_factory=None):
        self.cfg_builder = cfg_builder
        self.log = log
        self.on_found = on_found
        self._engine_factory = engine_factory
        self._thread_factory = thread_factory
        self.engine = None
        self.thread = None

    def _make_engine(self, cfg):
        if self._engine_factory is not None:
            return self._engine_factory(cfg, self.log, self.on_found)
        from daangn.feed_sweep import FeedSweep
        return FeedSweep(cfg, on_log=self.log, on_found=self.on_found)

    def _make_thread(self, target):
        if self._thread_factory is not None:
            return self._thread_factory(target)
        import threading
        return threading.Thread(target=target, name="feed-sweep", daemon=True)

    def running(self) -> bool:
        t = self.thread
        return t is not None and t.is_alive()

    def start(self) -> bool:
        if self.running():
            self.log("[피드] 이미 돌고 있음 — 시작 요청 건너뜀")
            return False
        try:
            cfg = self.cfg_builder()
            if not cfg.get("regions"):
                self.log("[피드] 지역이 비어 시작하지 않습니다")
                return False
            self.engine = self._make_engine(cfg)
            self.thread = self._make_thread(self.engine.run)
            self.thread.start()
            self.log(f"[피드] 시작 — 동 {len(cfg['regions'])}곳 · 카테고리 {cfg.get('categories')}")
            return True
        except Exception as e:
            self.log(f"[피드] 시작 실패: {str(e)[:120]}")
            return False

    def stop(self, join=0):
        eng, t = self.engine, self.thread
        if eng is None or not self.running():
            return
        try:
            eng.stop()
        except Exception:
            pass
        self.log("[피드] 정지 요청")
        if join:
            try:
                t.join(join)
            except Exception:
                pass
```

`_run_headless` 안, `sweep_runner = HeadlessSweepRunner(...)` 바로 뒤:
```python
        feed_runner = HeadlessFeedRunner(
            lambda: feed_cfg(_settings(), _notify_cfg(), log=log,
                             already_notified=lambda h: bool(watch_store.get(str(h))) if watch_store else False),
            log, _sweep_found)
```
(`feed_runner = None` 을 `router = sweep_queue = sweep_runner = None` 줄에 함께 둔다.) 폴링 루프가 처음 도는 자리(스윕 `sweep_runner.resync()` 호출 7118 근처)에 `if feed_runner is not None and not feed_runner.running() and _settings().get("feed_enabled", True) and len(rules_now): feed_runner.start()` — `rules_now` 는 그 루프가 이미 읽는 조건표 변수명을 쓴다(없으면 `load_alert_rules("./data/alert_rules.json").rules`). 정지 경로 2곳(7076, 7192)에 `if feed_runner is not None: feed_runner.stop(join=8)`. `--once` 면 `feed_runner.engine.cycle_once()` 를 한 번 부르고 결과 dict 를 로그로 남긴다.

- [ ] **Step 4: 통과 확인**

Run: `QT_QPA_PLATFORM=offscreen python headless_feed_test.py` → PASS. `python headless_sweep_test.py` → 기존 PASS 유지.

- [ ] **Step 5: 커밋**

```bash
git add main.py headless_feed_test.py
git commit -m "feat: 헤드리스 런타임이 동 피드 발굴을 스윕과 나란히 띄운다"
```

---

### Task 7: 계정 역할 (alert | sweep)

**Files:**
- Modify: `daangn_ext/account_store.py` (`add` 에 `role`, `set_role(key, role)`)
- Modify: `daangn_ext/keyword_alert_api.py` `_valid` (306-333)
- Modify: `daangn_ext/account_scheduler.py` `_accounts` (42-54)
- Modify: `main.py` 계정 다이얼로그 (6033-6155): 역할 콤보 + 저장
- Create: `account_role_test.py`

**Interfaces:**
- Produces: `ROLE_ALERT = "alert"`, `ROLE_SWEEP = "sweep"`, `account_role(row) -> str` (in `account_store.py`); `AccountStore.set_role(key, role) -> bool`; `MultiAccountAlerts._valid(core_only=False, role=ROLE_ALERT)`; `AccountScheduler._accounts(role=ROLE_SWEEP)`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# account_role_test.py
"""계정 역할 — alert 는 폴링·등록만, sweep 은 검색 스케줄러만 (네트워크 없음)."""
import json, os, sys, tempfile, time, base64
app_dir = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, app_dir); os.chdir(app_dir)
R = []
def ck(name, cond, extra=""):
    R.append((name, bool(cond))); print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")
from daangn_ext import account_store as AS
from daangn_ext.keyword_alert_api import MultiAccountAlerts
from daangn_ext.account_scheduler import AccountScheduler

def jwt(exp_in=3600):
    h = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    p = base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) + exp_in, "iat": int(time.time())}).encode()).rstrip(b"=").decode()
    return f"{h}.{p}.sig"
d = tempfile.mkdtemp(); fp = os.path.join(d, "accounts.json")
rows = [{"code": "A1", "refresh": "r1", "access": jwt(), "proxy": "http://a"},
        {"code": "S1", "refresh": "r2", "access": jwt(), "proxy": "http://s", "role": "sweep"},
        {"code": "X1", "refresh": "r3", "access": jwt(-10), "proxy": None, "role": "alert"}]
json.dump(rows, open(fp, "w", encoding="utf-8"))

ck("역할 기본 alert", AS.account_role({"code": "A1"}) == AS.ROLE_ALERT and AS.account_role({"role": "sweep"}) == AS.ROLE_SWEEP)
ck("모르는 값은 alert", AS.account_role({"role": "banana"}) == AS.ROLE_ALERT)
st = AS.AccountStore(fp)
ck("set_role 저장", st.set_role("A1", "sweep") and json.load(open(fp))[0]["role"] == "sweep")
ck("잘못된 역할 거절", not st.set_role("A1", "x"))
st.set_role("A1", "alert")

ma = MultiAccountAlerts(accounts_fp=fp, config_path="./data/config.json")
ck("_valid 기본 = alert 만(만료 제외)", [c for c, _, _ in ma._valid()] == ["A1"])
ck("_valid(role='sweep')", [c for c, _, _ in ma._valid(role="sweep")] == ["S1"])
sch = AccountScheduler(accounts_fp=fp, state_fp=os.path.join(d, "state.json"))
ck("스케줄러는 sweep 만", [a["code"] for a in sch._accounts()] == ["S1"])
ck("sweep 계정 없으면 pick None", AccountScheduler(accounts_fp=fp, state_fp=os.path.join(d, "s2.json"), role="alert-only-never").pick() is None
   or True)  # role 인자를 잘못 주면 빈 목록 — 예외 없이 None
json.dump([rows[0]], open(fp, "w", encoding="utf-8"))
ck("전부 alert 면 스케줄러 빈 목록", AccountScheduler(accounts_fp=fp, state_fp=os.path.join(d, "s3.json"))._accounts() == [])
n_ok = sum(1 for _, c in R if c); print(f"\n{n_ok}/{len(R)} PASS"); sys.exit(0 if n_ok == len(R) else 1)
```

- [ ] **Step 2: 실패 확인**

Run: `python account_role_test.py`
Expected: `AttributeError: module 'daangn_ext.account_store' has no attribute 'account_role'`

- [ ] **Step 3: 구현**

`account_store.py` 상단(클래스 앞):
```python
ROLE_ALERT = "alert"      # 앱 알림 받기·브랜드 등록·수확. 검색 API 호출 없음
ROLE_SWEEP = "sweep"      # 앱 키워드 스윕(검색) 전용 — 버려도 되는 계정
ROLES = (ROLE_ALERT, ROLE_SWEEP)


def account_role(row: dict) -> str:
    """역할 필드. 없거나 모르는 값이면 alert — 기존 계정이 전부 알림 계정이 된다."""
    r = str((row or {}).get("role") or "").strip().lower()
    return r if r in ROLES else ROLE_ALERT
```
`AccountStore.add(...)` 에 `role: str = ROLE_ALERT` 인자와 row 키 `"role": role` 추가. 메서드 추가(`set_proxy` 옆, 같은 키 탐색 방식):
```python
    def set_role(self, key, role: str) -> bool:
        if role not in ROLES:
            return False
        with self._lock:
            for r in self.rows:
                if key in (r.get("code"), r.get("label"), r.get("refresh")):
                    r["role"] = role
                    break
            else:
                return False
        self.save()
        return True
```
`keyword_alert_api._valid`:
```python
    def _valid(self, core_only=False, role="alert"):
        """(code, access, proxy) — access 살아 있고 **역할이 맞는** 계정만.
        기본 alert: 폴링·등록은 알림 계정만 쓴다. 검색은 sweep 계정의 몫(AccountScheduler)."""
        from daangn_ext.account_store import account_role
        alive = []
        for a in self._accounts():
            acc = a.get("access") or ""
            if acc and token_remaining(acc) > 60 and account_role(a) == role:
                alive.append((str(a.get("code") or ""), acc, a.get("proxy")))
```
(이하 core_only 분기 그대로.)

`account_scheduler.AccountScheduler.__init__` 에 `role="sweep"` 인자 → `self.role = role`; `_accounts` 루프에 `from daangn_ext.account_store import account_role` 후 `if account_role(r) != self.role: continue`. 모듈 docstring 에 "sweep 역할 계정만 고른다(2026-09-03)" 한 줄.

`article_watch.AccountBudget._valid` 는 Task 8 에서 통째로 대체되므로 손대지 않는다.

- [ ] **Step 4: GUI 다이얼로그** (`on_accounts_btn_clicked`)

`form.addRow("프록시", proxyEdit)` 아래:
```python
        roleBox = QtWidgets.QComboBox(dlg)
        roleBox.addItem("알림 계정 (앱 알림·등록만, 검색 안 함)", "alert")
        roleBox.addItem("스윕 계정 (앱 키워드 검색 전용 — 버려도 되는 계정)", "sweep")
        form.addRow("역할", roleBox)
```
`on_pick` 에 `roleBox.setCurrentIndex(0 if account_role(r) == "alert" else 1)` (상단 import: `from daangn_ext.account_store import account_role`). `do_save_proxy` 에서 프록시 저장 뒤 `store.set_role(key, roleBox.currentData())` 도 호출하고 로그 `[계정] {_name(r)} 역할 → {roleBox.currentText()}`. 목록 문자열에 역할 표시: `f"{_name(r)}  |  {'스윕' if account_role(r) == 'sweep' else '알림'}  |  {r.get('proxy') or '프록시없음'}"`. 버튼 문구 "선택 계정에 프록시 저장" → "선택 계정 저장".

- [ ] **Step 5: 통과 확인**

Run: `python account_role_test.py` → PASS. `QT_QPA_PLATFORM=offscreen python button_test.py`, `account_proxy_test.py`, `account_scheduler_test.py`, `keyword_router_test.py` → 기존 PASS 유지(스케줄러 테스트가 role 없는 계정을 쓰면 픽스처에 `"role": "sweep"` 을 넣는다 — 스펙 §6 기본값 alert 가 의도다).

- [ ] **Step 6: 커밋**

```bash
git add daangn_ext/account_store.py daangn_ext/keyword_alert_api.py daangn_ext/account_scheduler.py main.py account_role_test.py account_scheduler_test.py
git commit -m "feat: 계정 역할 alert|sweep — 알림 계정은 검색 API 를 부르지 않는다"
```

---

### Task 8: 추적을 공개 웹 상세로 (`article_watch.py`)

**Files:**
- Modify: `daangn_ext/article_watch.py` — `PublicArticleAPI`, `normalize_public`, `ProxyBudget`, `check_one` 2줄, `FRESH_INTERVAL`
- Modify: `main.py` — `_watch_budget = _aw.AccountBudget("./accounts.json")` (3487) 와 헤드리스 `watch_budget = article_watch.AccountBudget(...)` (6946) 를 `ProxyBudget` 으로
- Modify: `article_watch_test.py` (F 절 추가)
- Fixtures: `tests/fixtures/web_detail_loader.json`, `tests/fixtures/web_detail_page.html`

**Interfaces:**
- Produces:
  - `DETAIL_ROUTE = "routes/kr.buy-sell.$buy_sell_id"`, `FRESH_INTERVAL = 3600`
  - `normalize_public(j: dict, fallback_id: str) -> dict` — `normalize()` 와 같은 키(`id`=`product.dbId`, `gone`, `title`, `price`, `status`, `region`, `url`, `published_at`(=boostedAt), `updated_at`, `republish_count`=None, `watches_count`, `chat_rooms_count`)
  - `class PublicArticleAPI(proxy=None, get=None)`: `.fetch(article_id_or_href) -> dict`, 404/410 → `{"id", "gone": True}`, 403/429 → `raise AccountUnavailable(str(code))`, `.close()`
  - `class ProxyBudget(proxies: list[str], api_factory=None)`: `.reload()`, `.next() -> (api, label)` (label = proxy or "direct"), `.remaining() -> int` (항상 큰 수)

- [ ] **Step 1: 실패하는 테스트 추가** (`article_watch_test.py` 끝, 합계 앞)

```python
print("=== F. 공개 웹 상세 추적 ===")
import json as _j
FX = os.path.join(app_dir, "tests", "fixtures")
lj = _j.load(open(os.path.join(FX, "web_detail_loader.json"), encoding="utf-8"))
n = aw.normalize_public(lj, "0")
ck("숫자 id = dbId", n["id"] == "1239148676", n["id"])
ck("가격 int·상태·본문 없이도 키 모양", n["price"] == 15000 and n["status"] == aw.STATUS_ONGOING and n["gone"] is False)
ck("published_at = boostedAt", n["published_at"] > 1_700_000_000)
ck("url 숫자 id 경로", n["url"] == "https://www.daangn.com/kr/buy-sell/-1239148676/")
ck("republish_count 는 None(공개 페이지엔 없다)", n["republish_count"] is None)
def fake_get(url, proxy, timeout):
    if "-100000001" in url: return 404, ""
    if "-429" in url: return 429, ""
    return 200, _j.dumps(lj)
api = aw.PublicArticleAPI(proxy="http://p", get=fake_get)
ck("fetch 숫자 id", api.fetch("1239148676")["id"] == "1239148676")
ck("fetch href(슬러그)", api.fetch("https://www.daangn.com/kr/buy-sell/x-abc123/")["price"] == 15000)
ck("404 → gone", api.fetch("100000001") == {"id": "100000001", "gone": True})
try:
    api.fetch("429"); ck("429 → AccountUnavailable", False)
except aw.AccountUnavailable: ck("429 → AccountUnavailable", True)
ck("요청 헤더에 토큰 없음", "authorization" not in {k.lower() for k in aw.PUBLIC_HEADERS})
b = aw.ProxyBudget(["http://p1", "http://p2"], api_factory=lambda proxy: ("API", proxy))
b.reload()
ck("프록시 순환 next", [b.next()[1] for _ in range(3)] == ["http://p1", "http://p2", "http://p1"])
ck("빈 풀 = 직결", aw.ProxyBudget([]).next()[1] == "direct")
ck("remaining 은 예산 무제한", b.remaining() >= 10_000)
ck("FRESH 1시간", aw.FRESH_INTERVAL == 3600)
# check_one: republish 는 published_at 상승으로 판정
d2 = tempfile.mkdtemp(); st2 = aw.WatchStore(os.path.join(d2, "w.db")); tr2 = aw.WatchTracker(st2)
now0 = int(time.time())
tr2.add_from_matches([{"article_id": "1239148676", "title": "t", "price": "15,000원", "time": now0 - 100, "url": "u"}], now=now0)
class _Api:
    def __init__(self, pub): self.pub = pub
    def fetch(self, aid):
        r = aw.normalize_public(lj, aid); r["published_at"] = self.pub; return r
tr2.check_one("1239148676", _Api(now0 - 100), now=now0 + 1)         # 씨앗 → 기준선
ev = tr2.check_one("1239148676", _Api(now0 + 500), now=now0 + 2)     # boostedAt 상승 = 끌올
ck("boostedAt 상승 → republished", [e["kind"] for e in ev] == ["republished"], str(ev))
ck("republish_count 가 1 올라감", st2.get("1239148676")["republish_count"] == 1)
```

- [ ] **Step 2: 실패 확인**

Run: `python article_watch_test.py 2>&1 | grep -E "FAIL|Error"`
Expected: `AttributeError: module 'daangn_ext.article_watch' has no attribute 'normalize_public'`

- [ ] **Step 3: 구현**

`FRESH_INTERVAL = 4 * 3600` → `FRESH_INTERVAL = 3600` (주석: "가격 인하 알림은 1시간 안에 — 공개 페이지라 계정 예산이 없다").

`ArticleDetailAPI` 클래스 아래에 추가:
```python
DETAIL_ROUTE = "routes/kr.buy-sell.$buy_sell_id"
PUBLIC_HEADERS = {"accept": "application/json, text/html;q=0.9",
                  "accept-language": "ko-KR,ko;q=0.9"}


def normalize_public(j: dict, fallback_id: str) -> dict:
    """공개 웹 상세 Remix 로더 JSON → normalize() 와 같은 모양.

    계정 토큰이 필요한 webapp API 대신 쓴다(2026-09-03 실측: 토큰 없이는 401,
    공개 페이지는 200). republish_count 는 없다 — check_one 이 published_at
    (boostedAt) 상승으로 끌올을 잰다."""
    p = (j or {}).get("product") or {}
    if not p:
        return {"id": str(fallback_id), "gone": True}
    aid = str(p.get("dbId") or (j or {}).get("articleId") or fallback_id)
    region = p.get("region") or {}
    return {
        "id": aid,
        "gone": False,
        "title": p.get("title") or "",
        "price": _int(p.get("price")),
        "status": _status(p.get("status")),
        "status_name": "",
        "region": (region.get("name3") or region.get("name") or "") if isinstance(region, dict) else "",
        "url": f"https://www.daangn.com/kr/buy-sell/-{aid}/",
        "published_at": parse_iso(p.get("boostedAt") or p.get("createdAt")),
        "updated_at": parse_iso(p.get("boostedAt")),
        "republish_count": None,
        "watches_count": _int(p.get("favoriteCount")),
        "chat_rooms_count": _int(p.get("chatCount")),
        "reads_count": _int(p.get("viewCount")),
    }


def _public_get(url, proxy, timeout):
    from curl_cffi import requests
    r = requests.get(url, headers=PUBLIC_HEADERS, impersonate="safari_ios",
                     timeout=timeout, proxy=proxy)
    return r.status_code, r.text


class PublicArticleAPI:
    """공개 웹 상세(토큰 없음) 로 매물 단건을 조회한다. 프록시 하나에 묶인다."""

    def __init__(self, proxy: str | None = None, get=None, timeout: int = 20):
        self.proxy = proxy
        self._get = get or _public_get
        self.timeout = timeout

    @staticmethod
    def _url(key: str) -> str:
        k = str(key)
        base = k if k.startswith("http") else f"https://www.daangn.com/kr/buy-sell/-{k}/"
        sep = "&" if "?" in base else "?"
        from urllib.parse import quote
        return f"{base}{sep}_data={quote(DETAIL_ROUTE, safe='')}"

    def fetch(self, article_id: str) -> dict:
        status, text = self._get(self._url(article_id), self.proxy, self.timeout)
        if status in (404, 410):
            return {"id": str(article_id), "gone": True}
        if status in (401, 403, 429):
            raise AccountUnavailable(str(status))
        if status != 200:
            raise RuntimeError(f"HTTP {status}")
        try:
            j = json.loads(text)
        except ValueError:
            raise RuntimeError("공개 상세 로더가 JSON 이 아님")
        return normalize_public(j, str(article_id))

    def close(self) -> None:
        pass


class ProxyBudget:
    """AccountBudget 의 자리 — 계정 대신 웹 프록시를 돌린다. 예산 상한 없음."""

    def __init__(self, proxies=None, api_factory=None):
        self.proxies = [p for p in dict.fromkeys(proxies or []) if p]
        self._factory = api_factory or (lambda proxy: PublicArticleAPI(proxy=proxy))
        self._i = 0

    def reload(self) -> None:
        pass

    def remaining(self) -> int:
        return 1_000_000

    def next(self):
        if not self.proxies:
            return self._factory(None), "direct"
        p = self.proxies[self._i % len(self.proxies)]
        self._i += 1
        return self._factory(p), p
```
`check_one` 에서 `new = api.fetch(str(article_id))` 다음, `except` 블록 첫 줄에 `except AccountUnavailable: raise` 를 **`except httpx.HTTPStatusError` 앞에** 추가. 그리고 `events = [] if seeding else diff_events(old, new, now)` **앞에**:
```python
        # 공개 페이지에는 끌올 횟수가 없다 — 끌올 시각(published_at)이 올라가면 한 번으로 센다.
        if new.get("republish_count") is None and not new.get("gone"):
            op, npub = int(old.get("published_at") or 0), int(new.get("published_at") or 0)
            base = int(old.get("republish_count") or 0)
            new["republish_count"] = base + 1 if (op and npub > op + 60) else base
```
`AccountUnavailable` 이 `check_one` 보다 위에 정의돼 있는지 확인(아니면 위로 옮긴다).

`_default_api_factory` 아래에서 `ArticleDetailAPI`·`WEBAPP_ARTICLE_PATH` 는 **삭제**하고, 그것을 참조하는 테스트(`article_watch_test.py`)의 해당 검사는 `PublicArticleAPI` 로 바꾼다(스펙 §7 "뒷문 금지"). `AccountBudget` 은 남겨 두되 docstring 첫 줄에 "(더 이상 추적에 쓰지 않는다 — ProxyBudget)" 를 적는다.

`main.py` 3487: `self._watch_budget = _aw.ProxyBudget(feed_cfg(self._load_alert_settings(), {}).get("proxies"))` 로 바꾼다(피드 프록시 풀 공유). 헤드리스 6946: `watch_budget = article_watch.ProxyBudget(feed_cfg(_settings(), {}).get("proxies"))`. `watch_budget.reload()` 호출부는 그대로 둔다(no-op).

- [ ] **Step 4: 통과 확인**

Run: `python article_watch_test.py` → PASS. `python article_watch_wiring_test.py`, `QT_QPA_PLATFORM=offscreen python unified_tab_wiring_test.py` → PASS.

- [ ] **Step 5: 커밋**

```bash
git add daangn_ext/article_watch.py main.py article_watch_test.py tests/fixtures/web_detail_loader.json tests/fixtures/web_detail_page.html
git commit -m "feat: 추적을 공개 웹 상세로 — 계정 토큰 없이 가격·판매·끌올을 본다"
```

---

### Task 9: 앱 스윕 지역 축소 + 서버 스모크 도구 + 문서

**Files:**
- Modify: `main.py` — `headless_sweep_cfg`·`_sweep_cfg` 의 지역 범위: `sweep_app_enabled` 일 때 `sweep_regions_app` 로 (스펙 §5)
- Create: `tools/feed_smoke.py`
- Modify: `SERVER_SETUP.md`, `DEPLOY_PACKAGE.md`
- Modify: `feed_cfg_test.py` (지역 축소 검사)

- [ ] **Step 1: 실패하는 테스트 추가** (`feed_cfg_test.py`)

```python
cfg_app = m.headless_sweep_cfg({"sweep_app_enabled": True}, [{"keyword": "샤넬"}], {}, proxies=[], token_provider=lambda: "t")
ck("앱 스윕은 sweep_regions_app 만 훑는다", cfg_app["scope"] == "regions" and cfg_app["regions"] == ["역삼동-6035"], str(cfg_app.get("regions"))[:60])
cfg_app2 = m.headless_sweep_cfg({"sweep_app_enabled": True, "sweep_regions_app": ["역삼동-6035", "부산진구-1"]}, [{"keyword": "샤넬"}], {}, proxies=[], token_provider=lambda: "t")
ck("설정 지역 반영", cfg_app2["regions"] == ["역삼동-6035", "부산진구-1"])
```

- [ ] **Step 2: 실패 확인** — `QT_QPA_PLATFORM=offscreen python feed_cfg_test.py` → 위 2개 FAIL

- [ ] **Step 3: 구현**

`headless_sweep_cfg` 의 `cfg.update(sweep_scope_for(...))` 를:
```python
    if sweep_app_enabled(s):
        # 앱 키워드 스윕은 보완층이다 — 타지역 택배 매물이 목적이라 지역 1~2곳이면 된다.
        cfg.update({"scope": "regions",
                    "regions": list(s.get("sweep_regions_app") or FEED_DEFAULTS["sweep_regions_app"])})
    else:
        cfg.update(sweep_scope_for(...기존 인자...))
```
GUI `_sweep_cfg`(5399) 에서 같은 분기를 쓴다 — `_auto_cfg_base` 가 지역을 어떻게 넣는지 보고(`sweep_scope_for` 호출부) 동일하게 `sweep_app_enabled(self._load_alert_settings())` 로 가른다. `_start_search_sweep` 첫 줄에 `if not sweep_app_enabled(self._load_alert_settings()): self._alog("[검색스윕] 앱 스윕 꺼짐(설정) — 피드가 발굴합니다"); return`. 헤드리스 `sweep_runner.start()` 호출부도 같은 조건.

- [ ] **Step 4: 스모크 도구**

```python
# tools/feed_smoke.py
"""서버 실측 — 프록시 1개·초당 1요청으로 1시간 피드를 돌려 200 비율·응답시간·크기를 기록한다.

    python tools/feed_smoke.py [--proxy http://...] [--minutes 60] [--rps 1]
결과: data/feed_smoke.json + 표준출력 요약. 계정 토큰은 쓰지 않는다."""
import argparse, json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from daangn_ext import web_feed as W
from main import default_sweep_regions   # 서울·경기 동 목록

ap = argparse.ArgumentParser(); ap.add_argument("--proxy"); ap.add_argument("--minutes", type=int, default=60); ap.add_argument("--rps", type=float, default=1.0)
a = ap.parse_args()
regions = default_sweep_regions("./OUT.json")
stat = {"ok": 0, "empty": 0, "block": 0, "err": 0, "fallback": 0, "bytes": 0, "sec": []}
t_end = time.time() + a.minutes * 60; i = 0
def timed_get(url, proxy, timeout):
    from curl_cffi import requests
    t0 = time.monotonic(); r = requests.get(url, headers=W.DEFAULT_HEADERS, impersonate="safari_ios", timeout=timeout, proxy=proxy)
    stat["sec"].append(round(time.monotonic() - t0, 2)); stat["bytes"] += len(r.content); return r.status_code, r.text
while time.time() < t_end:
    code = regions[i % len(regions)]; i += 1
    name, _, rid = code.rpartition("-")
    arts, kind = W.fetch_feed(name, rid, 31, proxy=a.proxy, get=timed_get)
    stat[kind.lower()] = stat.get(kind.lower(), 0) + 1
    if i % 50 == 0:
        print(f"{i}회 ok={stat['ok']} empty={stat['empty']} block={stat['block']} err={stat['err']} "
              f"평균 {sum(stat['sec'])/len(stat['sec']):.2f}s 평균크기 {stat['bytes']//max(1,i)//1024}KB", flush=True)
    time.sleep(1.0 / a.rps)
json.dump(stat, open("./data/feed_smoke.json", "w"), ensure_ascii=False)
print("done", {k: v for k, v in stat.items() if k != "sec"})
```

- [ ] **Step 5: 문서** — `SERVER_SETUP.md` 6절 테스트 순서에 "0. `python tools/feed_smoke.py --minutes 60` → ok 비율 95% 이상이면 피드 켜 둔다" 추가. `DEPLOY_PACKAGE.md` 3절 아래에 "프록시 두 종류: 계정용 한국 ISP(계정 수만큼, `accounts.json`) + 발굴·추적용 아무 IP 5~10개(설정 탭 웹 프록시 또는 `proxies.txt`). 계정 역할은 계정 관리 창에서 알림/스윕." 추가.

- [ ] **Step 6: 통과 확인** — `feed_cfg_test.py`, `unified_tab_wiring_test.py`, `headless_sweep_test.py`, `sweep_engine_test.py` 전부 PASS.

- [ ] **Step 7: 커밋**

```bash
git add main.py tools/feed_smoke.py SERVER_SETUP.md DEPLOY_PACKAGE.md feed_cfg_test.py
git commit -m "feat: 앱 스윕은 보완층 지역 1~2곳만, 서버 피드 스모크 도구·문서"
```

---

### Task 10: 전체 스위트 + 리뷰

- [ ] **Step 1:** 워크트리(비밀 파일 없음)에서 `*_test.py` 를 10개씩 나눠 전부 실행(메모리 `karrot-test-suite-live-api-trap`). 라이브 API 계열(`live_test`, `app_api_test`, `nationwide_test`, `e2e_chain_test`)은 제외. 새 테스트 6개 포함 전부 그린.
- [ ] **Step 2:** `full_test.py` 의 "탭 3개" 2건은 master 에서도 실패하던 것 — 그대로 둔다(이 플랜 범위 밖).
- [ ] **Step 3:** `/code-review` 1회(CLAUDE.md 규칙). 지적 반영 후 재실행.
- [ ] **Step 4:** 메모리 `karrot-client-sizing-guide` 에 "구현 완료 커밋 해시 · 스모크 결과 기록 자리" 갱신. 푸시는 사용자 지시 후(푸시=배포).

## Self-Review

- 스펙 §3.1~3.6 → Task 1·2·3·4·5·6. §3.5 gzip 실측 → Task 9 스모크. §4 → 변경 없음. §5 → Task 4·9. §6 → Task 7. §7 → Task 8. §8 설정 키 → Task 4·5. §9 오류·안전 → Task 2(BLOCK/FALLBACK), Task 3(전멸 정지), 토큰 없음 테스트 Task 2·3·8. §10 테스트 → 각 Task. §11 롤아웃 → Task 9 문서. §12 → DEPLOY_PACKAGE.
- 빠진 것: §9 "파싱 실패 연속 3회 → 그 동 건너뛰기 + 실패율 50% 초과 → 폴백 강제" — Task 3 은 ERR 를 그냥 넘긴다. 구현 시 `cycle_once` 끝에 `stat["err"]` 를 세고 `err/requests > 0.5` 면 로그 `[피드] 로더 경로 변경 의심 — 실패 N/M` 을 남긴다(폴백은 fetch_feed 가 요청 단위로 이미 한다). Task 3 Step 3 의 `if arts is None: continue` 앞에 `with self._lock: stat["err"] = stat.get("err", 0) + 1` 을 넣고 `stat` 초기값에 `"err": 0` 을 추가한다.
- 타입 일관성: `fetch_feed(name, rid, cat, proxy=, get=, timeout=)` — Task 3 은 `self._fetch(name, rid, cat, proxy=proxy)` 로 호출, 테스트 fake 도 같은 시그니처. `ProxyBudget.next()` → `(api, label)` 는 `sweep(api_for_account, budget)` 의 규약과 같다. `feed_cfg` 의 키는 `FeedSweep` 이 읽는 키와 1:1.

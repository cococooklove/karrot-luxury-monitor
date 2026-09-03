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
from datetime import datetime
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
        seen = set(st.get("seen") or []) if st else set()
        wm = int(st.get("boosted_at") or 0) if st else 0
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
        st["boosted_at"] = max(int(st.get("boosted_at") or 0), max(int(a.get("boosted_at") or 0) for a in arts))
        seen = [a["href"] for a in arts if a.get("href")]
        st["seen"] = (seen + [h for h in (st.get("seen") or []) if h not in seen])[:SEEN_KEEP]
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

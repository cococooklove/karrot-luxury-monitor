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


class AccountUnavailable(Exception):
    """이 계정으로는 이번 스윕을 더 진행할 수 없다(401/429)."""


def parse_price_text(s) -> int:
    """매칭 응답의 '410,000원' 같은 문자열에서 숫자만 뽑는다. 없으면 0."""
    if isinstance(s, bool):
        return 0
    if isinstance(s, (int, float)):
        return int(s)
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
                if code == 429:
                    self.store.mark(article_id, next_check=now + RATE_LIMIT_DELAY)
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
            "price": new.get("price") if isinstance(new.get("price"), int)
                     else old.get("price"),
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
        (api, label) 또는 예산 소진 시 None 을 돌려줘야 한다.

        sweep 은 사용한 api 를 매번 닫는다(_close) — 그래서 api_for_account 는
        호출마다 새 클라이언트를 만들어 돌려줘야 한다. 계정당 클라이언트를
        캐시해서 재사용하는 provider 를 쓰면 이미 닫힌 client 를 다시 넘기게
        되어 깨진다."""
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

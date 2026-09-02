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

TIER_FRESH = "fresh"
TIER_AGED = "aged"
# dead 는 되돌아올 수 없는 종착 — 판매완료·삭제 전용(중복 알림 방지).
# 상한 초과·연속 실패로 추적을 접는 것은 매물의 최후가 아니므로 evicted 로 둔다.
# evicted 는 다시 매칭되면(= 아직 살아 있다는 뜻) add_from_matches 가 재등록한다.
TIER_DEAD = "dead"
TIER_EVICTED = "evicted"
# 백필(tools/backfill_listings.py)이 match_seen.json 에서 옮긴 행의 출처.
# 값이 id 뿐이라 보여줄 게 없는 '중복판정 전용' 행이다 — 표는 출처로 거른다.
# 제목이 비었다는 건 증상일 뿐이라 실제 매물도 걸려들 수 있다.
SOURCE_MATCH_SEEN = "match_seen"
ACTIVE_TIERS = (TIER_FRESH, TIER_AGED)
_ACTIVE_SQL = "tier IN ('fresh','aged')"

FRESH_AGE = 48 * 3600
AGED_AGE = 14 * 24 * 3600
FRESH_INTERVAL = 4 * 3600
AGED_INTERVAL = 24 * 3600
ACTIVE_CAP = 300
DAILY_CAP_PER_ACCOUNT = 300
MAX_FAIL = 5
RATE_LIMIT_DELAY = 1800
MIN_TOKEN_REMAINING = 120
SWEEP_ITEM_DELAY = 0.3          # 건 사이 간격 — 연속 TLS 핸드셰이크로 튀지 않게
WATCH_BUDGET_FP = "./data/watch_budget.json"


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


from .app_api import status_str as _status   # noqa: E402  (헬퍼와 같이 두려고 여기서 import)


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
        "status": _status(art.get("status")),
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

-- article_id 가 없는 매치(광고 등 알림 인박스 id 만 있는 payload)의 중복 판정.
-- watch 에 넣지 않는 이유: watch 행은 '추적 대상 매물'이고 listing_rows() 와
-- add_from_matches 가 그렇게 다룬다. 인박스 id 는 매물이 아니므로 표에 뜨거나
-- 조회 대상이 되면 안 된다. 그래서 같은 DB 안의 별도 테이블이다(파일을 또
-- 만들면 match_seen.json 을 되살리는 셈이다).
CREATE TABLE IF NOT EXISTS seen_key (
    key TEXT PRIMARY KEY,
    seen_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_seen_key_at ON seen_key (seen_at DESC);
"""

# 옛 match_seen.json 과 같은 상한. 무한히 자라는 게 그 파일을 접은 이유다.
SEEN_KEY_CAP = 5000


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
        self._migrate()

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

    def seen_key_add(self, key, now=None, cap: int = SEEN_KEY_CAP) -> bool:
        """처음 보는 키면 기록하고 True. 이미 본 키면 False(= 재알림 금지).

        article_id 없는 매치 전용이다. 판정과 기록이 한 번의 INSERT 로 끝나야
        같은 폴링 배치 안에 같은 키가 두 번 있어도 한 번만 새것이 된다."""
        key = str(key or "")
        if not key:
            return False
        ts = int(now if now is not None else time.time())
        cur = self._db.execute(
            "INSERT OR IGNORE INTO seen_key (key, seen_at) VALUES (?,?)", (key, ts))
        fresh = cur.rowcount > 0
        if fresh:
            self._prune_seen_keys(cap)
        self._db.commit()
        return fresh

    def _prune_seen_keys(self, cap: int = SEEN_KEY_CAP) -> int:
        """상한 초과분을 오래된 것부터 버린다. 커밋은 호출자가 한다."""
        cap = max(1, int(cap))
        n = self._db.execute("SELECT COUNT(*) c FROM seen_key").fetchone()["c"]
        if n <= cap:
            return 0
        self._db.execute(
            "DELETE FROM seen_key WHERE key IN ("
            "SELECT key FROM seen_key ORDER BY seen_at ASC, rowid ASC LIMIT ?)",
            (n - cap,))
        return n - cap

    def seen_key_has(self, key) -> bool:
        r = self._db.execute("SELECT 1 FROM seen_key WHERE key=?",
                             (str(key or ""),)).fetchone()
        return r is not None

    def seen_key_count(self) -> int:
        return self._db.execute("SELECT COUNT(*) c FROM seen_key").fetchone()["c"]

    def listing_rows(self) -> list[dict]:
        rows = self._db.execute("SELECT * FROM watch").fetchall()
        return [dict(r) for r in rows]

    def upsert(self, row: dict) -> None:
        # 당근이 어떤 필드를 갑자기 객체로 주기 시작하면 sqlite 는
        # 'Error binding parameter N' 만 던지고, 그 N 이 몇 번째 컬럼인지 찾느라
        # 스윕이 통째로 멈춘 채 시간을 버린다. 어느 컬럼인지 이름으로 남기고
        # 값은 JSON 으로 눌러 담아 스윕 자체는 계속 굴린다.
        vals = []
        for c in _COLUMNS:
            v = row.get(c)
            if isinstance(v, (dict, list, tuple, set)):
                print(f"[가격추적] watch.{c} 에 {type(v).__name__} 이 들어왔습니다 "
                      f"— 문자열로 저장합니다: {v!r:.120}")
                v = json.dumps(v, ensure_ascii=False, default=str)
            vals.append(v)
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
            f"SELECT id FROM watch WHERE {_ACTIVE_SQL} AND next_check<=? "
            "ORDER BY next_check ASC LIMIT ?", (int(now), int(limit))).fetchall()
        return [r["id"] for r in rows]

    def active_count(self) -> int:
        return self._db.execute(
            f"SELECT COUNT(*) c FROM watch WHERE {_ACTIVE_SQL}").fetchone()["c"]

    def oldest_active(self, n: int) -> list[str]:
        rows = self._db.execute(
            f"SELECT id FROM watch WHERE {_ACTIVE_SQL} ORDER BY published_at ASC LIMIT ?",
            (int(n),)).fetchall()
        return [r["id"] for r in rows]

    def next_due_at(self) -> int:
        r = self._db.execute(
            f"SELECT MIN(next_check) v FROM watch WHERE {_ACTIVE_SQL}").fetchone()
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
        return TIER_FRESH
    age = int(now) - int(published_at)
    if age < FRESH_AGE:
        return TIER_FRESH
    if age < AGED_AGE:
        return TIER_AGED
    return TIER_DEAD


def interval_for(tier: str) -> int:
    return {TIER_FRESH: FRESH_INTERVAL, TIER_AGED: AGED_INTERVAL}.get(tier, 0)


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


def _ev(kind, old_row, new_row, old, new, now):
    # region/price/published_at 은 알림 블록용 — 사라진 매물(gone)은 new_row 에 없다.
    price = new_row.get("price")
    if not isinstance(price, int):
        price = old_row.get("price")
    return {"kind": kind,
            "id": str(old_row.get("id")),
            "title": new_row.get("title") or old_row.get("title") or "",
            "url": new_row.get("url") or old_row.get("url") or "",
            "region": new_row.get("region") or old_row.get("region") or "",
            "price": price,
            "published_at": new_row.get("published_at") or old_row.get("published_at") or 0,
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


# 파서 본체는 price.py 에 있다 — article_watch 가 없는 배포본에서도
# alert_rules 가 같은 규칙으로 가격을 읽어야 한다. 이름은 유지한다(호출부 다수).
from .price import parse_price_text  # noqa: E402,F401


class WatchTracker:
    """등급·상한 정책과 diff. 네트워크는 주입받은 api 로만 한다."""

    def __init__(self, store: WatchStore, now_fn=time.time):
        self.store = store
        self._now_fn = now_fn
        self.last_sweep_exhausted = False

    def _now(self, now=None) -> int:
        return int(now if now is not None else self._now_fn())

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
            # 14일 넘은 매물은 추적하지 않는다. 그래도 행은 남긴다 — 행이 없으면
            # 다음 폴링마다 '처음 본 매물'이 되어 같은 매물을 계속 재알림한다.
            # 묘비일 뿐 구독이 아니므로 added 에는 세지 않는다.
            if tier == TIER_DEAD:
                continue
            if price:
                self.store.add_price(aid, now, price)
            added += 1
        return added

    def enforce_cap(self, now=None) -> int:
        over = self.store.active_count() - ACTIVE_CAP
        if over <= 0:
            return 0
        for aid in self.store.oldest_active(over):
            self.store.mark(aid, tier=TIER_EVICTED)
        return over

    def check_one(self, article_id, api, now=None) -> list[dict]:
        now = self._now(now)
        old = self.store.get(str(article_id))
        if old is None:
            return []
        # 아직 한 번도 재조회하지 않은 행 = 씨앗값만 들어 있다. 씨앗의 가격은
        # 알림 표시 문자열에서, republish_count 는 0 고정으로 만든 값이라 API 실측과
        # 비교하면 없는 변동이 잡힌다. 첫 조회는 기준선 확보로만 쓰고 알리지 않는다.
        #
        # last_check 는 이 표식의 전부다 — 관측에 성공한 경로만 쓸 수 있다.
        # 실패 경로가 last_check 를 건드리면 등호가 깨져 아직 씨앗뿐인 행이
        # '이미 기준선을 잡은 행'으로 둔갑하고, 첫 성공 조회가 씨앗과 비교돼
        # 없는 변동을 알린다. 실패는 fail·next_check 만 움직인다.
        seeding = old.get("last_check") == old.get("first_seen")
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

        # 값을 못 받은 가격(0·음수·비정수)은 '내려간 것'이 아니라 '모르는 것'이다.
        # 저장값을 그대로 두고 이번 회차의 가격 이벤트는 만들지 않는다.
        np_ = new.get("price")
        if not new.get("gone") and (isinstance(np_, bool)
                                    or not isinstance(np_, int) or np_ <= 0):
            new["price"] = old.get("price")

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

    def _note_failure(self, old, article_id, now) -> list[dict]:
        """조회 실패는 매물의 변화가 아니다 — 알리지 않고 세기만 한다.

        last_check 는 건드리지 않는다: 관측에 실패했으니 '마지막 관측'이 아니고,
        check_one 의 기준선 표식(last_check == first_seen)이 실패 한 번에 깨지면
        안 된다. 일정은 next_check 로만 움직이므로 영향 없다."""
        fail = (old.get("fail") or 0) + 1
        if fail >= MAX_FAIL:
            self.store.mark(article_id, fail=fail, tier=TIER_EVICTED)
        else:
            self.store.mark(article_id, fail=fail,
                            next_check=now + interval_for(old.get("tier") or TIER_FRESH))
        return []

    def sweep(self, api_for_account, budget: int, now=None) -> list[dict]:
        """예산만큼 점검한다. api_for_account 는 매 건마다 불리고
        (api, label) 또는 예산 소진 시 None 을 돌려줘야 한다.

        sweep 은 사용한 api 를 매번 닫는다(_close) — 그래서 api_for_account 는
        호출마다 새 클라이언트를 만들어 돌려줘야 한다. 계정당 클라이언트를
        캐시해서 재사용하는 provider 를 쓰면 이미 닫힌 client 를 다시 넘기게
        되어 깨진다.

        self.last_sweep_exhausted: 이번 스윕이 계정 예산이 떨어져 대기열을 남긴 채
        끝났으면 True. 조용히 커버리지가 줄어드는 것을 호출자가 알아채라고 둔다."""
        now = self._now(now)
        out = []
        blocked = set()
        self.last_sweep_exhausted = False
        first = True
        for aid in self.store.due(now, int(budget)):
            if not first:
                time.sleep(SWEEP_ITEM_DELAY)
            first = False
            api = label = None
            for _ in range(4):
                got = api_for_account()
                if not got:
                    self.last_sweep_exhausted = True
                    return out
                if got[1] in blocked:
                    _close(got[0])
                    continue
                api, label = got
                break
            if api is None:
                self.last_sweep_exhausted = True
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


def _today() -> str:
    return _dt.date.today().isoformat()


class AccountBudget:
    """유효 토큰 계정을 라운드로빈으로 내주고 하루 요청 수를 계정별로 제한한다.

    사용량은 파일에 남긴다 — 재시작(크래시·배포·--once)마다 '하루' 상한이
    0 으로 돌아가면 상한이 아니게 된다.

    주의: 이 예산은 AccountScheduler 의 예산과 별개다. 두 컴포넌트가 같은 계정을
    쓰면 계정 전체 요청 수는 어느 한쪽 상한을 넘을 수 있다 — 합산 예산은 후속
    과제이고 여기서 고칠 범위가 아니다."""

    def __init__(self, accounts_fp: str = "./accounts.json",
                 daily_cap: int = DAILY_CAP_PER_ACCOUNT,
                 config_path: str = "./data/config.json",
                 api_factory=None, day_fn=None,
                 budget_fp: str = WATCH_BUDGET_FP):
        self.accounts_fp = accounts_fp
        self.budget_fp = budget_fp
        self.daily_cap = int(daily_cap)
        self.config_path = config_path
        self._factory = api_factory or _default_api_factory
        self._day_fn = day_fn or _today
        self._day = self._day_fn()
        self._used = self._load_usage()
        self._last_label = None
        self._accounts = []
        self.reload()

    def _load_usage(self) -> dict:
        """없거나·깨졌거나·어제 것이면 '오늘 0부터'. 절대 예외를 올리지 않는다."""
        try:
            with open(self.budget_fp, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or data.get("day") != self._day:
                return {}
            used = data.get("used")
            if not isinstance(used, dict):
                return {}
            return {str(k): int(v) for k, v in used.items()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)}
        except Exception:
            return {}

    def _save_usage(self) -> None:
        try:
            d = os.path.dirname(self.budget_fp)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(self.budget_fp, "w", encoding="utf-8") as f:
                json.dump({"day": self._day, "used": self._used}, f)
        except Exception:
            pass

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
            self._save_usage()

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
        labels = [a.get("label") or "" for a in cands]
        start = labels.index(self._last_label) + 1 \
            if self._last_label in labels else 0
        for i in range(len(cands)):
            idx = (start + i) % len(cands)
            label = labels[idx]
            if self._used.get(label, 0) < self.daily_cap:
                self._used[label] = self._used.get(label, 0) + 1
                self._last_label = label
                self._save_usage()
                return self._factory(cands[idx].get("access"),
                                     config_path=self.config_path,
                                     proxy=cands[idx].get("proxy")), label
        return None


def _default_api_factory(token, config_path=None, proxy=None):
    return ArticleDetailAPI(token, config_path=config_path or "./data/config.json",
                            proxy=proxy)

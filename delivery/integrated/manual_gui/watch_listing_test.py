import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


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

# ── G. 오래된 매물도 묘비 행을 남긴다 ──
# 행이 없으면 store.get() 이 매번 None 이라 같은 매물을 폴링마다 재알림한다.
print("=== G. dead 묘비 ===")
st4 = aw.WatchStore(os.path.join(d2, "w4.db"))
tr4 = aw.WatchTracker(st4)
OLD = [{"article_id": "99", "title": "오래된 매물", "price": "10만원",
        "region": "압구정", "url": "u99", "time": NOW - 30 * DAY,
        "keyword": "샤넬"}]
ck("오래된 매치는 추적수에 안 셈", tr4.add_from_matches(OLD, now=NOW) == 0)
r99 = st4.get("99")
ck("그래도 행은 남는다", r99 is not None)
ck("등급은 dead", r99 and r99["tier"] == aw.TIER_DEAD, str(r99 and r99.get("tier")))
# 빈 DB 에서도 참인 명제라 행 존재와 묶어서 확인한다 — 안 그러면 묘비가 없어도
# 통과하는 검사가 된다.
ck("묘비가 있는데도 active 아님",
   r99 is not None and st4.active_count() == 0, str(st4.active_count()))
ck("묘비가 있는데도 due 없음",
   r99 is not None and st4.due(NOW + 10 * DAY, 10) == [], str(st4.due(NOW, 10)))
ck("두 번째 투입도 0 — 재알림 안 남", tr4.add_from_matches(OLD, now=NOW + 60) == 0)
r99b = st4.get("99")
ck("묘비는 그대로 dead",
   r99b is not None and r99b["tier"] == aw.TIER_DEAD, str(r99b))
# 씨앗 가격만 있고 이력은 안 쌓는다 — 추적이 아니라 묘비다.
ck("묘비는 가격 이력 안 남김", st4.price_history("99") == [],
   str(st4.price_history("99")))

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

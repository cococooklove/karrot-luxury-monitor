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

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

"""백필 스크립트 테스트 (네트워크 불필요).

    python backfill_test.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


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

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

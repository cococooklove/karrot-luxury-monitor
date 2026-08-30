"""매물 표(listingTable) 순수 함수 배선 확인 (Qt 창 안 띄움).

    python unified_tab_wiring_test.py
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

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

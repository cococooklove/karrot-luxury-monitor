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

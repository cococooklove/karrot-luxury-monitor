"""auto_seen.db 를 watch 테이블로 한 번 옮긴다.

자동 모니터가 따로 들고 있던 '본 매물' 기록을 매물 표의 단일 진실로 합친다.
한 번 돌리고 나면 match_seen.json 은 지워도 된다. auto_seen.db 는 자동
모니터가 발신 전 중복 판정에 계속 쓰므로 그대로 둔다.

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

    # match_seen.json 은 id 배열뿐이라 표에 채울 정보가 없다. 그래도 옮겨야
    # 한다 — 중복 판정은 컬럼이 아니라 id 만 필요하다. dedupe_new_matches 는
    # watch 행이 없으면 '처음 보는 매물'로 치므로, 알림만 나가고 행이 없던
    # 매물(예전 add_from_matches 가 건너뛰던 dead 등급)이 계정 알림함에 남아
    # 있으면 첫 폴링에 텔레그램·시트로 다시 나간다. 그러고 나서 이 파일을
    # 지우면 되돌릴 수 없다.
    #
    # 값이 없으므로 묘비만 세운다. source=match_seen 이라 listing_display_rows
    # 가 출처로 걸러내므로 표에 빈 줄로 뜨지 않는다.
    ids = []
    if match_seen_json and os.path.exists(match_seen_json):
        try:
            with open(match_seen_json, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data = data.get("seen") or list(data.keys())
            ids = [str(x) for x in (data or []) if str(x or "").strip()]
        except Exception:
            ids = []

    for aid in ids:
        if store.get(aid) is not None:
            out["skipped"] += 1
            continue
        store.upsert({
            "id": aid,
            "title": "",
            "region": "",
            "url": "",
            "price": 0,
            "status": aw.STATUS_ONGOING,
            "republish_count": 0,
            "published_at": 0,
            "first_seen": now,
            "last_check": now,
            "next_check": 0,
            "tier": aw.TIER_DEAD,
            "fail": 0,
            "keyword": "",
            "source": aw.SOURCE_MATCH_SEEN,
            "first_price": 0,
            "last_change": 0,
            "last_delta": 0,
        })
        out["from_match"] += 1

    return out


def main() -> int:
    store = aw.WatchStore("./data/watch.db")
    res = backfill(store, "./auto_seen.db", "./data/match_seen.json",
                   int(time.time()))
    print(f"백필 완료: auto_seen {res['from_auto']}건 이관, "
          f"match_seen {res['from_match']}건 묘비 생성, "
          f"{res['skipped']}건은 이미 있어 건너뜀")
    print("data/match_seen.json 은 이제 지워도 됩니다.")
    print("auto_seen.db 는 지우지 마세요 — 자동 모니터가 자기 중복 판정에 "
          "계속 씁니다(지우면 다시 만들어 채웁니다).")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

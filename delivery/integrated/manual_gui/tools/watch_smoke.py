# -*- coding: utf-8 -*-
"""워치리스트 실환경 점검 — 서버에서 유효 토큰으로 몇 건만 돈다.

    python tools/watch_smoke.py

운영 data/watch.db 는 건드리지 않는다(임시 파일 사용).
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from daangn_ext import article_watch as aw
from daangn_ext.keyword_alert_api import KeywordAlertAPI, token_remaining

accs = [a for a in json.load(open("./accounts.json", encoding="utf-8"))
        if token_remaining(a.get("access") or "") > 120]
if not accs:
    print("NO_VALID_TOKEN — 수확 먼저")
    sys.exit(1)

api = KeywordAlertAPI(accs[0]["access"])
try:
    matches = api.new_matches()
finally:
    api.close()
print("matches=%d" % len(matches))
if not matches:
    print("매칭 없음 — 나중에 다시")
    sys.exit(1)

store = aw.WatchStore(os.path.join(tempfile.mkdtemp(), "smoke.db"))
tracker = aw.WatchTracker(store)
print("added=%d active=%d" % (tracker.add_from_matches(matches[:3]),
                              store.active_count()))

try:
    with open("./proxies.txt", encoding="utf-8") as f:
        proxies = [ln.strip() for ln in f if ln.strip()]
except OSError:
    proxies = []
budget = aw.ProxyBudget(proxies)  # 추적은 계정 토큰이 아니라 공개 웹 상세를 본다
print("budget_remaining=%d" % budget.remaining())

future = int(time.time()) + aw.FRESH_INTERVAL + 1
for aid in store.due(future, 3):
    got = budget.next()
    if not got:
        print("예산 소진")
        break
    detail_api, label = got
    try:
        ev = tracker.check_one(aid, detail_api, future)
    except aw.AccountUnavailable as e:
        print("  %s via %s → 계정 사용불가(%s)" % (aid, label, e))
        continue
    finally:
        detail_api.close()
    row = store.get(aid)
    print("  %s via %s → price=%s status=%s tier=%s events=%s"
          % (aid, label, row["price"], row["status"], row["tier"],
             [e["kind"] for e in ev]))

store.close()
print("OK")

#!/usr/bin/env python3
"""서버 수동 모드(app-API 검색) 라이브 검증. accounts.json access + data/config.json 필요.
실행: python tools/test_manual_server.py [지역코드] [키워드]"""
import json
import sys
sys.path.insert(0, ".")
from daangn_ext.app_source import AppSource

region = sys.argv[1] if len(sys.argv) > 1 else "역삼동-6035"
kw = sys.argv[2] if len(sys.argv) > 2 else "샤넬"

accs = json.load(open("./accounts.json", encoding="utf-8"))
acc = next((x["access"] for x in accs if x.get("access")), None)
if not acc:
    print("유효 access 없음"); sys.exit(1)

src = AppSource()
src.max_pages = 1                      # 1페이지만(빠른 검증)
arts, st = src.collect_region(kw, region, access_token=acc)
print(f"수동검색 {kw} @ {region}: {len(arts)}건 (stopped={st.get('stopped_by')})")
for a in arts[:5]:
    print("  ·", (a.get("title") or "")[:34], "|", a.get("price"), "|", a.get("region"))

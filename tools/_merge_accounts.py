#!/usr/bin/env python3
# 수확 결과를 기존 accounts.json 에 code 기준 병합. 수확계정은 refresh/access 갱신,
# 기존 proxy/label 보존. 미수확 계정은 그대로 유지.
# 사용: python3 _merge_accounts.py <base_accounts.json> <harvested.json>
import sys, json, os

base_fp, harv_fp = sys.argv[1], sys.argv[2]
base = json.load(open(base_fp, encoding="utf-8")) if os.path.exists(base_fp) else []
harv = json.load(open(harv_fp, encoding="utf-8")) if os.path.exists(harv_fp) else []

by_code = {a.get("code"): a for a in base}
upd = ins = 0
for h in harv:
    c = h.get("code")
    if not h.get("refresh"):
        continue
    if c in by_code:
        a = by_code[c]
        if h["refresh"] != a.get("refresh") or h.get("access") != a.get("access"):
            a["refresh"] = h["refresh"]
            a["access"] = h.get("access", "")
            if "_refresh_ttl" in h: a["_refresh_ttl"] = h["_refresh_ttl"]
            upd += 1
    else:
        by_code[c] = h
        base.append(h)
        ins += 1

tmp = base_fp + ".tmp"
json.dump(base, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
os.replace(tmp, base_fp)
try: os.chmod(base_fp, 0o600)
except Exception: pass
print(f"    병합: 갱신 {upd} · 신규 {ins} · 총 {len(base)}계정")

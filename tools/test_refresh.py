#!/usr/bin/env python3
"""WAF 판별: 첫 계정 refresh 실호출. X-Request-Id 포함(디컴파일 확정 헤더).
통과 → Mac 순정 무인 가능. 403 → TLS 지문 기반, 앱경로 필요."""
import sys, time, json
sys.path.insert(0, "collector")
import token_manager as tm

d = json.load(open("data/accounts.json"))
acc = d[0]
a = tm.Account(code=acc["code"], refresh=acc["refresh"],
               access=acc.get("access", ""), proxy=acc.get("proxy"))
print(f"계정 {a.code[:8]} · proxy={a.proxy or 'none'}")
try:
    na, nr = tm._default_refresh(a)
    print(f"성공 ✅  새 access TTL {int(tm.token_exp(na)-time.time())}s · refresh회전 {'O' if nr else 'X'}")
    print("→ Mac 순정 무인 가능. 에뮬/LD 불필요.")
except Exception as e:
    print(f"실패 ❌  {e}")
    print("→ 403 지속이면 TLS 지문 기반. 헤더로 못 뚫음 → APK 재패키징+앱캡처 경로.")

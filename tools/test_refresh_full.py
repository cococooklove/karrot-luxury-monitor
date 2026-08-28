#!/usr/bin/env python3
"""토큰 refresh 엔드포인트 정밀 재검증 — PC서 갱신 되나(WAF 통과?).

이게 전체 아키텍처를 가름:
  200 → PC서 갱신 가능 = LDPlayer 상시 불필요
  403 → WAF 차단 = LDPlayer 필수

현재 accounts.json 의 유효 refresh + config.json 풀 device 헤더로 실호출.
여러 impersonation 을 순차 시도(WAF 가 TLS 지문 기반이면 종류마다 다를 수 있음).
"""
import json
import sys
import time

ACCOUNTS = "data/accounts.json"
CONFIG = "data/config.json"
URL = "https://api.kr.karrotmarket.com/auth/v2/tokens/refresh"
IMPERSONATE = ["chrome", "safari_ios", "safari", "chrome110", "edge99", "okhttp"]


def load_account():
    rows = json.load(open(ACCOUNTS, encoding="utf-8"))
    # refresh 가장 최근(access 살아있는) 계정
    import base64
    def exp(t):
        try:
            p = t.split(".")[1]; p += "=" * (-len(p) % 4)
            return json.loads(base64.urlsafe_b64decode(p)).get("exp", 0)
        except Exception:
            return 0
    best = None
    for a in rows:
        if a.get("refresh"):
            if best is None or exp(a.get("access", "")) > exp(best.get("access", "")):
                best = a
    return best


def main():
    acc = load_account()
    if not acc:
        print("❌ refresh 토큰 있는 계정 없음"); sys.exit(2)
    print(f"계정 {str(acc.get('code'))[:8]}")

    # config.json 풀 헤더
    headers = {}
    try:
        cfg = json.load(open(CONFIG, encoding="utf-8"))
        headers = dict(cfg.get("headers") or {})
    except Exception as e:
        print(f"⚠️ config.json 로드 실패({e}) — 최소 헤더로 시도")
    headers["content-type"] = "application/json"
    headers.setdefault("accept", "application/json")
    import uuid
    headers["x-request-id"] = str(uuid.uuid4())
    if acc.get("access"):
        headers["authorization"] = f"Bearer {acc['access']}"
    print(f"헤더 {len(headers)}개: {sorted(headers)}")

    from curl_cffi import requests
    body = json.dumps({"refresh_token": acc["refresh"]}).encode()

    for imp in IMPERSONATE:
        try:
            r = requests.post(URL, data=body, headers=headers, impersonate=imp, timeout=15)
            snippet = r.text[:160].replace("\n", " ")
            print(f"[{imp:12s}] HTTP {r.status_code}  {snippet}")
            if r.status_code == 200:
                d = r.json()
                print(f"  ✅✅ 갱신 성공! 새 access={'access_token' in d} refresh={'refresh_token' in d}")
                print("  → PC서 갱신 가능 = LDPlayer 상시 불필요")
                return
        except Exception as e:
            print(f"[{imp:12s}] ERR {type(e).__name__}: {str(e)[:80]}")
        time.sleep(2)
    print("\n→ 전 impersonation 403/실패 = WAF 차단 확정. LDPlayer 필수")


if __name__ == "__main__":
    main()

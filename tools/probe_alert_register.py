#!/usr/bin/env python3
"""키워드 알림 등록(register) 엔드포인트 프로브 (Mac, 캡처 없이).

info 경로 `/api/v1/fleamarket/keyword/notification/info` 기반으로 등록 후보 경로/메서드를
토큰으로 시도 → 200/201 나오고 info 재조회 시 isRegistered=true 면 그게 register.

⚠️ 계정에 실제 키워드 등록됨(되돌림 가능). 테스트 키워드 1개만.
성공하면 스펙을 data/keyword_alert_endpoints.json 에 기록.
"""
import base64, json, sys, time
import httpx

HOST = "search-bff.kr.karrotmarket.com"
BASE = "/api/v1/fleamarket/keyword/notification"
UA = "Karrot/26.34.0 (com.towneers.www; build:263400; Android 33)"
KW = "샤넬"     # 프로브 키워드(실제 타깃이라 등록돼도 유용)


def freshest(fp="data/accounts.json"):
    def exp(t):
        try:
            p = t.split(".")[1]; p += "=" * (-len(p) % 4)
            return json.loads(base64.urlsafe_b64decode(p)).get("exp", 0)
        except Exception:
            return 0
    best = None
    for a in json.load(open(fp, encoding="utf-8")):
        acc = a.get("access") or ""
        if acc and (best is None or exp(acc) > exp(best)):
            best = acc
    return best


def make_headers(token):
    h = {"accept": "application/json", "content-type": "application/json",
         "x-user-agent": UA, "authorization": f"Bearer {token}"}
    try:
        cfg = json.load(open("data/config.json", encoding="utf-8")).get("headers", {})
        for k in ("x-user-agent", "x-device-identity", "x-ad-id", "x-country-code",
                  "x-karrot-session-id", "accept-language"):
            if k in cfg:
                h[k] = cfg[k]
    except Exception:
        pass
    return h


def is_registered(client, headers):
    r = client.get(f"https://{HOST}{BASE}/info", headers=headers, params={"keyword": KW})
    if r.status_code == 200:
        return r.json().get("isRegistered")
    return None


def main():
    token = freshest()
    if not token:
        print("❌ 토큰 없음"); sys.exit(2)
    headers = make_headers(token)
    client = httpx.Client(http2=True, timeout=15)

    before = is_registered(client, headers)
    print(f"프로브 키워드: {KW} · 시작 isRegistered={before}")
    if before:
        print("이미 등록됨 — unregister 프로브로 넘어가는 게 나음. 중단.")
        return

    # 등록 후보 (method, path, kwargs)
    candidates = [
        ("POST", BASE, {"json": {"keyword": KW}}),
        ("POST", BASE, {"params": {"keyword": KW}}),
        ("POST", f"{BASE}/register", {"json": {"keyword": KW}}),
        ("PUT",  BASE, {"json": {"keyword": KW}}),
        ("PUT",  f"{BASE}", {"params": {"keyword": KW}}),
        ("POST", f"{BASE}s", {"json": {"keyword": KW}}),
    ]
    for method, path, kw in candidates:
        try:
            r = client.request(method, f"https://{HOST}{path}", headers=headers, **kw)
            body = r.text[:150].replace("\n", " ")
            print(f"[{method} {path} {list(kw)[0]}] → {r.status_code}  {body}")
            if r.status_code in (200, 201, 204):
                time.sleep(1)
                after = is_registered(client, headers)
                print(f"    ↳ 등록후 isRegistered={after}")
                if after:
                    print(f"\n🎯 REGISTER 확정: {method} {path}  body/{list(kw)[0]}")
                    spec = {"register": {"method": method, "path": path,
                                         "kind": list(kw)[0]}}
                    json.dump(spec, open("data/keyword_alert_endpoints.json", "w",
                                         encoding="utf-8"), ensure_ascii=False, indent=2)
                    print("→ data/keyword_alert_endpoints.json 기록. (unregister는 별도 프로브)")
                    return
        except Exception as e:
            print(f"[{method} {path}] ERR {type(e).__name__}: {str(e)[:70]}")
        time.sleep(1.5)
    print("\n전 후보 실패 — 경로가 다름. mitmproxy 캡처 필요(앱서 등록하며 트래픽).")


if __name__ == "__main__":
    main()

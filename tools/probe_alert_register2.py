#!/usr/bin/env python3
"""등록 프로브 v2 — POST .../keyword/notification?keyword=샤넬 + body 변형.

v1서 판명: 경로/메서드 = POST(또는 PUT) + query ?keyword=. 500 = body 불완전.
여기선 body 스키마를 바꿔가며 200/201 + isRegistered=true 를 찾는다.
"""
import base64, json, sys, time
import httpx

HOST = "search-bff.kr.karrotmarket.com"
BASE = "/api/v1/fleamarket/keyword/notification"
UA = "Karrot/26.34.0 (com.towneers.www; build:263400; Android 33)"
KW = "샤넬"
REGION = "6128"; LAT = 37.4837; LON = 127.0324
COORD = "USER_COORDINATE_TYPE_REGION_CENTER_COORDINATE"


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
         "x-user-agent": UA, "authorization": f"Bearer {token}", "x-search-tab": "fleamarket"}
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
    return r.json().get("isRegistered") if r.status_code == 200 else None


def main():
    token = freshest()
    if not token:
        print("❌ 토큰 없음"); sys.exit(2)
    headers = make_headers(token)
    client = httpx.Client(http2=True, timeout=15)
    if is_registered(client, headers):
        print("이미 등록됨 — 중단"); return

    spatial = {"region": {"regionId": REGION},
               "userCoordinates": [{"type": COORD, "coordinate": {"latitude": LAT, "longitude": LON}}]}
    # (label, body) — query 는 항상 ?keyword=KW
    bodies = [
        ("empty", {}),
        ("keyword", {"keyword": KW}),
        ("regionId", {"regionId": REGION}),
        ("kw+region", {"keyword": KW, "regionId": REGION}),
        ("spatialContext", {"spatialContext": spatial}),
        ("kw+spatial", {"keyword": KW, "spatialContext": spatial}),
        ("fleaMarket", {"fleaMarket": {"filter": {"spatialContext": spatial}}}),
    ]
    for method in ("POST", "PUT"):
        for label, body in bodies:
            try:
                r = client.request(method, f"https://{HOST}{BASE}", headers=headers,
                                   params={"keyword": KW},
                                   content=json.dumps(body, ensure_ascii=False).encode())
                snip = r.text[:120].replace("\n", " ")
                print(f"[{method} body={label:14s}] {r.status_code}  {snip}")
                if r.status_code in (200, 201, 204):
                    time.sleep(1)
                    if is_registered(client, headers):
                        print(f"\n🎯 REGISTER 확정: {method} {BASE}?keyword= + body={label}")
                        json.dump({"register": {"method": method, "path": BASE,
                                                "query_key": "keyword", "body": body}},
                                  open("data/keyword_alert_endpoints.json", "w",
                                       encoding="utf-8"), ensure_ascii=False, indent=2)
                        print("→ data/keyword_alert_endpoints.json 기록")
                        return
            except Exception as e:
                print(f"[{method} {label}] ERR {str(e)[:60]}")
            time.sleep(1.2)
    print("\n전 body 실패 — mitmproxy 캡처로 정확한 스키마 필요")


if __name__ == "__main__":
    main()

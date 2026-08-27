#!/usr/bin/env python3
"""알림함(inbox) API 프로브 — inbox.kr.karrotwebview.com 에 토큰으로 알림리스트 시도.

알림함은 웹뷰라 실제 API는 JS 안(캡처 필요)이지만, 토큰으로 바로 되는지 후보경로 시도.
200+JSON(알림목록) 나오면 = 토큰폴링으로 매칭수신 가능 = LDPlayer 최소화 대박.
"""
import base64, json, sys, time
import httpx

UA = "Karrot/26.34.0 (com.towneers.www; build:263400; Android 33)"
HOSTS = ["inbox.kr.karrotwebview.com", "webapp.kr.karrotmarket.com"]
PATHS = [
    "/api/v1/notifications", "/api/notifications", "/notifications.json",
    "/api/v1/notifications/feed", "/api/v1/inbox", "/api/inbox/notifications",
    "/api/v24/notifications.json", "/api/v1/notification/list",
    "/api/v1/me/notifications", "/api/v1/activities", "/api/v24/activities.json",
]


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


def main():
    token = freshest()
    if not token:
        print("❌ 토큰 없음"); sys.exit(2)
    h = {"accept": "application/json", "x-user-agent": UA, "authorization": f"Bearer {token}"}
    try:
        cfg = json.load(open("data/config.json", encoding="utf-8")).get("headers", {})
        for k in ("x-user-agent", "x-device-identity", "x-ad-id", "x-country-code",
                  "x-karrot-session-id", "accept-language"):
            if k in cfg:
                h[k] = cfg[k]
    except Exception:
        pass
    client = httpx.Client(http2=True, timeout=12)
    hit = False
    for host in HOSTS:
        for path in PATHS:
            try:
                r = client.get(f"https://{host}{path}", headers=h)
                ct = r.headers.get("content-type", "")
                is_json = "json" in ct
                snip = r.text[:120].replace("\n", " ")
                mark = " ★JSON" if (r.status_code == 200 and is_json) else ""
                if r.status_code != 404:
                    print(f"[{host}{path}] {r.status_code} {ct[:20]}{mark}  {snip}")
                if r.status_code == 200 and is_json:
                    hit = True
            except Exception as e:
                print(f"[{host}{path}] ERR {str(e)[:50]}")
            time.sleep(0.5)
    if not hit:
        print("\n404/비JSON — 알림함 API는 웹뷰 JS 안. 정확히 찾으려면 웹뷰 트래픽 캡처 필요.")
    else:
        print("\n★ 200 JSON = 알림 폴링 가능! 그 경로로 수신 배선 → LDPlayer 최소화")


if __name__ == "__main__":
    main()

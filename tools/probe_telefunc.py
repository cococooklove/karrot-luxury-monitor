#!/usr/bin/env python3
"""알림함 Telefunc 폴링 프로브 — inbox-bff.kr.karrotmarket.com/_telefunc

확정(캡처): POST /_telefunc, content-type text/plain, Bearer 토큰,
  body {"file":"/src/services/notification/notification.telefunc.ts","name":"<fn>","args":[...]}

목표: invokeListNewMatchesNotifications = 키워드매칭(신규매물) 조회.
되면 토큰만으로 알림 폴링 = LDPlayer 최소화.
"""
import base64, json, sys, time
import httpx

HOST = "inbox-bff.kr.karrotmarket.com"
URL = f"https://{HOST}/_telefunc"
TFILE = "/src/services/notification/notification.telefunc.ts"
UA = "TowneersApp/26.34.0/263400 Android/13/33 sdk_gphone/release"
ORIGIN = "https://inbox.kr.karrotwebview.com"


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


def call(client, headers, name, args):
    body = json.dumps({"file": TFILE, "name": name, "args": args}, ensure_ascii=False)
    r = client.post(URL, headers=headers, content=body.encode())
    return r


def main():
    token = freshest()
    if not token:
        print("❌ 토큰 없음"); sys.exit(2)
    headers = {"content-type": "text/plain", "accept": "*/*",
               "x-user-agent": UA, "authorization": f"Bearer {token}",
               "origin": ORIGIN, "referer": ORIGIN + "/"}
    try:
        cfg = json.load(open("data/config.json", encoding="utf-8")).get("headers", {})
        for k in ("x-ad-id", "x-device-identity", "x-country-code", "x-karrot-session-id"):
            if k in cfg:
                headers[k] = cfg[k]
    except Exception:
        pass

    client = httpx.Client(http2=True, timeout=15)
    calls = [
        ("invokeListNewMatchesNotifications", [{"categoryId": "2", "cursor": "!undefined"}]),
        ("invokeListNewMatchesNotifications", [{"categoryId": "2"}]),
        ("invokeListNewMatchesNotifications", [{"category_id": "2", "cursor": "!undefined"}]),
        ("invokeListNewMatchesNotifications", ["2", "!undefined"]),
        ("invokeListNewMatchesNotifications", [{"categoryId": 2, "cursor": "!undefined"}]),
        ("invokeGetNewMatchesNotificationSettingsData", [{"categoryId": "2"}]),
    ]
    for name, args in calls:
        try:
            r = call(client, headers, name, args)
            snip = r.text[:350].replace("\n", " ")
            print(f"\n[{name} args={args}] HTTP {r.status_code} len={len(r.text)}")
            print("  ", snip)
        except Exception as e:
            print(f"[{name}] ERR {type(e).__name__}: {str(e)[:80]}")
        time.sleep(1)
    print("\n200 + 매칭데이터 나오면 = 알림 폴링 확정(토큰만으로 매칭수신) = LDPlayer 최소화")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""키워드 알림 API 검증 (Mac) — 확정 엔드포인트 info 를 토큰으로 호출.

GET https://search-bff.kr.karrotmarket.com/api/v1/fleamarket/keyword/notification/info?keyword=샤넬
→ {keyword, isRegistered, isBannedKeyword, isNotificationBannedKeyword}

search-bff 라 검색과 동일 토큰/헤더. 200 나오면 알림 API가 토큰으로 접근됨 = 알림모드 기반 확인.
등록(register) 엔드포인트는 미캡처라 여기선 조회만.
"""
import argparse, base64, json, sys, time
import httpx

HOST = "search-bff.kr.karrotmarket.com"
PATH = "/api/v1/fleamarket/keyword/notification/info"
UA = "Karrot/26.34.0 (com.towneers.www; build:263400; Android 33)"


def freshest(fp):
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--accounts", default="data/accounts.json")
    ap.add_argument("--config", default="data/config.json")
    ap.add_argument("--keywords", nargs="*", default=["샤넬", "루이비통", "롤렉스", "에르메스"])
    a = ap.parse_args()

    token = freshest(a.accounts)
    if not token:
        print("❌ access 없음 — 폰 수확 먼저"); sys.exit(2)
    now = int(time.time())
    try:
        p = token.split(".")[1]; p += "=" * (-len(p) % 4)
        rem = json.loads(base64.urlsafe_b64decode(p)).get("exp", 0) - now
        print(f"토큰 잔여 {int(rem)}s ({int(rem/60)}분)" + (" ⚠️만료" if rem < 0 else ""))
    except Exception:
        pass

    headers = {"accept": "application/json", "x-user-agent": UA,
               "authorization": f"Bearer {token}"}
    try:
        cfg = json.load(open(a.config, encoding="utf-8")).get("headers", {})
        for k in ("x-user-agent", "x-device-identity", "x-ad-id", "x-country-code",
                  "x-karrot-session-id", "accept-language"):
            if k in cfg:
                headers[k] = cfg[k]
    except Exception:
        pass

    client = httpx.Client(http2=True, timeout=15)
    for kw in a.keywords:
        try:
            r = client.get(f"https://{HOST}{PATH}", headers=headers, params={"keyword": kw})
            body = r.text[:200].replace("\n", " ")
            print(f"[{kw}] HTTP {r.status_code}  {body}")
            if r.status_code == 200:
                d = r.json()
                print(f"    등록={d.get('isRegistered')} 차단키워드={d.get('isBannedKeyword')} "
                      f"알림차단={d.get('isNotificationBannedKeyword')}")
        except Exception as e:
            print(f"[{kw}] ERR {type(e).__name__}: {str(e)[:80]}")
        time.sleep(1)
    print("\n200+정상응답 = 알림 API 토큰접근 확인. 등록 엔드포인트는 캡처 필요(다음 단계).")


if __name__ == "__main__":
    main()

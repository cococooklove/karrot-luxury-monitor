#!/usr/bin/env python3
"""알림키워드 CRUD 프로브 — 확정 경로 webapp.kr.karrotmarket.com/api/v24/keyword/user_keywords.json

앱 디컴파일로 확정: user_keywords 가 알림키워드. GET=목록, POST=등록, DELETE={id}=삭제.
1) GET 으로 토큰이 webapp 에 통하나 + 현재 등록목록 확인(안전)
2) POST 로 등록 시도(body 변형). 성공하면 GET 재확인.
"""
import base64, json, sys, time
import httpx

HOST = "webapp.kr.karrotmarket.com"
PATH = "/api/v24/keyword/user_keywords.json"
UA = "Karrot/26.34.0 (com.towneers.www; build:263400; Android 33)"
KW = "샤넬"


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
                  "x-karrot-session-id", "accept-language", "user-agent"):
            if k in cfg:
                h[k] = cfg[k]
    except Exception:
        pass
    return h


def main():
    token = freshest()
    if not token:
        print("❌ 토큰 없음"); sys.exit(2)
    headers = make_headers(token)
    client = httpx.Client(http2=True, timeout=15)
    url = f"https://{HOST}{PATH}"

    print("=== [1] GET 목록 (토큰 webapp 통하나 + 현재 등록) ===")
    try:
        r = client.get(url, headers=headers)
        print(f"GET {r.status_code}  {r.text[:250].replace(chr(10),' ')}")
    except Exception as e:
        print(f"GET ERR {type(e).__name__}: {str(e)[:80]}")

    print("\n=== [2] POST 등록 시도 ===")
    bodies = [
        ("keyword", {"keyword": KW}),
        ("kw+excl", {"keyword": KW, "exclude_keywords": []}),
        ("kw+price", {"keyword": KW, "min_price": None, "max_price": None}),
        ("full", {"keyword": KW, "exclude_keywords": [], "min_price": None,
                  "max_price": None, "category_ids": []}),
        ("user_keyword", {"user_keyword": {"keyword": KW}}),
    ]
    for label, body in bodies:
        try:
            r = client.post(url, headers=headers,
                            content=json.dumps(body, ensure_ascii=False).encode())
            snip = r.text[:220].replace("\n", " ")
            print(f"[POST {label:12s}] {r.status_code}  {snip}")
            if r.status_code in (200, 201):
                print(f"\n🎯 등록 성공! body={label}")
                # 확인
                g = client.get(url, headers=headers)
                print("목록 재확인:", g.text[:200].replace("\n", " "))
                json.dump({"host": HOST, "list": {"method": "GET", "path": PATH},
                           "register": {"method": "POST", "path": PATH, "body": body}},
                          open("data/keyword_alert_endpoints.json", "w", encoding="utf-8"),
                          ensure_ascii=False, indent=2)
                print("→ data/keyword_alert_endpoints.json 기록")
                return
        except Exception as e:
            print(f"[POST {label}] ERR {str(e)[:60]}")
        time.sleep(1.2)
    print("\n등록 실패 — 에러메시지의 필드 힌트 보고 body 조정 필요")


if __name__ == "__main__":
    main()

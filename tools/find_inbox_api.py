#!/usr/bin/env python3
"""알림함 SPA 의 데이터 API 엔드포인트 발굴 — HTML → JS 번들 → grep.

inbox.kr.karrotwebview.com 은 SPA(HTML셸). 실제 알림리스트 API URL 은 JS 번들에
문자열로 박혀있다. JS 는 정적(warp-static)이라 토큰 없이 받아 grep 하면 나온다.
"""
import base64, json, re, sys
import httpx

UA = "Karrot/26.34.0 (com.towneers.www; build:263400; Android 33)"
INBOX = "https://inbox.kr.karrotwebview.com/"


def freshest(fp="data/accounts.json"):
    def exp(t):
        try:
            p = t.split(".")[1]; p += "=" * (-len(p) % 4)
            return json.loads(base64.urlsafe_b64decode(p)).get("exp", 0)
        except Exception:
            return 0
    best = None
    try:
        for a in json.load(open(fp, encoding="utf-8")):
            acc = a.get("access") or ""
            if acc and (best is None or exp(acc) > exp(best)):
                best = acc
    except Exception:
        pass
    return best


def main():
    token = freshest()
    h = {"x-user-agent": UA}
    if token:
        h["authorization"] = f"Bearer {token}"
    client = httpx.Client(http2=True, timeout=20, follow_redirects=True)

    print("=== [1] 인박스 HTML 받기 ===")
    r = client.get(INBOX, headers=h)
    html = r.text
    print(f"HTML {r.status_code}, {len(html)}바이트")

    # JS/모듈 URL 추출 (script src, modulepreload, import)
    urls = set(re.findall(r'(?:src|href)="([^"]+\.js[^"]*)"', html))
    urls |= set(re.findall(r'"(https?://[^"]+\.js)"', html))
    urls |= set(re.findall(r'(/assets/[^"\']+\.js)', html))
    # 상대경로 → 절대
    abs_urls = []
    for u in urls:
        if u.startswith("http"):
            abs_urls.append(u)
        elif u.startswith("/"):
            abs_urls.append("https://inbox.kr.karrotwebview.com" + u)
    abs_urls = sorted(set(abs_urls))
    print(f"JS 번들 {len(abs_urls)}개")
    for u in abs_urls[:10]:
        print("  ", u)

    print("\n=== [2] JS 번들서 API 엔드포인트 grep ===")
    pat = re.compile(r'(https?://[a-z0-9.-]*karrot[a-z0-9.-]*|/api/[a-zA-Z0-9_./{}$-]+|/graphql|notification[a-zA-Z_]*|/bff/[a-zA-Z0-9_./-]+)', re.I)
    found = {}
    for u in abs_urls[:25]:
        try:
            j = client.get(u, headers={"x-user-agent": UA})
            if j.status_code != 200:
                continue
            for m in set(pat.findall(j.text)):
                if any(k in m.lower() for k in ("notification", "/api/", "graphql", "inbox", "activit", "bff")):
                    found.setdefault(m, 0)
                    found[m] += 1
        except Exception as e:
            print(f"  {u} ERR {str(e)[:40]}")
    for k in sorted(found):
        print("  ", k)
    if not found:
        print("  (JS서 API 문자열 못찾음 — 동적구성이거나 gql)")


if __name__ == "__main__":
    main()

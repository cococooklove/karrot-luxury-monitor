#!/usr/bin/env python3
"""인박스 SPA JS서 notificationInboxItems 요청 형식 추출.

inbox-bff.kr.karrotmarket.com/api/frontend 를 어떻게 호출하는지(operation/body/method)
JS 청크서 문맥 뽑아 확인 → 토큰으로 알림 폴링 배선.
"""
import re
import httpx

UA = "Karrot/26.34.0 (com.towneers.www; build:263400; Android 33)"
INBOX = "https://inbox.kr.karrotwebview.com/"
NEEDLES = ["notificationInboxItems", "api/frontend", "NotificationInboxItems",
           "newMatches", "NewMatches", "inbox-bff"]


def main():
    import os
    client = httpx.Client(http2=True, timeout=25, follow_redirects=True)
    html = client.get(INBOX, headers={"x-user-agent": UA}).text
    # 모든 js URL(상대+절대, 교차출처 포함)
    urls = set(re.findall(r'(/assets/[^"\']+\.js)', html))
    urls |= set(re.findall(r'"(https?://[^"]+\.js)"', html))
    urls |= set(re.findall(r'(https?://[a-z0-9./_-]+\.js)', html))
    abs_urls = sorted({u if u.startswith("http") else "https://inbox.kr.karrotwebview.com" + u
                       for u in urls})
    os.makedirs("out/inbox_js", exist_ok=True)
    print(f"JS {len(abs_urls)}개")

    KEYS = ["api/frontend", "notificationInboxItems", "inbox-bff", "operationName", "newMatches"]
    for i, u in enumerate(abs_urls):
        try:
            js = client.get(u, headers={"x-user-agent": UA}).text
        except Exception:
            continue
        # 저장(나중에 직접 grep 가능)
        open(f"out/inbox_js/chunk_{i}.js", "w", encoding="utf-8").write(js)
        for needle in KEYS:
            idx = js.find(needle)
            if idx >= 0:
                s = max(0, idx - 160); e = min(len(js), idx + 260)
                print(f"\n--- chunk_{i} ({u.split('/')[-1]}) :: '{needle}' ---")
                print(js[s:e].replace("\n", " "))
    print("\n(JS 저장: out/inbox_js/ — 더 파려면 여기 grep)")


if __name__ == "__main__":
    main()

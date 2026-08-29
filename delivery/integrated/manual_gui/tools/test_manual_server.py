#!/usr/bin/env python3
"""서버 수동 모드(app-API 검색) 라이브 검증 — config.json 전송 불필요.
정적 헤더 + accounts.json 토큰 + device-identity(인자)로 config 를 자체 구성.

실행: python tools/test_manual_server.py <device-identity>
  (data/config.json 이 이미 있으면 인자 없이도 그걸 사용)
"""
import json
import os
import sys

sys.path.insert(0, ".")

REGION = "역삼동-6035"
KW = "샤넬"

# 비민감 정적 헤더(모두 공통). 토큰/디바이스ID만 주입하면 됨.
STATIC = {
    "x-user-agent": "TowneersApp/26.34.0/263400 iOS/26.6.0/5026.6 iPhone17,4/release",
    "x-country-code": "KR",
    "user-agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
                   "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
                   "TowneersApp/26.34.0 (263400; iOS 26.6.0; Production; release)"),
    "accept": "application/json, text/plain, */*",
    "accept-language": "ko",
    "origin": "https://search.kr.karrotwebview.com",
    "referer": "https://search.kr.karrotwebview.com/",
    "content-type": "application/json",
    "x-search-origin": "search-webview",
    "x-search-tab": "all",
    "x-search-web-version": "f81d512",
    "x-search-funnel-from": "home",
    "x-search-query-from": "typed",
    "x-search-screen-depth-name": "result",
}


def build_config(device_id, token):
    headers = dict(STATIC)
    headers["x-device-identity"] = device_id
    headers["authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    os.makedirs("./data", exist_ok=True)
    with open("./data/config.json", "w", encoding="utf-8") as f:
        json.dump({"endpoint": "https://search-bff.kr.karrotmarket.com/api/v5/integrate/search",
                   "headers": headers}, f, ensure_ascii=False)


def main():
    accs = json.load(open("./accounts.json", encoding="utf-8"))
    token = next((x["access"] for x in accs if x.get("access")), None)
    if not token:
        print("유효 access 없음"); sys.exit(1)
    if len(sys.argv) > 1:
        build_config(sys.argv[1], token)
        print(f"config 자체구성 (device-id={sys.argv[1][:8]}…)")
    elif not os.path.exists("./data/config.json"):
        print("config.json 없음 + device-identity 인자 없음"); sys.exit(1)

    from daangn_ext.app_source import AppSource
    src = AppSource()
    src.max_pages = 1
    arts, st = src.collect_region(KW, REGION, access_token=token)
    print(f"수동검색 {KW} @ {REGION}: {len(arts)}건 (stopped={st.get('stopped_by')})")
    for a in arts[:5]:
        print("  ·", (a.get("title") or "")[:34], "|", a.get("price"), "|", a.get("region"))


if __name__ == "__main__":
    main()

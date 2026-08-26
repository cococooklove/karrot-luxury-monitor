"""당근 buy-sell 응답에서 매물 배열이 어디로 옮겨졌는지 탐색."""
import json, re, sys
from curl_cffi import requests
from bs4 import BeautifulSoup as Soup

kw = sys.argv[1] if len(sys.argv) > 1 else "아이폰"
area = sys.argv[2] if len(sys.argv) > 2 else "역삼동-6035"
url = "https://www.daangn.com/kr/buy-sell/"
r = requests.get(url, impersonate="chrome", timeout=15,
                 params={"search": kw, "in": area})
html = r.text
print(f"http={r.status_code} len={len(html)}")

# 1) 모든 __remixContext / __remixRouteModules / 기타 스크립트 JSON 찾기
soup = Soup(html, "html.parser")
scripts = soup.select("script")
print(f"scripts={len(scripts)}")
for i, s in enumerate(scripts):
    t = s.text or ""
    for marker in ("__remixContext", "fleamarket", "articles", "streamController", "__remixRouteModule"):
        if marker in t:
            print(f"  script[{i}] len={len(t)} has:{marker}")

# 2) remixContext 파싱 후 title+price 가진 dict 리스트 전부 경로와 함께
root = None
for s in scripts:
    if "window.__remixContext" in (s.text or ""):
        j = s.text.replace("window.__remixContext = ", "").rstrip(";")
        try:
            root = json.loads(j)
        except Exception as e:
            print("remixContext 파싱 실패:", e)
        break

def walk(o, path=""):
    if isinstance(o, list):
        if o and isinstance(o[0], dict):
            keys = set(o[0].keys())
            if {"title"} & keys or {"price"} & keys or {"href"} & keys:
                print(f"  [매물후보] {path} len={len(o)} keys={sorted(keys)[:12]}")
        for i, x in enumerate(o[:3]):
            walk(x, f"{path}[{i}]")
    elif isinstance(o, dict):
        for k, v in o.items():
            walk(v, f"{path}.{k}")

if root:
    print("--- title/price/href 배열 탐색 ---")
    walk(root, "remix")

# 3) HTML/JSON 안에 매물 검색 API 엔드포인트 흔적
print("--- API 엔드포인트 흔적 ---")
apis = set(re.findall(r'https?://[a-z0-9.-]+/[a-z0-9/_.-]*'
                      r'(?:flea|article|search|feed|listing)[a-z0-9/_.-]*', html, re.I))
apis |= set(re.findall(r'/v1/api/[a-z0-9/_.-]+', html, re.I))
apis |= set(re.findall(r'/api/v[0-9]/[a-z0-9/_.-]+', html, re.I))
for a in sorted(apis)[:40]:
    print("  ", a[:120])

# 4) 스트리밍 defer (remix가 매물을 나중에 흘리는 경우) 흔적
if "streamController" in html or "__remixContext.streamController" in html:
    print("--- defer 스트림 존재: 매물이 지연로드됨 ---")
    for m in re.findall(r'fleamarketArticles.{0,80}', html)[:5]:
        print("  ", m[:120])

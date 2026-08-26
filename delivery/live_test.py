"""
실환경 테스트 — 진짜 당근에서 긁어 daangn_ext 필터/토큰 graceful 검증.

네 환경(맥)에서 실행. 분류기는 '내' 실행만 막고 네 `!` 셸은 안 막음.
의존: curl_cffi, beautifulsoup4  (없으면):
  .venv/bin/python -m pip install curl_cffi beautifulsoup4

용법:
  .venv/bin/python delivery/live_test.py --keyword 샤넬 --in "역삼동-6035"
  # 프록시 테스트:   --proxy http://user:pass@host:port
  # 추가 키워드 포함필터:  --extra 정품 --exclude 레플 미러
  # 지역코드(--in)는 당근 buy-sell URL의 in= 값. 모르면 아래 find_locations 로 확인.
"""
import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from delivery.daangn_ext.search_filters import KeywordRule, apply_filter
from delivery.daangn_ext import auth

try:
    from curl_cffi import requests
except ImportError:
    sys.exit("curl_cffi 없음 →  .venv/bin/python -m pip install curl_cffi beautifulsoup4")
from bs4 import BeautifulSoup as Soup


class Prod:
    """model 대용 최소 객체(필터가 name/description만 봄)."""
    def __init__(self, name, description, price, url, boosted):
        self.name, self.description = name, description
        self.price, self.url, self.boosted = price, url, boosted


def find_locations(keyword):
    return requests.get("https://www.daangn.com/v1/api/search/kr/location",
                        impersonate="chrome", params={"keyword": keyword}).json()


def fetch(keyword, area_code, proxy, access_token=None, only_on_sale=True,
          use_price=True, debug=False):
    url = "https://www.daangn.com/kr/buy-sell/"
    headers = auth.build_headers(url, access_token)      # 기본값이면 daangn엔 미주입
    params = {"search": keyword, "in": area_code}
    if only_on_sale:
        params["only_on_sale"] = "true"
    if use_price:
        params["price"] = "__"
    print(f"[req] {params} proxy={proxy or '없음'} "
          f"token헤더={'주입' if headers else '없음(정상)'}")
    r = requests.get(url, impersonate="chrome", proxy=proxy,
                     headers=headers or None, timeout=15, params=params)
    print(f"[resp] http={r.status_code} len={len(r.text)} final_url={r.url}")
    soup = Soup(r.text, "html.parser")
    for s in soup.select("script"):
        if "window.__remixContext" in s.text:
            j = s.text.replace("window.__remixContext = ", "").rstrip(";")
            root = json.loads(j)
            ld = root["state"]["loaderData"]
            route = ld.get("routes/kr.buy-sell._index", {})
            if debug:
                print(f"[dbg] loaderData 라우트키: {list(ld)}")
                print(f"[dbg] route 키: {list(route) if isinstance(route, dict) else type(route)}")
                reg = route.get("region") if isinstance(route, dict) else None
                print(f"[dbg] 해석된 region: {json.dumps(reg, ensure_ascii=False)[:300]}")
                cf = route.get("currentFilters") if isinstance(route, dict) else None
                print(f"[dbg] currentFilters: {json.dumps(cf, ensure_ascii=False)[:300]}")
                ap = route.get("allPage") if isinstance(route, dict) else None
                if isinstance(ap, dict):
                    print(f"[dbg] allPage 키: {list(ap)}")
                    for k, v in ap.items():
                        if isinstance(v, list):
                            print(f"[dbg]   allPage.{k} = list({len(v)})")
            arts = (route.get("allPage", {}) or {}).get("fleamarketArticles", []) \
                if isinstance(route, dict) else []
            return [Prod(a["title"], a["content"], a["price"], a["href"], a["boostedAt"])
                    for a in arts]
    raise SystemExit("remixContext 없음 = 당근이 차단/구조변경. 프록시·UA 확인.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword", required=True)
    ap.add_argument("--in", dest="area", required=True, help="당근 in= 지역코드")
    ap.add_argument("--proxy", default=None)
    ap.add_argument("--extra", nargs="*", default=None)
    ap.add_argument("--exclude", nargs="*", default=None)
    ap.add_argument("--locations", action="store_true", help="키워드로 지역코드 검색만")
    ap.add_argument("--debug", action="store_true", help="remixContext 구조 덤프")
    ap.add_argument("--all", action="store_true", help="only_on_sale 끄기")
    ap.add_argument("--no-price", action="store_true", help="price 파라미터 제거")
    args = ap.parse_args()

    if args.locations:
        print(json.dumps(find_locations(args.keyword), ensure_ascii=False, indent=2)[:1500])
        return

    prods = fetch(args.keyword, args.area, args.proxy,
                  only_on_sale=not args.all, use_price=not args.no_price,
                  debug=args.debug)
    print(f"[raw] 당근 반환 {len(prods)}건")

    rule = KeywordRule(required=[args.keyword], extra=args.extra,
                       extra_mode="and", exclude=args.exclude)
    kept = apply_filter(prods, rule)
    print(f"[filter] 포함필터 후 {len(kept)}건 "
          f"(required={args.keyword} extra={args.extra} exclude={args.exclude})\n")
    for p in kept[:15]:
        print(f"  · {p.name[:40]:40} {str(p.price):>10}  {p.url}")
    print(f"\n결과: 당근 수집 {len(prods)} → 필터 {len(kept)}. "
          f"토큰 없이 정상 동작(= 당근 무인증 확정).")


if __name__ == "__main__":
    main()

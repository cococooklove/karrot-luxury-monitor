#!/usr/bin/env python3
"""검색 부분검증 — accounts.json 최신 access 로 search-bff 실호출.

LDPlayer/exe 없이 Mac 에서 검색+파싱 절반을 검증한다:
  - 토큰이 search-bff 에 통하나 (200 vs 401/403)
  - 매물이 나오나, parse_luxury 명품필터가 잡나
  - (옵션) JP 프록시 경유 vs 직접 차이

사용:
  python3 tools/test_search.py --keyword 샤넬 --region 6128 --lat 37.4837 --lon 127.0324
  python3 tools/test_search.py --keyword 루이비통 --proxy http://user:pass@host:port
"""
import argparse
import json
import os
import sys
import time

import httpx

HOST = "search-bff.kr.karrotmarket.com"
PATH = "/api/v5/fleamarket/search"
COORD = "USER_COORDINATE_TYPE_REGION_CENTER_COORDINATE"
DEFAULT_UA = "Karrot/26.34.0 (com.towneers.www; build:263400; Android 33)"


def freshest_access(accounts_fp):
    def exp(t):
        try:
            p = t.split(".")[1]; p += "=" * (-len(p) % 4)
            import base64
            return json.loads(base64.urlsafe_b64decode(p)).get("exp", 0)
        except Exception:
            return 0
    best = None
    try:
        for a in json.load(open(accounts_fp, encoding="utf-8")):
            acc = a.get("access") or ""
            if acc and (best is None or exp(acc) > exp(best[1])):
                best = (a.get("code"), acc)
    except Exception as e:
        print(f"accounts.json 로드 실패: {e}")
    if not best:
        return None, None
    return best[0], best[1]


def build_body(query, region_id, lat, lon):
    spatial = {"region": {"regionId": str(region_id)},
               "userCoordinates": [{"type": COORD,
                                    "coordinate": {"latitude": lat, "longitude": lon}}]}
    return {"query": query,
            "fleaMarket": {"filter": {"withoutCompleted": True, "spatialContext": spatial}},
            "spatialContext": spatial}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--accounts", default="data/accounts.json")
    ap.add_argument("--config", default="data/config.json", help="device 헤더(있으면 사용)")
    ap.add_argument("--keyword", default="샤넬")
    ap.add_argument("--region", default="6128")
    ap.add_argument("--lat", type=float, default=37.4837)
    ap.add_argument("--lon", type=float, default=127.0324)
    ap.add_argument("--proxy", default=None)
    a = ap.parse_args()

    code, access = freshest_access(a.accounts)
    if not access:
        print("❌ 유효 access 없음 — 폰/LDPlayer 수확 먼저 (accounts.json 확인)")
        sys.exit(2)
    now = int(time.time())
    try:
        import base64
        p = access.split(".")[1]; p += "=" * (-len(p) % 4)
        exp = json.loads(base64.urlsafe_b64decode(p)).get("exp", 0)
        print(f"계정 {str(code)[:8]} · access 만료까지 {int(exp - now)}s ({int((exp-now)/60)}분)")
    except Exception:
        pass

    headers = {"content-type": "application/json", "accept": "application/json",
               "x-user-agent": DEFAULT_UA, "x-search-tab": "fleamarket",
               "authorization": f"Bearer {access}"}
    # config.json 의 device 헤더 있으면 병합(정확도↑)
    try:
        cfg = json.load(open(a.config, encoding="utf-8")).get("headers", {})
        for k in ("x-user-agent", "user-agent", "x-device-identity", "x-ad-id",
                  "x-country-code", "x-karrot-session-id", "accept-language"):
            if k in cfg:
                headers[k] = cfg[k]
    except Exception:
        pass

    body = build_body(a.keyword, a.region, a.lat, a.lon)
    print(f"검색: '{a.keyword}' @ region {a.region} · proxy={a.proxy or '직접'}")
    try:
        client = httpx.Client(http2=True, timeout=20, proxy=a.proxy)
        r = client.post(f"https://{HOST}{PATH}", headers=headers,
                        content=json.dumps(body, ensure_ascii=False).encode())
        print(f"HTTP {r.status_code}")
        if r.status_code != 200:
            print("본문:", r.text[:300])
            sys.exit(1)
        data = r.json()
        results = data.get("results") or []
        print(f"✅ 응답 OK · 문서 {len(results)}건")
        # 제품 파서(app_api.to_article)로 파싱 — 자동모니터와 동일 경로
        try:
            sys.path.insert(0, "delivery/integrated/manual_gui")
            from daangn_ext.app_api import to_article
            docs = [it["document"] for it in results if isinstance(it, dict) and it.get("document")]
            arts = [to_article(d) for d in docs]
            kw = a.keyword
            matched = [x for x in arts if kw in (x.get("title") or "")]
            print(f"파싱 {len(arts)}건 · '{kw}' 제목매칭 {len(matched)}건 (자동모니터 KeywordRule 방식)")
            for it in matched[:6]:
                print(f"  · {(it.get('title') or '')[:44]} | {it.get('price')} | {it.get('region')}")
            if len(lux) == 0 and results:
                # 필드매핑 진단 — 실제 문서 구조 덤프
                d0 = results[0].get("document", results[0])
                print("  ── 진단: 첫 문서 키 ──")
                print("  최상위 result 키:", list(results[0].keys()))
                print("  document 키:", list(d0.keys())[:30] if isinstance(d0, dict) else type(d0))
                if isinstance(d0, dict):
                    for k in ("title", "name", "content", "price", "id", "regionName"):
                        if k in d0:
                            print(f"    {k} = {str(d0[k])[:60]}")
                    print("  전체 첫문서(축약):", json.dumps(d0, ensure_ascii=False)[:500])
        except Exception as e:
            print(f"(parse_luxury 로드 실패 — 원시 샘플): {e}")
            for rdoc in results[:3]:
                d = rdoc.get("document", rdoc)
                print("  document 키:", list(d.keys())[:25] if isinstance(d, dict) else d)
    except Exception as e:
        print(f"❌ 요청 실패: {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

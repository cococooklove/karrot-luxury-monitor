#!/usr/bin/env python3
"""제품 실함수 검증 — adaptive.collect_region (수동/자동이 실제 부르는 함수).

app-API 배선 후, 토큰 주면 collect_region 이 search-bff 로 수집하는지 확인.
robust(웹) 폴백이 아니라 앱API 로 명품이 잡히면 배선 성공.

사용: python3 tools/test_collect_region.py --keyword 샤넬 --region 강남구-6128
전제: data/accounts.json(수확된 access) + data/config.json(device 헤더) 존재.
"""
import argparse
import json
import os
import sys

# manual_gui 모듈 경로
GUI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "delivery", "integrated", "manual_gui")
sys.path.insert(0, GUI)


def freshest_access(fp):
    import base64
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
    ap.add_argument("--keyword", default="샤넬")
    ap.add_argument("--region", default="강남구-6128")   # "이름-regionId"
    a = ap.parse_args()

    token = freshest_access(a.accounts)
    if not token:
        print("❌ access 없음 — 수확 먼저"); sys.exit(2)

    if not os.path.exists("data/config.json"):
        print("⚠️ data/config.json 없음 — app-API 헤더 없어 웹크롤 폴백됨(명품 0건 예상)")

    from daangn_ext.adaptive import collect_region
    print(f"collect_region('{a.keyword}', '{a.region}') · 토큰 주입 → app-API 기대")
    arts, stats = collect_region(a.keyword, a.region, access_token=token,
                                 only_on_sale=True)
    print(f"수집 {len(arts)}건 · stats: requests={stats.get('requests')} "
          f"stopped_by={stats.get('stopped_by')} token_expired={stats.get('token_expired')}")
    for x in arts[:8]:
        # collect_region 반환은 app_source.to_article 형태 or 웹 article
        title = x.get("title") if isinstance(x, dict) else getattr(x, "title", "?")
        price = x.get("price") if isinstance(x, dict) else getattr(x, "price", "?")
        print(f"  · {str(title)[:44]} | {price}")
    if len(arts) == 0:
        print("→ 0건: 웹크롤 폴백(명품 억제) 또는 토큰/헤더 문제. config.json 확인")
    else:
        print("✅ app-API 경로로 명품 수집 확인 — 제품 실함수 검증")


if __name__ == "__main__":
    main()

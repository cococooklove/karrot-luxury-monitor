"""
통합 헤드리스 러너 — 클라 manual 프로젝트에 daangn_ext 통합된 상태로 실제 수집 시연.
GUI(PyQt) 없이 데이터층만 구동 → 통합 정상 동작 증명.

용법:
  python runner.py --keyword 구찌 --gu "강남구-381"          # 구 단위 적응형(상한돌파)
  python runner.py --keyword 샤넬 --dong "역삼동-6035"        # 동 단위(기존 호환)
  # 계정+프록시(옵션):  --accounts accounts.json
  # 필터:  --extra 정품 --exclude 레플 미러   / 가격:  --min 500000 --max 3000000
  # 저장:  --csv out.csv
"""
import argparse
import csv
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from daangn import api
from daangn_ext import (TokenManager, AccountStore, bind_to_token_manager,
                        KeywordRule)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword", required=True)
    ap.add_argument("--gu", help="구 코드(적응형): 강남구-381")
    ap.add_argument("--dong", help="동 코드(기존): 역삼동-6035")
    ap.add_argument("--extra", nargs="*", default=None)
    ap.add_argument("--exclude", nargs="*", default=None)
    ap.add_argument("--min", type=int, default=None)
    ap.add_argument("--max", type=int, default=None)
    ap.add_argument("--accounts", default=None, help="accounts.json (계정+프록시)")
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()

    # 계정+프록시 (옵션) → 검색 전 토큰 갱신
    token = proxy = None
    if args.accounts:
        store = AccountStore(args.accounts)
        tm = TokenManager()
        bind_to_token_manager(store, tm)
        print("[토큰] 검색 전 일괄 갱신:", tm.refresh_all())
        if store.rows:
            acc = list(tm.accounts.values())[0]
            token = tm.ensure_safe(acc)
            proxy = acc.proxy

    rule = KeywordRule(required=[args.keyword], extra=args.extra,
                       extra_mode="and", exclude=args.exclude)

    if args.gu:
        print(f"[적응형·구단위] {args.keyword} @ {args.gu}")
        prds = api.get_products_adaptive(
            area=args.gu, area_code=args.gu, keyword=args.keyword,
            only_tradeable=True, minimum_price=args.min, maximum_price=args.max,
            proxy=proxy, access_token=token, rule=rule)
    else:
        dong = args.dong or "역삼동-6035"
        print(f"[동단위] {args.keyword} @ {dong}")
        prds = api.get_products(
            area_code=dong, area=dong, keyword=args.keyword, only_tradeable=True,
            minimum_price=args.min, maximum_price=args.max,
            proxy=proxy, access_token=token, rule=rule)

    print(f"[결과] {len(prds)}건 (토큰헤더={'주입' if token else '없음'}, 프록시={proxy or '없음'})\n")
    for p in sorted(prds, key=lambda x: -_pi(x.price))[:12]:
        print(f"  {p.get_price_str():>14}  {p.name[:36]:36}  끌올={str(p.boostedAt)[:16]}")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["제목", "가격", "지역", "끌올", "링크", "본문"])
            for p in prds:
                w.writerow([p.name, p.get_price_str(), p.area,
                            p.boostedAt, p.url, (p.description or "")[:200]])
        print(f"\n→ CSV 저장: {args.csv} ({len(prds)}건)")


def _pi(v):
    try:
        return int(float(v))
    except Exception:
        return 0


if __name__ == "__main__":
    main()

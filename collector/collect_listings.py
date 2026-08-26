"""
매물 목록 수집 — 지역별 페이지 순회 → data/listings/<region>.jsonl

용법:
  # 캡처 템플릿의 path 로, 지역/페이지 파라미터 지정
  python collector/collect_listings.py --path "/api/v1/listings" \
      --region-param region_id --region 1234 \
      --page-param page --pages 5

파라미터 이름(region_id/page)은 캡처 query 에서 확인해 맞춰라.
동적서명 필요하면:  KARROT_FRIDA=1 python collector/collect_listings.py ...
"""
import argparse
import json
import os
from karrot_api import KarrotClient
from parse import extract

OUTDIR = "data/listings"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True)
    ap.add_argument("--region-param", default="region_id")
    ap.add_argument("--region", required=True)
    ap.add_argument("--page-param", default="page")
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--start", type=int, default=1)
    args = ap.parse_args()

    os.makedirs(OUTDIR, exist_ok=True)
    out = os.path.join(OUTDIR, f"{args.region}.jsonl")
    client = KarrotClient(args.path)

    total, seen = 0, set()
    with open(out, "w", encoding="utf-8") as f:
        for page in range(args.start, args.start + args.pages):
            params = dict(client.tpl.get("query", {}))
            params[args.region_param] = args.region
            params[args.page_param] = page
            resp = client.request(params=params)
            if resp.status_code != 200:
                print(f"page {page}: {resp.status_code} 차단/실패 — 중단. analyze_capture 재확인.")
                break
            items = extract(resp.text)
            new = [it for it in items if it["id"] not in seen]
            for it in new:
                seen.add(it["id"])
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
            total += len(new)
            print(f"page {page}: +{len(new)} (누적 {total})")
            if not new:
                print("신규 없음 — 마지막 페이지로 판단, 중단.")
                break
    client.close()
    print(f"완료: {total}건 → {out}")


if __name__ == "__main__":
    main()

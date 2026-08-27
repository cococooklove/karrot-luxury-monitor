"""명품 알림 키워드셋 생성 — parse_luxury.BRANDS 를 단일 소스로 재사용.

FINDINGS_LUXURY.md ③ 실측: 단독 브랜드명('샤넬')은 확률적으로 억제되고
접미어 조합('샤넬가방')은 12/12 성공하며 건수도 동일하다.
→ 알림 키워드도 **접미어 조합을 기본**으로 깐다.

용법:
  python3 tools/build_keyword_set.py                     # 기본셋 생성
  python3 tools/build_keyword_set.py --tier 1            # 고가 브랜드만
  python3 tools/build_keyword_set.py --suffixes 가방 지갑
산출: data/keywords_luxury.json
"""
import argparse
import json
import os
import sys

sys.path.insert(0, "collector")
from parse_luxury import BRANDS  # noqa: E402

OUT = "data/keywords_luxury.json"

# 티어 1 = 리셀 마진 큰 최상위. 계정/키워드 상한이 빡세면 여기부터.
TIER1 = ["샤넬", "에르메스", "롤렉스", "루이비통", "까르띠에", "파텍필립",
         "반클리프", "예거르쿨트"]

DEFAULT_SUFFIXES = ["가방", "지갑", "시계", "목걸이", "반지", "팔찌",
                    "벨트", "귀걸이", "클러치", "백팩"]


def canonical_brands():
    """별칭 제거한 정규 브랜드명 목록(등장 순서 유지)."""
    return list(dict.fromkeys(BRANDS.values()))


def build(tier=None, suffixes=None, bare=False):
    brands = canonical_brands()
    if tier == 1:
        brands = [b for b in brands if b in TIER1]
    suffixes = suffixes or DEFAULT_SUFFIXES
    out = []
    for b in brands:
        if bare:
            out.append({"keyword": b, "brand": b, "suffix": None})
        for s in suffixes:
            out.append({"keyword": f"{b}{s}", "brand": b, "suffix": s})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", type=int, choices=[1], default=None)
    ap.add_argument("--suffixes", nargs="*", default=None)
    ap.add_argument("--bare", action="store_true",
                    help="브랜드 단독 키워드도 포함(억제 위험)")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    items = build(args.tier, args.suffixes, args.bare)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    brands = len({i["brand"] for i in items})
    print(f"키워드 {len(items)}개 (브랜드 {brands}) → {args.out}")
    print("예시:", ", ".join(i["keyword"] for i in items[:8]))


if __name__ == "__main__":
    main()

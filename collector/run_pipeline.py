"""
턴키 진입점 — 클라 방식(LD복원+토큰) 밴회피 파이프라인 통합 실행.

두 단계:
  prep     복원 직후 인스턴스별 지문 재랜덤화 (밴 원인 #1,#2). 당근앱 실행 전 1회.
  collect  다계정 pool 로 명품 매물 수집 (#3 앱토큰읽기 + #4 프록시/워밍업 내장).

구성: data/accounts.json (ANTIBAN.md 형식)

용법:
  # 1) 각 .ldbk 복원 후, 당근앱 최초실행 전:
  python collector/run_pipeline.py prep
  # 2) 앱 로그인·토큰 안정화 후 수집:
  python collector/run_pipeline.py collect \
      --url "https://<host>/<path>" --brands 샤넬 루이비통 --regions 6530 6540
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from pool import WorkerPool                     # noqa: E402
from parse_luxury import extract, BRANDS        # noqa: E402

CONFIG = "data/accounts.json"
OUTDIR = "data/luxury"


def load_specs():
    if not os.path.exists(CONFIG):
        raise SystemExit(f"{CONFIG} 없음 — ANTIBAN.md 형식으로 계정 구성")
    return json.load(open(CONFIG, encoding="utf-8"))


def cmd_prep(_):
    """인스턴스별 고유 지문 부여. 클론 연좌밴(#1)·에뮬탐지(#2) 차단."""
    specs = load_specs()
    for s in specs:
        serial = s.get("serial")
        idx = s.get("ld_index")
        seed = s["name"]
        print(f"=== prep {s['name']} (serial={serial}, ld_index={idx}) ===")
        args = ["python3", "tools/randomize_fingerprint.py",
                "--serial", str(serial), "--seed", seed]
        if idx is not None:
            args += ["--ld-index", str(idx)]
        if s.get("ldconsole"):
            args += ["--ldconsole", s["ldconsole"]]
        subprocess.run(args)
    print("\n→ 각 인스턴스 재부팅 1회 후 당근앱 실행·로그인. 그다음 collect.")


def cmd_collect(args):
    os.makedirs(OUTDIR, exist_ok=True)
    pool = WorkerPool.from_config(use_frida=args.frida)
    brands = set(args.brands) if args.brands else None
    total, kept = 0, 0
    try:
        for region in args.regions:
            params = {args.region_param: region}
            if args.keyword:
                params[args.keyword_param] = args.keyword
            resp = pool.request("GET", args.url, params=params)
            recs = extract(resp.text)
            out = os.path.join(OUTDIR, f"{region}.jsonl")
            with open(out, "a", encoding="utf-8") as f:
                for r in recs:
                    total += 1
                    # 브랜드 필터 + 리셀 적격만
                    if brands and r.get("brand") not in brands:
                        continue
                    if not r.get("resell_ok"):
                        continue
                    kept += 1
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"region {region}: 파싱 {len(recs)} / 리셀적격 누적 {kept}")
        print("\n[pool stats]")
        for row in pool.stats():
            print(" ", row)
    finally:
        pool.close()
    print(f"완료: 원시 {total} → 리셀적격 {kept}건 → {OUTDIR}/")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("prep", help="복원후 지문 재랜덤화")
    p1.set_defaults(func=cmd_prep)

    p2 = sub.add_parser("collect", help="pool 수집")
    p2.add_argument("--url", required=True, help="캡처로 확정한 목록 엔드포인트")
    p2.add_argument("--regions", nargs="+", required=True)
    p2.add_argument("--region-param", default="region_id")
    p2.add_argument("--keyword", default=None)
    p2.add_argument("--keyword-param", default="search")
    p2.add_argument("--brands", nargs="*", default=None,
                    help=f"필터 브랜드(예 샤넬 루이비통). 미지정=전체. 사전 {len(set(BRANDS.values()))}종")
    p2.add_argument("--frida", action="store_true", help="동적서명 필요 시")
    p2.set_defaults(func=cmd_collect)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

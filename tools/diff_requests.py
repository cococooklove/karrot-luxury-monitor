"""
Phase 0 진단 핵심 — 작동 요청 vs 막힌 요청 차이 찾기.

용법:
  # 1) 캡처에서 성공/차단 요청 훑어보기 (path별 status 분포)
  python tools/diff_requests.py summary

  # 2) 특정 path 의 성공 요청과 내 프로그램 요청 헤더 diff
  #    내 요청은 data/mine.json (아래 형식)에 저장해두고 비교
  python tools/diff_requests.py diff "/api/v1/listings"

  # 3) 같은 path 를 2번 이상 캡처했을 때 헤더가 요청마다 변하는지 (동적 서명 판정)
  python tools/diff_requests.py volatility "/api/v1/listings"

data/mine.json 형식:
  {"method":"GET","path":"/api/v1/listings","req_headers":{"authorization":"Bearer ...", ...}}

산출물 해석:
  - 성공엔 있고 mine 엔 없는 헤더 = 빠진 세트 (차단 원인 후보)
  - volatility 에서 값이 매번 바뀌는 헤더 = 런타임 동적 서명 → Frida 필요
  - 값 고정 헤더만 부족 = 정적 복제로 해결
"""
import json
import sys
from collections import defaultdict

CAP = "data/capture.jsonl"
MINE = "data/mine.json"

# 요청마다 당연히 달라지는(무의미) 헤더는 가변성 판정에서 제외
IGNORE_VOLATILE = {"content-length", "date", "cookie"}


def load_cap():
    rows = []
    try:
        with open(CAP, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except FileNotFoundError:
        sys.exit(f"{CAP} 없음. 먼저 mitmproxy 캡처 실행.")
    return rows


def lower_headers(h):
    return {k.lower(): v for k, v in h.items()}


def cmd_summary():
    rows = load_cap()
    by_path = defaultdict(lambda: defaultdict(int))
    for r in rows:
        by_path[r["path"]][r["status"]] += 1
    print(f"{'STATUS/path':<50} counts")
    for path in sorted(by_path):
        stat = dict(by_path[path])
        blocked = any(s in (401, 403, 429) for s in stat)
        mark = "  <== 차단 섞임" if blocked else ""
        print(f"{path:<50} {stat}{mark}")


def cmd_diff(path):
    rows = [r for r in load_cap() if r["path"] == path]
    ok = [r for r in rows if r["status"] and 200 <= r["status"] < 300]
    if not ok:
        sys.exit(f"성공(2xx) 요청 없음: {path}")
    good = lower_headers(ok[-1]["req_headers"])
    try:
        mine = lower_headers(json.load(open(MINE, encoding="utf-8"))["req_headers"])
    except FileNotFoundError:
        sys.exit(f"{MINE} 없음. 내 프로그램 요청 헤더를 저장하라.")

    missing = {k: good[k] for k in good if k not in mine}
    differ = {k: (good[k], mine[k]) for k in good if k in mine and good[k] != mine[k]}
    extra = {k: mine[k] for k in mine if k not in good}

    print(f"=== {path} : 성공요청 vs mine ===\n")
    print("[성공엔 있고 mine엔 없음 — 차단 원인 1순위]")
    for k, v in missing.items():
        print(f"  - {k}: {v[:80]}")
    print("\n[둘 다 있으나 값 다름]")
    for k, (g, m) in differ.items():
        print(f"  ~ {k}:\n      good={g[:80]}\n      mine={m[:80]}")
    print("\n[mine에만 있음 (무해/불필요 가능)]")
    for k, v in extra.items():
        print(f"  + {k}: {v[:80]}")


def cmd_volatility(path):
    rows = [r for r in load_cap()
            if r["path"] == path and r["status"] and 200 <= r["status"] < 300]
    if len(rows) < 2:
        sys.exit(f"성공 요청 2건 이상 필요 (현재 {len(rows)}건). 같은 조회 여러 번 캡처.")
    header_vals = defaultdict(set)
    for r in rows:
        for k, v in lower_headers(r["req_headers"]).items():
            if k not in IGNORE_VOLATILE:
                header_vals[k].add(v)
    print(f"=== {path} : 헤더 가변성 ({len(rows)}건) ===\n")
    print("[매번 바뀜 → 런타임 동적 서명 의심 (Frida 필요)]")
    for k, vals in header_vals.items():
        if len(vals) > 1:
            print(f"  * {k}  ({len(vals)}종)")
    print("\n[값 고정 → 정적 복제 가능]")
    for k, vals in header_vals.items():
        if len(vals) == 1:
            print(f"  = {k}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "summary":
        cmd_summary()
    elif cmd == "diff" and len(sys.argv) > 2:
        cmd_diff(sys.argv[2])
    elif cmd == "volatility" and len(sys.argv) > 2:
        cmd_volatility(sys.argv[2])
    else:
        sys.exit(__doc__)

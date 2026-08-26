"""
토큰(인증) 있을 때 vs 없을 때 응답 차이 검증.

원리: 같은 path 에 대해 캡처된 요청을 인증 유무로 나눠 응답을 비교.
 - status / 응답크기 / 매물 건수 / JSON 키셋 / 매물 필드 차이

캡처 방법 (mitmproxy 뜬 상태):
  1) 브라우저/앱 로그인 상태로 매물 목록 조회      (인증 O)
  2) 시크릿창/로그아웃 상태로 같은 목록 조회         (인증 X)
  → data/capture.jsonl 에 둘 다 쌓임

용법:
  python tools/verify_auth_diff.py                 # path별 auth유무 요약
  python tools/verify_auth_diff.py "/<path>"       # 특정 path 상세 diff
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "collector"))
import parse

CAP = "data/capture.jsonl"
AUTH_HDRS = ("authorization", "cookie", "x-auth-token", "x-access-token")


def load():
    try:
        return [json.loads(l) for l in open(CAP, encoding="utf-8") if l.strip()]
    except FileNotFoundError:
        raise SystemExit(f"{CAP} 없음. 먼저 캡처.")


def is_authed(rec):
    h = {k.lower(): v for k, v in rec["req_headers"].items()}
    return any(k in h and h[k] for k in AUTH_HDRS)


def parse_body(rec):
    try:
        return parse.extract(rec.get("resp_body", "") or "{}")
    except Exception:
        return []


def summary(rows):
    from collections import defaultdict
    paths = defaultdict(lambda: {"auth": 0, "noauth": 0})
    for r in rows:
        if not (r["status"] and 200 <= r["status"] < 300):
            continue
        paths[r["path"]]["auth" if is_authed(r) else "noauth"] += 1
    print(f"{'path':<50} auth noauth")
    for p, c in sorted(paths.items()):
        both = "  ← 양쪽 다 있음(비교가능)" if c["auth"] and c["noauth"] else ""
        print(f"{p:<50} {c['auth']:>4} {c['noauth']:>6}{both}")
    print("\n'양쪽 다 있음' path 로: python tools/verify_auth_diff.py \"<path>\"")


def detail(rows, path):
    a = [r for r in rows if r["path"] == path and is_authed(r)
         and r["status"] and 200 <= r["status"] < 300]
    n = [r for r in rows if r["path"] == path and not is_authed(r)
         and r["status"] and 200 <= r["status"] < 300]
    if not a or not n:
        sys.exit(f"비교 불가: 인증O {len(a)}건 / 인증X {len(n)}건. 둘 다 캡처 필요.")
    ra, rn = a[-1], n[-1]
    ia, iny = parse_body(ra), parse_body(rn)

    print(f"=== {path} : 인증 O vs X ===\n")
    print(f"응답크기:  auth={ra['resp_len']:>8}   noauth={rn['resp_len']:>8}   "
          f"차이={ra['resp_len']-rn['resp_len']:+}")
    print(f"매물건수:  auth={len(ia):>8}   noauth={len(iny):>8}   "
          f"차이={len(ia)-len(iny):+}")

    # 매물 1건 필드셋 비교
    if ia and iny:
        ka = set(ia[0]["_raw"].keys())
        kn = set(iny[0]["_raw"].keys())
        only_auth = ka - kn
        only_no = kn - ka
        print(f"\n[인증 O 에만 있는 필드] {sorted(only_auth) or '없음'}")
        print(f"[인증 X 에만 있는 필드] {sorted(only_no) or '없음'}")

    print("\n해석:")
    print(" - 건수/크기 차이 크면 → 토큰이 더 많은 매물/데이터 노출 (웹 세션으로 대체 가능한지 확인)")
    print(" - '인증 O 에만 있는 필드' = 토큰 없으면 못 얻는 데이터 (연락처·상세 등)")
    print(" - 차이 거의 없으면 → 웹/비인증 경로로 충분 = 토큰·에뮬 불필요")


if __name__ == "__main__":
    rows = load()
    if len(sys.argv) > 1:
        detail(rows, sys.argv[1])
    else:
        summary(rows)

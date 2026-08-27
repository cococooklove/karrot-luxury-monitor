"""키워드 알림 등록/목록/삭제 경로를 OPTIONS 프리플라이트로 탐색한다.

왜 OPTIONS 인가:
  캡처 실측상 이 API 는 웹뷰 호출이라 CORS 프리플라이트가 붙는다
  (`OPTIONS /api/v1/fleamarket/keyword/notification/info` → 204).
  OPTIONS 는 **인증 불필요·계정 상태 변경 없음** 이므로 등록을 실제로
  실행하지 않고도 경로 존재 여부와 허용 메서드를 알아낼 수 있다.

용법:
  python3 tools/probe_keyword_endpoints.py            # 후보 경로 전부 프로브
  python3 tools/probe_keyword_endpoints.py --write    # 찾은 경로를 스펙에 반영

찾지 못하면 앱 조작 캡처(docs/KEYWORD_ALERT_CAPTURE.md)로 간다.
"""
import argparse
import sys
import time

import httpx

sys.path.insert(0, "collector")
from keyword_alert import HOST, load_spec, save_spec  # noqa: E402

ORIGIN = "https://search.kr.karrotwebview.com"

BASES = [
    "/api/v1/fleamarket/keyword/notification",
    "/api/v1/fleamarket/keyword/notifications",
    "/api/v1/fleamarket/keyword/alarm",
    "/api/v1/fleamarket/keyword-notification",
    "/api/v1/keyword/notification",
    "/api/v2/fleamarket/keyword/notification",
]
SUFFIXES = ["", "/list", "/keywords", "/info", "/register", "/subscribe", "/count"]
METHODS = ["GET", "POST", "DELETE"]


def preflight(client, path, method):
    """OPTIONS 프리플라이트 1회. (status, allow-methods) 반환."""
    url = f"https://{HOST}{path}"
    headers = {
        "origin": ORIGIN,
        "access-control-request-method": method,
        "access-control-request-headers": "authorization,content-type",
        "user-agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                       "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"),
    }
    try:
        r = client.request("OPTIONS", url, headers=headers)
    except Exception as e:
        return None, f"예외 {e}"
    allow = (r.headers.get("access-control-allow-methods")
             or r.headers.get("allow") or "")
    return r.status_code, allow


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="찾은 경로를 스펙에 저장")
    ap.add_argument("--gap", type=float, default=0.4, help="요청 간격(초)")
    args = ap.parse_args()

    paths = []
    for b in BASES:
        for s in SUFFIXES:
            p = b + s
            if p not in paths:
                paths.append(p)

    hits = {}
    with httpx.Client(http2=True, timeout=12) as client:
        print(f"프로브 {len(paths)}경로 × {len(METHODS)}메서드 "
              f"(OPTIONS 만 — 계정 상태 안 건드림)\n")
        for p in paths:
            allows = set()
            status = None
            for m in METHODS:
                st, allow = preflight(client, p, m)
                time.sleep(args.gap)
                if st is None:
                    continue
                status = st
                if 200 <= st < 300:
                    allows.update(x.strip().upper()
                                  for x in allow.split(",") if x.strip())
            if allows:
                hits[p] = sorted(allows)
                print(f"  ✅ {p:52s} allow={','.join(sorted(allows))}")
            elif status and status not in (404, 405):
                print(f"  ?  {p:52s} status={status}")

    if not hits:
        print("\n찾은 경로 없음. → docs/KEYWORD_ALERT_CAPTURE.md 절차 2번(앱 조작 캡처).")
        sys.exit(2)

    # 위양성 가드 — 실측(2026-08-27): 이 서버는 CORS 프리플라이트에서 경로를 검증하지
    # 않고 존재하지 않는 경로에도 allow-all 을 돌려준다. 그 상태에서 --write 하면
    # 스펙이 가짜 경로로 오염되고, 등록이 조용히 실패한다.
    ratio = len(hits) / len(paths)
    allow_all = sum(1 for a in hits.values() if len(a) >= 5) / max(len(hits), 1)
    if ratio > 0.8 or allow_all > 0.8:
        print(f"\n⚠️ 위양성 — {len(hits)}/{len(paths)} 경로가 전부 통과했다.")
        print("   이 서버의 프리플라이트는 경로 존재 여부를 검증하지 않는다.")
        print("   OPTIONS 탐색으로는 확정 불가 → docs/KEYWORD_ALERT_CAPTURE.md 절차 2번")
        print("   (앱에서 알림 벨 탭 → 캡처)로 진행하라. --write 는 막는다.")
        sys.exit(2)

    print(f"\n후보 {len(hits)}개.")
    if not args.write:
        print("스펙에 반영하려면 --write")
        return

    spec = load_spec()
    for p, allows in hits.items():
        tail = p.rsplit("/", 1)[-1]
        if tail == "info":
            continue  # 이미 확정
        if "POST" in allows and not spec["register"].get("path"):
            spec["register"]["path"] = p
            spec["register"]["method"] = "POST"
        if "DELETE" in allows and not spec["unregister"].get("path"):
            spec["unregister"]["path"] = p
            spec["unregister"]["method"] = "DELETE"
        if "GET" in allows and not spec["list"].get("path") and tail != "info":
            spec["list"]["path"] = p
            spec["list"]["method"] = "GET"
    save_spec(spec)
    print("스펙 반영 완료. 실제 동작은 body 스키마가 맞아야 하므로")
    print("등록 1건 테스트(tools/setup_keyword_alerts.py --dry-run)로 확인하라.")


if __name__ == "__main__":
    main()

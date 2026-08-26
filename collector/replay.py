"""
Phase 1 (정적 헤더 부족 경로) — 캡처한 성공 요청의 헤더를 전량 재현해 토큰 요청.

diff 결과 "빠진 헤더" 가 정적이면 이걸로 차단 우회 가능.
동적 서명이면 여기 sign() 를 Frida RPC 로 채워야 함 (TODO 표시).

용법:
  # capture.jsonl 에서 특정 path 의 성공요청을 템플릿으로 뽑아 재생
  python collector/replay.py "/api/v1/listings"

  # 지역/페이지 파라미터 바꿔 요청
  python collector/replay.py "/api/v1/listings" --query region_id=1234 --query page=2
"""
import argparse
import json
import sys
import httpx

CAP = "data/capture.jsonl"

# 재생 시 httpx 가 알아서 관리 → 원본에서 제거할 헤더
DROP = {"content-length", "host", "connection", "accept-encoding"}


def load_template(path):
    ok = None
    with open(CAP, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r["path"] == path and r["status"] and 200 <= r["status"] < 300:
                ok = r  # 마지막 성공요청 사용
    if not ok:
        sys.exit(f"성공 요청 없음: {path}. summary 로 path 확인.")
    return ok


def sign(headers, body):
    """동적 서명 경로에서만 사용. Frida RPC 로 유효 서명 계산해 헤더에 주입.
    정적 헤더 경로면 그대로 통과."""
    # TODO(동적 서명): frida 로 앱 서명함수 후킹 → 여기서 호출해 headers['x-...signature'] 갱신
    return headers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--query", action="append", default=[], help="key=value 반복 가능")
    args = ap.parse_args()

    tpl = load_template(args.path)
    headers = {k: v for k, v in tpl["req_headers"].items() if k.lower() not in DROP}
    params = dict(tpl.get("query", {}))
    for kv in args.query:
        k, _, v = kv.partition("=")
        params[k] = v

    headers = sign(headers, tpl.get("req_body", ""))
    url = f"https://{tpl['host']}{tpl['path']}"

    with httpx.Client(http2=True, timeout=15) as c:
        resp = c.request(tpl["method"], url, headers=headers, params=params)
    print(f"{resp.status_code} {resp.request.url}")
    if resp.status_code in (401, 403, 429):
        print("차단됨. diff 로 아직 빠진 헤더/서명 확인. 값 가변이면 sign() 구현 필요.")
    else:
        text = resp.text
        print(text[:800])


if __name__ == "__main__":
    main()

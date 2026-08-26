"""
mitmproxy 애드온 — 당근 API 요청/응답을 JSONL로 덤프.

실행:
  mitmproxy -s capture/karrot_dump.py        # 대화형(요청 흐름 눈으로 확인)
  mitmdump -s capture/karrot_dump.py         # 헤드리스 덤프

LD플레이어/기기 프록시를 이 PC:8080 으로, mitm 루트 인증서를 시스템 신뢰 저장소에 설치.
cert pinning 있으면 objection/frida 로 unpinning 후 진행.

산출물: data/capture.jsonl  (요청 1건 = 1줄)
필드: ts, method, url, host, path, query, req_headers, req_body, status, resp_headers, resp_len
"""
import json
import time
from mitmproxy import http

OUT = "data/capture.jsonl"

# 당근 관련 호스트만 (필요 시 추가). 캡처 후 실제 host 로 좁혀라.
HOST_MATCH = ("daangn.com", "karrotmarket.com", "kr.karrotmarket", "towneers")


def _match(host: str) -> bool:
    return any(m in host for m in HOST_MATCH)


def response(flow: http.HTTPFlow) -> None:
    host = flow.request.host
    if not _match(host):
        return
    req = flow.request
    resp = flow.response
    try:
        body = req.get_text(strict=False) if req.content else ""
    except Exception:
        body = "<binary>"
    try:
        resp_body = resp.get_text(strict=False) if (resp and resp.content) else ""
    except Exception:
        resp_body = "<binary>"
    rec = {
        "ts": round(time.time(), 3),
        "method": req.method,
        "url": req.pretty_url,
        "host": host,
        "path": req.path.split("?", 1)[0],
        "query": dict(req.query),
        "req_headers": dict(req.headers),
        "req_body": body[:4000],
        "status": resp.status_code if resp else None,
        "resp_headers": dict(resp.headers) if resp else {},
        "resp_len": len(resp.content) if (resp and resp.content) else 0,
        "resp_body": resp_body[:20000],
    }
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    # 콘솔에 한 줄 요약 (막힌 요청 즉시 식별)
    flag = "  <== BLOCKED?" if resp and resp.status_code in (401, 403, 429) else ""
    print(f"[karrot] {rec['status']} {req.method} {rec['path']}{flag}")

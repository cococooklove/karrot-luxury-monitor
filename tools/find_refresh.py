"""capture.jsonl 에서 토큰 갱신(refresh→access) 요청을 찾아낸다.

TOKEN_REFRESH_CAPTURE.md 4단계용. Frida unpinning 후 갱신을 유발하면
api.kr.karrotmarket.com 으로 교환 요청이 나간다. 그걸 자동으로 골라
token_manager 에 넣을 URL·body·응답키를 뽑아준다.

실행: python tools/find_refresh.py [capture.jsonl 경로]

토큰 실값은 마스킹해서 출력한다(로그/공유 안전).
"""
import json
import re
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "data/capture.jsonl"

# 갱신 요청의 신호들
HINT_PATH = re.compile(r"(token|oauth|refresh|access|session|credential|grant)", re.I)
HINT_BODY = re.compile(r"(refresh_token|grant_type|refreshToken|refresh-token)", re.I)
AUTH_HOSTS = ("api.kr.karrotmarket.com", "auth", "account", "identity", "oauth")


def mask(v):
    s = str(v)
    if len(s) > 20:
        return s[:6] + f"…<{len(s)}자>…" + s[-4:]
    return s


def mask_obj(o):
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if re.search(r"token|secret|auth|code|key|password", k, re.I) and isinstance(v, str):
                out[k] = mask(v)
            else:
                out[k] = mask_obj(v)
        return out
    if isinstance(o, list):
        return [mask_obj(x) for x in o]
    return o


def looks_like_refresh(d):
    method = d.get("method", "")
    path = d.get("path") or ""
    host = d.get("host") or ""
    body = d.get("req_body") or ""
    score = 0
    if method == "POST":
        score += 1
    if HINT_PATH.search(path):
        score += 2
    if any(h in host for h in AUTH_HOSTS):
        score += 2
    if HINT_BODY.search(str(body)):
        score += 3
    # 응답에 access_token 이 새로 담기면 결정적
    resp = str(d.get("resp_body") or d.get("resp_snippet") or "")
    if re.search(r"access_?token|accessToken", resp, re.I):
        score += 3
    return score


def main():
    try:
        rows = [json.loads(l) for l in open(PATH, encoding="utf-8") if l.strip()]
    except FileNotFoundError:
        print(f"캡처 파일 없음: {PATH}")
        sys.exit(1)

    scored = sorted(((looks_like_refresh(d), d) for d in rows),
                    key=lambda x: -x[0])
    hits = [(s, d) for s, d in scored if s >= 4]

    if not hits:
        print("갱신 요청으로 보이는 것 없음.")
        print("점검: (1) Frida unpinning 이 켜졌는지 (2) 토큰을 실제로 만료시켰는지")
        print("      (3) api.kr.karrotmarket.com TLS 실패가 사라졌는지(mitm 로그)")
        # 그래도 인증 호스트로 간 것들은 보여준다
        auth = [d for d in rows if any(h in (d.get("host") or "") for h in AUTH_HOSTS)]
        if auth:
            print(f"\n인증 호스트로 간 요청 {len(auth)}건(참고):")
            for d in auth[:10]:
                print(f"  {d.get('method'):5s} {d.get('host')}{d.get('path')} → {d.get('status')}")
        sys.exit(2)

    print(f"갱신 후보 {len(hits)}건 (점수순)\n")
    for score, d in hits[:5]:
        print("=" * 66)
        print(f"점수 {score}")
        print(f"{d.get('method')} {d.get('host')}{d.get('path')} → {d.get('status')}")
        if d.get("query"):
            print("query:", json.dumps(mask_obj(d["query"]), ensure_ascii=False)[:300])
        body = d.get("req_body")
        if body:
            try:
                body = json.loads(body) if isinstance(body, str) else body
            except Exception:
                pass
            print("req_body:", json.dumps(mask_obj(body), ensure_ascii=False)[:400]
                  if not isinstance(body, str) else mask(body)[:400])
        hdrs = {k: (mask(v) if re.search(r"auth|token|key|secret", k, re.I) else v)
                for k, v in (d.get("req_headers") or {}).items()}
        print("req_headers 키:", sorted(hdrs))
        resp = d.get("resp_body") or d.get("resp_snippet")
        if resp:
            try:
                rj = json.loads(resp) if isinstance(resp, str) else resp
                print("resp 키:", sorted(rj.keys()) if isinstance(rj, dict) else type(rj).__name__)
            except Exception:
                print("resp(앞부분):", str(resp)[:200])

    print("\n" + "=" * 66)
    print("다음: 위 URL·body·응답키를 collector/token_manager.py 의")
    print("      REFRESH_URL 과 _default_refresh() 에 반영.")


if __name__ == "__main__":
    main()

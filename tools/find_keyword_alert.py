"""capture.jsonl 에서 키워드 알림(등록/조회/삭제) 요청을 찾아낸다.

절차는 docs/KEYWORD_ALERT_CAPTURE.md 참고.
앱에서 [나의 당근 → 키워드 알림] 을 열고 키워드 추가/삭제를 하면
그 트래픽이 capture.jsonl 에 쌓인다. 그걸 자동으로 골라
엔드포인트·요청 본문·응답 스키마·개수 상한을 뽑아준다.

실행: python tools/find_keyword_alert.py [capture.jsonl 경로]

토큰 실값은 마스킹해서 출력한다(로그/공유 안전).
"""
import json
import re
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "data/capture.jsonl"

# 키워드 알림 요청의 신호들
HINT_PATH = re.compile(
    r"(keyword|alarm|alert|notification|subscription|subscribe|watch|"
    r"saved.?search|search.?alert|following|follow)", re.I)
HINT_BODY = re.compile(
    r"(keyword|alarm|alert|notification|subscri|regionId|region_id)", re.I)
# 개수 상한이 응답에 실릴 때 흔한 키
HINT_LIMIT = re.compile(
    r"(max[_A-Za-z]*|limit|quota|remain|available|count|exceed|초과|최대|개까지)", re.I)

NOISE_PATH = re.compile(r"\.(png|jpg|jpeg|webp|gif|css|js|woff2?)$", re.I)


def mask(v):
    s = str(v)
    return s[:6] + f"…<{len(s)}자>…" + s[-4:] if len(s) > 20 else s


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


def score_row(d):
    path = d.get("path") or ""
    if NOISE_PATH.search(path):
        return 0
    method = d.get("method", "")
    body = str(d.get("req_body") or "")
    resp = str(d.get("resp_body") or d.get("resp_snippet") or "")
    s = 0
    if HINT_PATH.search(path):
        s += 4
    if method in ("POST", "PUT", "DELETE", "PATCH"):
        s += 1
    if HINT_BODY.search(body):
        s += 2
    if HINT_PATH.search(resp):
        s += 2
    if d.get("status") in (400, 409, 422, 429):   # 상한 초과 응답일 가능성
        s += 2
    return s


def dump(d, score):
    print("=" * 66)
    print(f"점수 {score}")
    print(f"{d.get('method')} {d.get('host')}{d.get('path')} → {d.get('status')}")
    if d.get("query"):
        print("query:", json.dumps(mask_obj(d["query"]), ensure_ascii=False)[:300])
    body = d.get("req_body")
    if body:
        try:
            body = json.loads(body)
        except Exception:
            pass
        print("req_body:", (json.dumps(mask_obj(body), ensure_ascii=False)[:600]
                            if not isinstance(body, str) else mask(body)[:600]))
    print("req_headers 키:", sorted((d.get("req_headers") or {}).keys()))
    resp = d.get("resp_body") or d.get("resp_snippet")
    if resp:
        try:
            rj = json.loads(resp)
            print("resp 키:", sorted(rj.keys()) if isinstance(rj, dict) else type(rj).__name__)
            print("resp(앞부분):", json.dumps(mask_obj(rj), ensure_ascii=False)[:800])
        except Exception:
            print("resp(앞부분):", str(resp)[:400])
        hits = sorted(set(HINT_LIMIT.findall(str(resp))))
        if hits:
            print("★ 상한 후보 키워드:", hits[:15])


def main():
    try:
        rows = [json.loads(l) for l in open(PATH, encoding="utf-8") if l.strip()]
    except FileNotFoundError:
        print(f"캡처 파일 없음: {PATH}")
        sys.exit(1)

    scored = sorted(((score_row(d), d) for d in rows), key=lambda x: -x[0])
    hits = [(s, d) for s, d in scored if s >= 4]

    if not hits:
        print("키워드 알림 요청으로 보이는 것 없음.")
        print("점검: (1) 앱에서 실제로 키워드 알림 화면을 열고 추가/삭제 했는지")
        print("      (2) api.kr.karrotmarket.com 이면 Frida unpinning 필요 (TLS 실패 로그 확인)")
        print("      (3) 웹뷰 경로면 host 가 webapp/webview 일 수 있음")
        hosts = {}
        for d in rows:
            hosts[d.get("host")] = hosts.get(d.get("host"), 0) + 1
        print("\n캡처된 호스트 분포:")
        for h, c in sorted(hosts.items(), key=lambda x: -x[1]):
            print(f"  {c:5d}  {h}")
        sys.exit(2)

    # 메서드별로 대표 요청을 보여준다 (조회 GET / 등록 POST / 삭제 DELETE)
    print(f"키워드 알림 후보 {len(hits)}건 (점수순)\n")
    seen = set()
    for score, d in hits:
        key = (d.get("method"), d.get("host"), d.get("path"))
        if key in seen:
            continue
        seen.add(key)
        dump(d, score)
        if len(seen) >= 8:
            break

    print("\n" + "=" * 66)
    print("다음: 등록(POST) 요청의 URL·body 를 계정 세팅 스크립트에,")
    print("      조회(GET) 응답 스키마를 알림 목록 동기화에 반영.")


if __name__ == "__main__":
    main()

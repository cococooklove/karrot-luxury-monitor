"""
캡처에서 인증/디바이스 헤더 뽑아 data/config.json 으로.
(재생·수집은 karrot_api 가 템플릿 통째로 쓰므로 필수는 아님. 값 확인/보관용.)

용법:
  python tools/extract_token.py
"""
import json
import re

CAP = "data/capture.jsonl"
OUT = "data/config.json"
WANT = re.compile(r"(authorization|auth|token|device|udid|uuid|user-agent|"
                  r"x-app|version|sign|integrity)", re.I)


def main():
    tpl = None
    try:
        cap = open(CAP, encoding="utf-8")
    except FileNotFoundError:
        raise SystemExit(f"{CAP} 없음. 먼저 mitmproxy 캡처 실행.")
    with cap as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r["status"] and 200 <= r["status"] < 300:
                tpl = r
    if not tpl:
        raise SystemExit("성공 요청 없음.")
    picked = {k: v for k, v in tpl["req_headers"].items() if WANT.search(k)}
    cfg = {"host": tpl["host"], "sample_path": tpl["path"], "headers": picked}
    json.dump(cfg, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"→ {OUT}")
    for k, v in picked.items():
        print(f"  {k}: {v[:60]}")


if __name__ == "__main__":
    main()

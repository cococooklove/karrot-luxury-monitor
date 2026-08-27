"""새 액세스 토큰을 data/config.json 에 꽂고 즉시 검증한다.

access 토큰 TTL 은 30분이라 캡처/추출한 값을 손으로 붙이면 이미 만료돼 있기 쉽다.
이 도구가 남은 수명을 먼저 알려주고, --verify 로 실호출 1건까지 확인한다.

용법:
  python3 tools/set_token.py "eyJhbG..."           # 토큰 직접
  pbpaste | python3 tools/set_token.py -           # 클립보드/파이프
  python3 tools/set_token.py --file token.txt --verify
  python3 tools/set_token.py --check               # 쓰기 없이 현재 토큰 상태만
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "collector"))

from token_manager import _jwt_payload, token_exp  # noqa: E402

CONFIG = os.path.join(ROOT, "data", "config.json")


def clean(raw):
    t = (raw or "").strip().strip('"').strip("'")
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    # 줄바꿈/공백이 섞여 들어온 경우 복구
    return "".join(t.split())


def describe(token):
    payload = _jwt_payload(token)
    if not payload:
        return None, "JWT 디코드 실패 — 액세스 토큰이 맞는지 확인"
    exp = token_exp(token)
    left = exp - int(time.time())
    info = {
        "code": payload.get("code"),
        "exp": exp,
        "left_sec": left,
        "refresh_token_id": payload.get("refresh_token_id"),
    }
    if left <= 0:
        return info, f"이미 만료됨 ({-left}초 지남)"
    return info, None


def load_config():
    if not os.path.exists(CONFIG):
        return {"endpoint": "", "headers": {}}
    return json.load(open(CONFIG, encoding="utf-8"))


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)
    os.chmod(CONFIG, 0o600)


def verify():
    """info 엔드포인트 1건으로 실제 유효성 확인."""
    from keyword_alert import KeywordAlertClient
    c = KeywordAlertClient()
    try:
        d = c.info("샤넬")
        print("검증 OK →", json.dumps(d, ensure_ascii=False))
        return True
    except Exception as e:
        print("검증 실패:", str(e)[:200])
        return False
    finally:
        c.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("token", nargs="?", help='토큰 문자열, 또는 "-" 로 stdin')
    ap.add_argument("--file", help="토큰이 든 파일")
    ap.add_argument("--check", action="store_true", help="현재 config 토큰 상태만 출력")
    ap.add_argument("--verify", action="store_true", help="쓴 뒤 실호출 1건으로 검증")
    args = ap.parse_args()

    cfg = load_config()

    if args.check:
        cur = clean(cfg.get("headers", {}).get("authorization", ""))
        if not cur:
            raise SystemExit("config 에 authorization 없음")
        info, err = describe(cur)
        print(json.dumps(info, ensure_ascii=False))
        print("상태:", err or f"유효 — 남은 수명 {info['left_sec']}초")
        if args.verify:
            sys.exit(0 if verify() else 1)
        sys.exit(1 if err else 0)

    if args.file:
        raw = open(args.file, encoding="utf-8").read()
    elif args.token == "-" or (args.token is None and not sys.stdin.isatty()):
        raw = sys.stdin.read()
    elif args.token:
        raw = args.token
    else:
        raise SystemExit("토큰 필요 — 인자/--file/stdin 중 하나")

    token = clean(raw)
    if not token:
        raise SystemExit("빈 토큰")
    info, err = describe(token)
    if info:
        print(json.dumps(info, ensure_ascii=False))
    if err:
        print("⚠️", err)
        if info is None:
            sys.exit(1)

    prev = clean(cfg.get("headers", {}).get("authorization", ""))
    if prev and prev == token:
        print("기존 토큰과 동일 — 갱신 안 된 값일 수 있다")
    cfg.setdefault("headers", {})["authorization"] = "Bearer " + token
    save_config(cfg)
    print(f"저장 완료 → {CONFIG} (0600)")
    if info and info.get("left_sec", 0) > 0:
        print(f"남은 수명 {info['left_sec']}초 — 이 안에 테스트 끝내야 한다")

    if args.verify:
        sys.exit(0 if verify() else 1)


if __name__ == "__main__":
    main()

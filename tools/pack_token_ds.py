#!/usr/bin/env python3
"""karrot_token.ds (Jetpack Proto DataStore, 평문) 빌더 — extract_tokens.parse_token_ds 의 역방향.

메시지 스키마(디컴파일 확정): field1=refresh, 2=access, 3=auth. 전부 wire2 string.
파일 = 헤더 없는 순수 직렬화 proto (DataStore Serializer.writeTo 원본).

용도:
  1) 세션복원 주입: accounts.json 의 refresh/access → 각 계정 karrot_token.ds 생성 → 폰 앱에 주입
  2) 클라 소용량 재요청: 회전 후 최신 토큰 필요 시, 7GB .ldbk 대신 이 파일(계정당 ~1KB)만 받으면 됨

사용:
  # accounts.json 전체 → out/<code>/karrot_token.ds
  python3 tools/pack_token_ds.py --from-accounts data/accounts.json --out-dir out/sessions
  # 단건
  python3 tools/pack_token_ds.py --refresh <JWT> --access <JWT> -o karrot_token.ds
"""
import argparse, json, os, re, sys

FIELD_TAG = {1: 0x0A, 2: 0x12, 3: 0x1A}   # (field<<3)|2


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _field(num: int, val: str) -> bytes:
    raw = val.encode("utf-8")
    return bytes([FIELD_TAG[num]]) + _varint(len(raw)) + raw


def _secure_write(fp: str, blob: bytes):
    """0o600 으로 생성부터(chmod 창 없음)."""
    fd = os.open(fp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(blob)


def pack(refresh: str = "", access: str = "", auth: str = "") -> bytes:
    buf = bytearray()
    if refresh:
        buf += _field(1, refresh)
    if access:
        buf += _field(2, access)
    if auth:
        buf += _field(3, auth)
    return bytes(buf)


def _selftest():
    """parse_token_ds 로 round-trip 검증."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "collector"))
    sys.path.insert(0, os.path.dirname(__file__))
    from extract_tokens import parse_token_ds
    samples = [
        {"refresh": "eyJhbGciOiJFUzI1NiJ9.reFReSh.sig", "access": "eyJhbGciOiJFUzI1NiJ9.AcCeSs.sig"},
        {"refresh": "r" * 700, "access": "a" * 900, "auth": "x" * 40},  # 긴 토큰: varint 2바이트 길이 경계
        {"refresh": "only-refresh"},
    ]
    ok = True
    for s in samples:
        blob = pack(**s)
        back = parse_token_ds(blob)
        for k, v in s.items():
            if back.get(k) != v:
                print(f"FAIL {k}: in={v[:20]!r} out={back.get(k)!r}")
                ok = False
    print("round-trip", "✅ PASS" if ok else "❌ FAIL")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-accounts")
    ap.add_argument("--out-dir", default="out/sessions")
    ap.add_argument("--refresh", default="")
    ap.add_argument("--access", default="")
    ap.add_argument("--auth", default="")
    ap.add_argument("-o", "--out")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        sys.exit(0 if _selftest() else 1)

    if a.from_accounts:
        accts = json.load(open(a.from_accounts, encoding="utf-8"))
        n = 0
        for acc in accts:
            code = str(acc.get("code") or acc.get("label") or n)
            code = re.sub(r"[^A-Za-z0-9_-]", "_", code)   # path traversal 방지(디렉토리명 화이트리스트)
            if not code:
                code = str(n)
            blob = pack(acc.get("refresh", ""), acc.get("access", ""), acc.get("auth", ""))
            d = os.path.join(a.out_dir, code)
            os.makedirs(d, exist_ok=True)
            fp = os.path.join(d, "karrot_token.ds")
            _secure_write(fp, blob)
            print(f"  {code}: {len(blob)}B → {fp}")
            n += 1
        print(f"완료: {n}계정")
        return

    blob = pack(a.refresh, a.access, a.auth)
    if a.out:
        _secure_write(a.out, blob)
        print(f"{len(blob)}B → {a.out}")
    else:
        sys.stdout.buffer.write(blob)


if __name__ == "__main__":
    main()

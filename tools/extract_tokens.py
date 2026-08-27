"""에뮬레이터 이미지/앱 데이터 백업/shared_prefs 에서 당근 토큰을 추출한다.

클라이언트가 준 계정 데이터(에뮬 이미지 또는 /data/data 백업)에서
refresh 토큰 + 디바이스 헤더를 뽑아 accounts.json 을 만든다.

저장 위치·형식을 몰라도 되도록 **JWT 패턴을 전수 스캔**하고 claim 으로 분류한다:
  - access:  exp-iat ≈ 1800s(30분), payload type/짧은 TTL
  - refresh: exp-iat 김(수시간+), payload type:refresh
계정 식별 = payload.sub (또는 code). 계정별로 최신 refresh 를 채택.

디바이스 헤더(x-device-identity 등)는 prefs/xml 에서 정규식으로 부수 추출.

사용:
  python tools/extract_tokens.py <스캔경로> [--out data/accounts.json]
  # <스캔경로> = 압축 푼 백업 디렉토리, 또는 마운트된 에뮬 이미지, 또는 shared_prefs 폴더

주의:
  - 토큰은 비밀. 출력 파일은 0600. 콘솔엔 마스킹만.
  - EncryptedSharedPreferences(Keystore 암호화)면 평문 JWT 가 안 보인다 →
    "JWT 0건"이면 암호화 저장 → 이 방법 불가(에뮬 런타임 추출 필요) 안내.
"""
import argparse
import base64
import json
import os
import re
import sys
import time

JWT_RE = re.compile(rb'eyJ[A-Za-z0-9_-]{6,}\.eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}')
# 디바이스 헤더 후보(prefs/xml/json 안 어디든)
HDR_KEYS = ("x-device-identity", "device_identity", "deviceIdentity", "device_id",
            "x-ad-id", "advertising_id", "x-karrot-session-id", "session_id",
            "x-user-agent")
HDR_RE = re.compile(
    r'(?i)(device[_-]?identity|device[_-]?id|ad[_-]?id|advertising[_-]?id|'
    r'karrot[_-]?session[_-]?id|session[_-]?id)["\'>\s:=]{1,4}([A-Za-z0-9\-]{16,})')

SCAN_EXT_SKIP = (".so", ".dex", ".png", ".jpg", ".webp", ".ttf", ".tflite",
                 ".mp4", ".zip", ".apk", ".jar", ".001", ".vdi")
MAX_FILE = 20 * 1024 * 1024        # 20MB 넘는 파일은 스킵(이미지 blob 등)


def jwt_payload(tok: str) -> dict:
    try:
        p = tok.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p))
    except Exception:
        return {}


def classify(tok: str):
    """(kind, sub, ttl). kind ∈ {access, refresh, other}."""
    pl = jwt_payload(tok)
    if not pl:
        return None
    exp = pl.get("exp")
    iat = pl.get("iat")
    sub = str(pl.get("sub") or pl.get("code") or pl.get("user_id") or "?")
    typ = str(pl.get("type") or "").lower()
    ttl = (exp - iat) if (exp and iat) else None
    now = int(time.time())
    alive = (exp - now) if exp else None
    kind = "other"
    if typ == "refresh" or (ttl and ttl > 3600):
        kind = "refresh"
    elif typ == "access" or (ttl and ttl <= 3600):
        kind = "access"
    return {"kind": kind, "sub": sub, "ttl": ttl, "alive": alive,
            "exp": exp, "token": tok, "client": pl.get("client_name")}


def mask(t: str) -> str:
    return t[:12] + "…" + t[-6:] if len(t) > 24 else t


def scan(root: str):
    jwts = {}          # token -> info
    headers = {}       # key -> value (best-effort)
    files_scanned = 0
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if fn.lower().endswith(SCAN_EXT_SKIP):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(fp) > MAX_FILE:
                    continue
                with open(fp, "rb") as f:
                    data = f.read()
            except Exception:
                continue
            files_scanned += 1
            for m in JWT_RE.findall(data):
                tok = m.decode("ascii", "ignore")
                if tok in jwts:
                    continue
                info = classify(tok)
                if info:
                    info["file"] = fp
                    jwts[tok] = info
            # 헤더 후보 (텍스트 파일만)
            try:
                txt = data.decode("utf-8", "ignore")
            except Exception:
                txt = ""
            for hm in HDR_RE.finditer(txt):
                k = hm.group(1).lower().replace("-", "_")
                headers.setdefault(k, hm.group(2))
    return jwts, headers, files_scanned


def build_accounts(jwts: dict, headers: dict) -> list:
    # 계정(sub)별로 최신(exp 큰) refresh + access 선택
    by_sub = {}
    for info in jwts.values():
        if info["kind"] not in ("refresh", "access"):
            continue
        s = by_sub.setdefault(info["sub"], {"refresh": None, "access": None})
        cur = s[info["kind"]]
        if cur is None or (info["exp"] or 0) > (cur["exp"] or 0):
            s[info["kind"]] = info
    out = []
    for sub, toks in by_sub.items():
        r = toks["refresh"]
        a = toks["access"]
        if not r:
            continue                    # refresh 없으면 무인 갱신 불가 → 스킵
        out.append({
            "code": sub,
            "refresh": r["token"],
            "access": a["token"] if a else "",
            "proxy": None,
            "label": f"acc-{sub[:6]}",
            "_refresh_ttl": r["ttl"],
            "_client": r.get("client"),
        })
    return out, headers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="스캔할 디렉토리(백업/에뮬마운트/prefs)")
    ap.add_argument("--out", default="data/accounts.json")
    ap.add_argument("--headers-out", default="data/config.json")
    args = ap.parse_args()

    if not os.path.isdir(args.root):
        print(f"디렉토리 아님: {args.root}")
        sys.exit(1)

    print(f"스캔: {args.root}")
    jwts, headers, n = scan(args.root)
    print(f"파일 {n}개 스캔 · JWT {len(jwts)}개 발견")

    if not jwts:
        print("\n❌ JWT 0건. 가능성:")
        print("  - 토큰이 EncryptedSharedPreferences(Keystore)로 암호화 저장됨 → 백업에서 못 읽음")
        print("    → 에뮬 런타임에서 추출 필요(Frida, 또는 앱 실행 중 메모리/트래픽)")
        print("  - 스캔 경로가 앱 데이터가 아님 → /data/data/com.towneers.www 하위를 지정")
        sys.exit(2)

    kinds = {}
    for i in jwts.values():
        kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
    print(f"  종류: {kinds}")
    accounts, hdrs = build_accounts(jwts, headers)

    print(f"\n계정(refresh 보유) {len(accounts)}개:")
    for a in accounts:
        alive = ""
        print(f"  {a['label']:14s} refresh={mask(a['refresh'])} "
              f"ttl={a['_refresh_ttl']}s client={a['_client']}")

    if accounts:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        # 내부 필드 제거하고 저장
        clean = [{k: v for k, v in a.items() if not k.startswith("_")} for a in accounts]
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        os.chmod(args.out, 0o600)
        print(f"\n저장: {args.out} (0600, {len(clean)}계정)")

    if hdrs:
        print(f"\n디바이스 헤더 후보 {len(hdrs)}개: {sorted(hdrs)}")
        print("  (accounts 별 헤더가 다르면 계정별로 분리 필요 — config.json 은 참고용)")


if __name__ == "__main__":
    main()

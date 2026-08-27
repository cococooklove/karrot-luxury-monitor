"""extract_tokens 자체 테스트 (합성 데이터, 네트워크 없음)."""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_tokens import parse_token_ds


def field(num, val):
    tag = (num << 3) | 2
    b = val.encode()
    return bytes([tag, len(b)]) + b


def mkjwt(sub, ttl, typ):
    now = int(time.time())
    h = base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode().rstrip("=")
    p = {"iat": now, "exp": now + ttl, "sub": sub, "type": typ, "client_name": "KARROT_APP"}
    pb = base64.urlsafe_b64encode(json.dumps(p).encode()).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(b"x" * 32).decode().rstrip("=")
    return f"{h}.{pb}.{sig}"


def main():
    # 1) proto 파서 단위
    data = field(1, "RVAL") + field(2, "AVAL") + field(3, "AUTH")
    r = parse_token_ds(data)
    assert r == {"refresh": "RVAL", "access": "AVAL", "auth": "AUTH"}, r
    print("[PASS] proto 파서 필드 매핑")

    # 2) 통합: 계정 2개 백업 디렉토리
    d = tempfile.mkdtemp()
    for acc in ("acc1", "acc2"):
        ddir = f"{d}/{acc}/data/com.towneers.www/files/datastore"
        os.makedirs(ddir)
        blob = field(1, mkjwt(acc, 21600, "refresh")) + field(2, mkjwt(acc, 1800, "access"))
        with open(f"{ddir}/karrot_token.ds", "wb") as f:
            f.write(blob)
    here = os.path.dirname(os.path.abspath(__file__))
    py = sys.executable
    out = subprocess.run([py, os.path.join(here, "extract_tokens.py"), d,
                          "--out", d + "/accounts.json"],
                         capture_output=True, text=True)
    print(out.stdout.strip())
    assert out.returncode == 0, out.stderr
    accs = json.load(open(d + "/accounts.json"))
    assert len(accs) == 2, accs
    assert all(a["refresh"] and a["access"] for a in accs), accs
    assert oct(os.stat(d + "/accounts.json").st_mode & 0o777) == "0o600"
    print("[PASS] 통합 추출(karrot_token.ds 2계정 → accounts.json 0600)")

    # 3) 불투명(비-JWT) refresh 도 proto 로 잡히는지
    d2 = tempfile.mkdtemp()
    ddir = f"{d2}/data/com.towneers.www/files/datastore"
    os.makedirs(ddir)
    with open(f"{ddir}/karrot_token.ds", "wb") as f:
        f.write(field(1, "opaque-refresh-abc123") + field(2, mkjwt("u", 1800, "access")))
    out2 = subprocess.run([py, os.path.join(here, "extract_tokens.py"), d2,
                           "--out", d2 + "/accounts.json"],
                          capture_output=True, text=True)
    accs2 = json.load(open(d2 + "/accounts.json"))
    assert accs2 and accs2[0]["refresh"] == "opaque-refresh-abc123", accs2
    print("[PASS] 불투명 refresh 토큰도 proto 로 추출")

    print("\n3/3 PASS")


if __name__ == "__main__":
    main()

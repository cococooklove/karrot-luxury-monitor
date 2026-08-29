#!/usr/bin/env python3
"""세션 이식 (SMS 없이 로그인): accounts.json 의 refresh 토큰으로 karrot_token.ds 를
구성해 LDPlayer 인스턴스의 당근 앱 데이터에 심는다. 앱 실행 시 refresh 로 access 갱신 → 로그인.

서버(LDPlayer)서 실행:
  python tools/server_transplant.py --code 452902230637059559 --serial 127.0.0.1:5555
"""
import argparse
import base64
import glob
import json
import subprocess
import sys
import time

PKG = "com.towneers.www"
DS = f"/data/data/{PKG}/files/datastore/karrot_token.ds"


def _varint(n):
    out = b""
    while True:
        x = n & 0x7F
        n >>= 7
        out += bytes([x | 0x80]) if n else bytes([x])
        if not n:
            return out


def build_token_ds(refresh, access="", auth=""):
    """proto: field1=refresh, 2=access, 3=auth (wire type 2, string)."""
    def field(num, s):
        if not s:
            return b""
        b = s.encode("utf-8")
        return bytes([(num << 3) | 2]) + _varint(len(b)) + b
    return field(1, refresh) + field(2, access) + field(3, auth)


def find_adb():
    for pat in (r"C:\LDPlayer\*\adb.exe", r"D:\LDPlayer\*\adb.exe",
                r"C:\Program Files*\LDPlayer\*\adb.exe"):
        for p in glob.glob(pat):
            return p
    return "adb"


def sh(adb, serial, *args):
    return subprocess.run([adb, "-s", serial, *args], capture_output=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--serial", default="127.0.0.1:5555")
    ap.add_argument("--accounts", default="./accounts.json")
    ap.add_argument("--no-launch", action="store_true")
    a = ap.parse_args()

    accts = json.load(open(a.accounts, encoding="utf-8"))
    acct = next((x for x in accts if str(x.get("code")) == a.code), None)
    if not acct:
        sys.exit(f"[이식] 계정 {a.code} accounts.json 에 없음")
    ds = build_token_ds(acct.get("refresh", ""), acct.get("access", ""), acct.get("auth", ""))
    b64 = base64.b64encode(ds).decode()

    adb = find_adb()
    print(f"[이식] adb={adb} serial={a.serial} code={a.code} ds={len(ds)}B")
    subprocess.run([adb, "connect", a.serial], capture_output=True)

    # 루트 확인
    r = sh(adb, a.serial, "shell", "su", "-c", "id")
    if b"uid=0" not in r.stdout:
        sys.exit(f"[이식] su 루트 불가: {r.stdout.decode()[:80]} {r.stderr.decode()[:80]}")

    uid = sh(adb, a.serial, "shell", "su", "-c", f"stat -c %u /data/data/{PKG}").stdout.decode().strip()
    print(f"[이식] app uid={uid}")

    sh(adb, a.serial, "shell", "su", "-c", f"am force-stop {PKG}")
    time.sleep(1)
    cmd = (f"mkdir -p /data/data/{PKG}/files/datastore && "
           f"echo {b64} | base64 -d > {DS} && "
           f"chown {uid}:{uid} {DS} && chmod 600 {DS} && "
           f"ls -l {DS}")
    r = sh(adb, a.serial, "shell", "su", "-c", cmd)
    print("[이식] push:", r.stdout.decode().strip()[:120], r.stderr.decode().strip()[:120])

    if not a.no_launch:
        sh(adb, a.serial, "shell", "monkey", "-p", PKG, "-c",
           "android.intent.category.LAUNCHER", "1")
        print("[이식] 앱 실행됨 — 20~30초 후 harvest 로 access 갱신 확인")


if __name__ == "__main__":
    main()

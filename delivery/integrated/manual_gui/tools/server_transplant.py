#!/usr/bin/env python3
"""세션 이식 (SMS 없이 로그인): accounts.json 의 refresh 토큰으로 karrot_token.ds 를
구성해 LDPlayer 인스턴스 당근 앱에 심는다. 앱 실행 시 refresh 로 access 갱신 → 로그인.

이 LDPlayer su 는 'su -c' 따옴표가 안 먹어 'su 0 <cmd>' 형식 사용.
파일 주입은 adb push(/sdcard) → su 0 cp 로 (파이프/리다이렉트 회피).

서버(LDPlayer)서:
  python tools/server_transplant.py --code 452902230637059559 --serial 127.0.0.1:5555
"""
import argparse
import base64
import glob
import json
import os
import subprocess
import sys
import tempfile
import time

PKG = "com.towneers.www"
DS_DIR = f"/data/data/{PKG}/files/datastore"
DS = f"{DS_DIR}/karrot_token.ds"


def _varint(n):
    out = b""
    while True:
        x = n & 0x7F
        n >>= 7
        out += bytes([x | 0x80]) if n else bytes([x])
        if not n:
            return out


def build_token_ds(refresh, access="", auth=""):
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


def run(*args):
    return subprocess.run(list(args), capture_output=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--serial", default="127.0.0.1:5555")
    ap.add_argument("--accounts", default="./accounts.json")
    ap.add_argument("--no-launch", action="store_true")
    a = ap.parse_args()
    adb, S = find_adb(), a.serial

    def su(*cmd):   # su 0 <cmd> (따옴표 이슈 없는 형식)
        return run(adb, "-s", S, "shell", "su", "0", *cmd)

    accts = json.load(open(a.accounts, encoding="utf-8"))
    acct = next((x for x in accts if str(x.get("code")) == a.code), None)
    if not acct:
        sys.exit(f"[이식] 계정 {a.code} accounts.json 에 없음")
    ds = build_token_ds(acct.get("refresh", ""), acct.get("access", ""), acct.get("auth", ""))
    print(f"[이식] adb={adb} serial={S} code={a.code} ds={len(ds)}B")
    run(adb, "connect", S)

    if b"uid=0" not in su("id").stdout:
        sys.exit(f"[이식] su 0 루트 불가 (LDPlayer Root 권한 확인)")

    uid = su("stat", "-c", "%u", f"/data/data/{PKG}").stdout.decode().strip()
    if not uid.isdigit():
        sys.exit(f"[이식] uid 감지 실패: {uid!r} (당근 앱 최초 1회 실행 필요)")
    print(f"[이식] app uid={uid}")

    su("am", "force-stop", PKG)
    time.sleep(1)
    su("mkdir", "-p", DS_DIR)

    # 로컬 임시파일 → adb push → su 0 cp (파이프/리다이렉트 회피)
    tf = tempfile.NamedTemporaryFile(delete=False, suffix=".ds")
    tf.write(ds); tf.close()
    run(adb, "-s", S, "push", tf.name, "/sdcard/karrot_token.ds")
    os.unlink(tf.name)
    su("cp", "/sdcard/karrot_token.ds", DS)
    su("chown", f"{uid}:{uid}", DS)
    su("chmod", "600", DS)
    su("rm", "/sdcard/karrot_token.ds")
    ls = su("ls", "-l", DS).stdout.decode().strip()
    print(f"[이식] push 완료: {ls}")

    if not a.no_launch:
        run(adb, "-s", S, "shell", "monkey", "-p", PKG, "-c",
            "android.intent.category.LAUNCHER", "1")
        print("[이식] 앱 실행됨 — 20~30초 후 harvest 로 access 갱신 확인")


if __name__ == "__main__":
    main()

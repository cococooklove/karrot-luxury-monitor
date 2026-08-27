#!/usr/bin/env python3
"""LDPlayer 멀티인스턴스 토큰 수확기 (Windows/클라용, 폰 불필요).

LDPlayer 는 기본 루팅 → su 로 각 인스턴스의 karrot_token.ds 를 직접 읽는다.
인스턴스마다 계정 1개 = 진짜 병렬. 회전토큰을 accounts.json 에 병합(덮어쓰기 X).

앱이 스스로 refresh(WAF 통과) → 이 스크립트는 결과만 수확. Mac 직접갱신(WAF 403) 대체.

사용(Windows):
  python tools/ld_harvest.py ^
    --adb "C:\\LDPlayer\\LDPlayer9\\adb.exe" ^
    --serials 127.0.0.1:5555 127.0.0.1:5557 127.0.0.1:5559 ^
    --interval 1500            # 25분(access 30분 만료 전)
  # 1회만: --once     앱갱신 유발 끄기: --no-nudge

포트: LDPlayer 다중실행 시 인스턴스별 adb 포트(5555, 5557, 5559 … 보통 +2).
      'LDPlayer > 설정' 또는 `adb devices` 로 확인. --auto 로 adb devices 자동수집.
"""
import argparse, base64, json, os, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_tokens import parse_token_ds, jwt_payload  # noqa

PKG = "com.towneers.www"
APP_DATA = f"/data/data/{PKG}"
TOKEN_REL = "files/datastore/karrot_token.ds"


def adb(adb_bin, serial, *args, binary=False, timeout=30):
    cmd = [adb_bin]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"adb {' '.join(args[:2])}: {p.stderr.decode('utf-8','ignore')[:150]}")
    return p.stdout if binary else p.stdout.decode("utf-8", "ignore")


def sub_read(adb_bin, serial, path):
    """su 로 파일을 base64 로 읽어 bytes 반환(바이너리 안전)."""
    # 경로 화이트리스트(인젝션 방지)
    if any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/_.-" for c in path):
        raise ValueError(f"경로 위험문자: {path}")
    out = adb(adb_bin, serial, "exec-out", "su", "-c", f"base64 {path}")
    return base64.b64decode(out.strip())


def find_token(adb_bin, serial):
    out = adb(adb_bin, serial, "exec-out", "su", "-c",
              f"find {APP_DATA} -name karrot_token.ds 2>/dev/null")
    for line in out.replace("\r", "").splitlines():
        line = line.strip()
        if line.startswith(APP_DATA + "/") and all(
                c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/_.-" for c in line):
            return line
    return f"{APP_DATA}/{TOKEN_REL}"


def nudge(adb_bin, serial):
    try:
        adb(adb_bin, serial, "shell", "monkey", "-p", PKG,
            "-c", "android.intent.category.LAUNCHER", "1", timeout=20)
        time.sleep(6)
    except Exception:
        pass


def jwt_field(tok, key):
    try:
        return (jwt_payload(tok) or {}).get(key)
    except Exception:
        return None


def harvest_one(adb_bin, serial, do_nudge):
    try:
        adb(adb_bin, None, "connect", serial, timeout=15)
    except Exception:
        pass
    if do_nudge:
        nudge(adb_bin, serial)
    path = find_token(adb_bin, serial)
    raw = sub_read(adb_bin, serial, path)
    d = parse_token_ds(raw)
    refresh, access = d.get("refresh", ""), d.get("access", "")
    if not refresh:
        return None
    code = jwt_field(refresh, "sub") or jwt_field(access, "sub") or serial
    aexp = jwt_field(access, "exp") if access else 0
    rem = int(aexp - time.time()) if aexp else 0
    return {"code": str(code), "refresh": refresh, "access": access,
            "_access_rem": rem, "serial": serial}


def merge(accounts_fp, rows):
    base = json.load(open(accounts_fp, encoding="utf-8")) if os.path.exists(accounts_fp) else []
    by = {a.get("code"): a for a in base}
    upd = ins = 0
    for r in rows:
        c = r["code"]
        if c in by:
            a = by[c]
            if r["refresh"] != a.get("refresh") or r["access"] != a.get("access"):
                a["refresh"] = r["refresh"]; a["access"] = r["access"]; upd += 1
        else:
            base.append({"code": c, "refresh": r["refresh"], "access": r["access"],
                         "proxy": None, "label": f"acc-{c[:6]}"})
            ins += 1
    tmp = accounts_fp + ".tmp"
    json.dump(base, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, accounts_fp)
    try: os.chmod(accounts_fp, 0o600)
    except Exception: pass
    return upd, ins, len(base)


def cycle(adb_bin, serials, accounts_fp, do_nudge):
    rows = []
    for s in serials:
        try:
            r = harvest_one(adb_bin, s, do_nudge)
            if r:
                rows.append(r)
                print(f"  {s}  {r['code']}  access {r['_access_rem']//60}m 남음")
            else:
                print(f"  {s}  refresh 없음(로그인 확인)")
        except Exception as e:
            print(f"  {s}  실패: {str(e)[:120]}")
    if rows:
        u, i, t = merge(accounts_fp, rows)
        print(f"  병합: 갱신 {u} · 신규 {i} · 총 {t}계정")
    else:
        print("  수확 0")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adb", default="adb", help="adb 실행경로(Windows: LDPlayer adb.exe)")
    ap.add_argument("--serials", nargs="*", default=[], help="LD 인스턴스 adb 주소들 (127.0.0.1:5555 …)")
    ap.add_argument("--auto", action="store_true", help="adb devices 로 자동수집")
    ap.add_argument("--accounts", default="data/accounts.json")
    ap.add_argument("--interval", type=int, default=1500)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--no-nudge", action="store_true")
    a = ap.parse_args()

    serials = list(a.serials)
    if a.auto or not serials:
        out = adb(a.adb, None, "devices")
        for line in out.splitlines()[1:]:
            if "\tdevice" in line:
                serials.append(line.split("\t")[0])
    if not serials:
        sys.exit("인스턴스 없음. --serials 로 LD 포트 지정 또는 LDPlayer 켜고 --auto.")
    print(f"대상 {len(serials)}인스턴스: {', '.join(serials)}")

    if a.once:
        cycle(a.adb, serials, a.accounts, not a.no_nudge)
        return
    while True:
        print(f"── {time.strftime('%H:%M:%S')} 수확 ──")
        cycle(a.adb, serials, a.accounts, not a.no_nudge)
        time.sleep(a.interval)


if __name__ == "__main__":
    main()

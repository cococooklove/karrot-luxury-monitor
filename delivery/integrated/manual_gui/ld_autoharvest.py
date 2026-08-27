"""LDPlayer 온디바이스 토큰 자동수확 (GUI 번들).

기존 _refresh_tokens 의 HTTP refresh(WAF 403)를 대체한다:
LDPlayer(기본 루팅)의 정품 당근앱이 스스로 갱신한 access 를 su 로 직접 읽어
accounts.json 에 병합. 앱이 WAF·피닝을 처리하므로 PC 직접 refresh 불필요.

- 각 인스턴스 앱을 nudge(실행)해 만료임박 access 갱신 유발 → karrot_token.ds 읽기.
- accounts.json 스키마: [{code, refresh, access, proxy, label}] — AccountStore/freshest 호환.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import time

PKG = "com.towneers.www"
APP_DATA = f"/data/data/{PKG}"
_SAFE = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/_.-"

LD_ADB_PATHS = [
    r"C:\LDPlayer\LDPlayer9\adb.exe",
    r"C:\LDPlayer\LDPlayer4.0\adb.exe",
    r"C:\Program Files\LDPlayer\LDPlayer9\adb.exe",
    r"D:\LDPlayer\LDPlayer9\adb.exe",
]


# ── karrot_token.ds proto 파싱 (field1=refresh, 2=access, 3=auth; wire2 string) ──
def _read_varint(buf, i):
    shift = val = 0
    while i < len(buf):
        b = buf[i]; val |= (b & 0x7F) << shift; i += 1
        if not (b & 0x80):
            return val, i
        shift += 7
    return val, i


def parse_token_ds(data: bytes) -> dict:
    out = {}
    i, n = 0, len(data)
    field_name = {1: "refresh", 2: "access", 3: "auth"}
    while i < n:
        tag, i = _read_varint(data, i)
        field, wt = tag >> 3, tag & 7
        if wt == 2:
            ln, i = _read_varint(data, i)
            chunk = data[i:i + ln]; i += ln
            nm = field_name.get(field)
            if nm:
                try:
                    out[nm] = chunk.decode("utf-8")
                except Exception:
                    pass
        elif wt == 0:
            _, i = _read_varint(data, i)
        elif wt == 5:
            i += 4
        elif wt == 1:
            i += 8
        else:
            break
    return out


def _jwt_sub(tok: str):
    try:
        p = tok.split(".")[1]; p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p)).get("sub")
    except Exception:
        return None


def find_adb(explicit=None):
    if explicit and os.path.exists(explicit):
        return explicit
    for p in LD_ADB_PATHS:
        if os.path.exists(p):
            return p
    return "adb"     # PATH


def _adb(adb_bin, serial, *args, timeout=30):
    cmd = [adb_bin] + (["-s", serial] if serial else []) + list(args)
    p = subprocess.run(cmd, capture_output=True, timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode("utf-8", "ignore")[:150])
    return p.stdout.decode("utf-8", "ignore")


def list_instances(adb_bin):
    try:
        out = _adb(adb_bin, None, "devices")
        return [l.split("\t")[0] for l in out.splitlines()[1:] if "\tdevice" in l]
    except Exception:
        return []


def _find_token_path(adb_bin, serial):
    try:
        out = _adb(adb_bin, serial, "exec-out", "su", "-c",
                   f"find {APP_DATA} -name karrot_token.ds 2>/dev/null")
        for line in out.replace("\r", "").splitlines():
            line = line.strip()
            if line.startswith(APP_DATA + "/") and all(c in _SAFE for c in line):
                return line
    except Exception:
        pass
    return f"{APP_DATA}/files/datastore/karrot_token.ds"


def harvest_one(adb_bin, serial, nudge=True):
    if nudge:
        try:
            _adb(adb_bin, serial, "shell", "monkey", "-p", PKG,
                 "-c", "android.intent.category.LAUNCHER", "1", timeout=20)
            time.sleep(6)
        except Exception:
            pass
    path = _find_token_path(adb_bin, serial)
    if any(c not in _SAFE for c in path):
        return None
    raw = base64.b64decode(_adb(adb_bin, serial, "exec-out", "su", "-c", f"base64 {path}").strip())
    d = parse_token_ds(raw)
    refresh, access = d.get("refresh", ""), d.get("access", "")
    if not (refresh or access):
        return None
    code = _jwt_sub(refresh) or _jwt_sub(access) or serial
    return {"code": str(code), "refresh": refresh, "access": access}


def merge_accounts(accounts_fp, rows):
    base = json.load(open(accounts_fp, encoding="utf-8")) if os.path.exists(accounts_fp) else []
    by = {a.get("code"): a for a in base}
    upd = ins = 0
    for r in rows:
        c = r["code"]
        if c in by:
            a = by[c]
            if r["refresh"] != a.get("refresh") or r["access"] != a.get("access"):
                if r["refresh"]:
                    a["refresh"] = r["refresh"]
                a["access"] = r["access"]; upd += 1
        else:
            base.append({"code": c, "refresh": r["refresh"], "access": r["access"],
                         "proxy": None, "label": f"acc-{str(c)[:6]}"})
            ins += 1
    tmp = accounts_fp + ".tmp"
    json.dump(base, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, accounts_fp)
    return upd, ins, len(base)


def harvest_all(accounts_fp="./accounts.json", adb_bin=None, serials=None,
                nudge=True, log=None):
    """모든 LDPlayer 인스턴스 수확 → accounts.json 병합. (updated, inserted, total, harvested)."""
    log = log or (lambda m: None)
    adb_bin = find_adb(adb_bin)
    use = list(serials or []) or list_instances(adb_bin)
    if not use:
        log("[수확] LDPlayer 인스턴스 없음 — LDPlayer 켜졌는지 확인")
        return (0, 0, 0, 0)
    rows = []
    for s in use:
        try:
            r = harvest_one(adb_bin, s, nudge=nudge)
            if r:
                rows.append(r)
                log(f"[수확] {s} · {r['code']}")
        except Exception as e:
            log(f"[수확] {s} 실패: {str(e)[:80]}")
    if not rows:
        return (0, 0, 0, 0)
    u, i, t = merge_accounts(accounts_fp, rows)
    log(f"[수확] 갱신 {u} · 신규 {i} · 총 {t}계정")
    return (u, i, t, len(rows))

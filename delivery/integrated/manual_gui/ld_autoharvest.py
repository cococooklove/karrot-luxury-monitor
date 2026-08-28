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

import glob as _glob
# LDPlayer 설치 폴더 후보(버전 무관 glob 포함). adb.exe/ldconsole.exe 가 여기 있음.
_LD_DIRS = []
for _root in (r"C:\LDPlayer", r"D:\LDPlayer", r"C:\Program Files\LDPlayer",
              r"C:\Program Files (x86)\LDPlayer"):
    for _v in ("LDPlayer14", "LDPlayer9", "LDPlayer4.0", "LDPlayer64", ""):
        _LD_DIRS.append(_root + ("\\" + _v if _v else ""))
    try:
        _LD_DIRS += _glob.glob(_root + r"\LDPlayer*")   # 설치된 실제 버전 폴더 자동수집
    except Exception:
        pass
# 중복 제거(순서 유지)
_seen = set(); _LD_DIRS = [d for d in _LD_DIRS if not (d in _seen or _seen.add(d))]

LD_ADB_PATHS = [d + r"\adb.exe" for d in _LD_DIRS]
LD_CONSOLE_NAMES = ["ldconsole.exe", "dnconsole.exe"]
LD_CONSOLE_PATHS = list(_LD_DIRS)


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


# ── LDPlayer 자동 부팅 (클라가 LDPlayer 안 켜도 되게) ──
def find_ldconsole(adb_bin=None):
    import os.path
    cands = []
    if adb_bin and os.path.exists(adb_bin):
        d = os.path.dirname(adb_bin)
        cands += [os.path.join(d, n) for n in LD_CONSOLE_NAMES]
    for base in LD_CONSOLE_PATHS:
        cands += [os.path.join(base, n) for n in LD_CONSOLE_NAMES]
    for c in cands:
        if os.path.exists(c):
            return c
    return None


def ld_list(console):
    """ldconsole list2 → [(index, name, is_running)]."""
    try:
        p = subprocess.run([console, "list2"], capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        rows = []
        for line in p.stdout.decode("utf-8", "ignore").splitlines():
            f = line.split(",")
            if len(f) >= 2 and f[0].strip().lstrip("-").isdigit():
                # list2: index,name,top_hwnd,bind_hwnd,android_started(0/1),pid,...
                running = len(f) >= 5 and f[4].strip() not in ("0", "", "-1")
                rows.append((f[0].strip(), f[1].strip(), running))
        return rows
    except Exception:
        return []


def ld_launch(console, index):
    try:
        subprocess.run([console, "launch", "--index", str(index)], timeout=30,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception:
        return False


def ensure_ldplayer(adb_bin, boot_wait=120, log=None):
    """adb 에 기기가 없으면 LDPlayer 인스턴스를 부팅해 올라올 때까지 대기.
    반환: 사용가능 serial 리스트."""
    log = log or (lambda m: None)
    cur = list_instances(adb_bin)
    if cur:
        return cur
    console = find_ldconsole(adb_bin)
    if not console:
        log("[LDPlayer] ldconsole.exe 못찾음 — LDPlayer 설치경로 확인")
        return []
    insts = ld_list(console)
    if not insts:
        log("[LDPlayer] 인스턴스 없음 — .ldbk 복원 필요")
        return []
    to_boot = [i for i in insts if not i[2]]
    if to_boot:
        log(f"[LDPlayer] {len(to_boot)}개 인스턴스 부팅…")
        for idx, name, _ in to_boot:
            ld_launch(console, idx)
    # adb 기기 올라올 때까지 폴링
    waited = 0
    while waited < boot_wait:
        time.sleep(5); waited += 5
        cur = list_instances(adb_bin)
        if len(cur) >= len(insts):
            log(f"[LDPlayer] {len(cur)}개 기동 완료 ({waited}s)")
            return cur
    cur = list_instances(adb_bin)
    log(f"[LDPlayer] {len(cur)}/{len(insts)}개 기동 (대기 {boot_wait}s 초과)")
    return cur


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


def _su_ok(adb_bin, serial):
    """루트(su) 사용가능?"""
    try:
        out = _adb(adb_bin, serial, "shell", "su", "-c", "id")
        return "uid=0" in out
    except Exception:
        return False


def _read_ds_b64(adb_bin, serial):
    """karrot_token.ds 를 base64 로 반환. 루트면 su, 아니면 run-as(디버그앱).
    반환 (b64str, mode) 또는 (None, None)."""
    rel = "files/datastore/karrot_token.ds"
    absp = f"{APP_DATA}/{rel}"
    # 1) su (LDPlayer 등 루팅)
    if _su_ok(adb_bin, serial):
        try:
            return _adb(adb_bin, serial, "exec-out", "su", "-c", f"base64 {absp}").strip(), "su"
        except Exception:
            pass
    # 2) run-as (디버그 재패키징 앱 — 폰 개발용, 비루팅)
    try:
        b = _adb(adb_bin, serial, "exec-out", "run-as", PKG, "base64", rel).strip()
        if b:
            return b, "run-as"
    except Exception:
        pass
    return None, None



def harvest_one(adb_bin, serial, nudge=True):
    if nudge:
        try:
            _adb(adb_bin, serial, "shell", "monkey", "-p", PKG,
                 "-c", "android.intent.category.LAUNCHER", "1", timeout=20)
            time.sleep(6)
        except Exception:
            pass
    b64, _mode = _read_ds_b64(adb_bin, serial)
    if not b64:
        return None
    try:
        raw = base64.b64decode(b64)
    except Exception:
        return None
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
        # LDPlayer 자동 부팅(클라가 안 켜도 됨) 후 재시도
        use = ensure_ldplayer(adb_bin, log=log)
    if not use:
        log("[수확] LDPlayer 인스턴스 없음 — 설치/.ldbk 복원 확인")
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

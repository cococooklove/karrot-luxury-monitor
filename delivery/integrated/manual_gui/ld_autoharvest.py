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
import tempfile
import threading
import time

# accounts.json 은 이 기계에서 재발급할 수 없는 세션 토큰의 유일한 사본이다.
# 두 스레드(GUI 스윕 스레드 + 알림 워커, 헤드리스 폴링 루프 + 스윕)가 같은 프로세스
# 안에서 동시에 들어올 수 있으므로 읽기-병합-쓰기 전체를 직렬화한다.
_MERGE_LOCK = threading.Lock()
# 함대 전체 수확도 프로세스 안에서 하나만 돈다. 동시 수확은 adb 폭주이면서
# LDPlayer 인스턴스 동시기동 금지 규칙(순차 기동)을 어긴다.
_HARVEST_LOCK = threading.Lock()

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
    """연결된 기기 목록. LDPlayer 는 인스턴스마다 emulator-P 와 127.0.0.1:(P+1) 를
    둘 다 노출할 수 있어(수동 connect 시) 같은 인스턴스가 중복 → 병렬 수확서 서로
    간섭(force-stop 충돌). emulator-* 를 정본으로 두고 중복 127.0.0.1 은 제거."""
    try:
        out = _adb(adb_bin, None, "devices")
        devs = [l.split("\t")[0] for l in out.splitlines()[1:] if "\tdevice" in l]
    except Exception:
        return []
    emu_ports = set()
    for d in devs:
        if d.startswith("emulator-"):
            try: emu_ports.add(int(d.split("-")[1]))
            except Exception: pass
    result = []
    for d in devs:
        if d.startswith("127.0.0.1:"):
            try:
                # 127.0.0.1:(P+1) 는 emulator-P 와 동일 인스턴스 → emulator 있으면 skip
                if (int(d.split(":")[1]) - 1) in emu_ports:
                    continue
            except Exception:
                pass
        result.append(d)
    return result


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


def ld_quit(console, index):
    try:
        subprocess.run([console, "quit", "--index", str(index)], timeout=30,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception:
        return False


def ensure_ldplayer(adb_bin, boot_wait=180, log=None, gap=35, retry=1):
    """adb 에 기기가 없으면 LDPlayer 인스턴스를 부팅해 올라올 때까지 대기.

    동시 기동은 VM start 전 hang 을 유발(무인 재부팅 복구 실패의 원인) → **순차 기동**.
    인스턴스마다 launch → adb 기기 수 증가 확인(최대 boot_wait) → 실패시 quit 후 재시도.
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
    log(f"[LDPlayer] {len(insts)}개 인스턴스 순차 부팅(간격 {gap}s)…")
    for idx, name, running in insts:
        before = len(list_instances(adb_bin))
        for attempt in range(retry + 1):
            if attempt:
                log(f"[LDPlayer] {name}(idx {idx}) 부팅 실패 → 재기동 {attempt}/{retry}")
                ld_quit(console, idx)
                time.sleep(8)
            ld_launch(console, idx)
            waited = 0
            while waited < boot_wait:
                time.sleep(5); waited += 5
                if len(list_instances(adb_bin)) > before:
                    log(f"[LDPlayer] {name}(idx {idx}) 기동 완료 ({waited}s)")
                    break
            else:
                continue
            break
        else:
            log(f"[LDPlayer] {name}(idx {idx}) 기동 실패 — 건너뜀")
        time.sleep(gap)
    cur = list_instances(adb_bin)
    log(f"[LDPlayer] {len(cur)}/{len(insts)}개 기동")
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



def _access_remaining(access):
    """access JWT 남은 초. 파싱 실패 -1."""
    try:
        p = access.split(".")[1]; p += "=" * (-len(p) % 4)
        return int(json.loads(base64.urlsafe_b64decode(p)).get("exp", 0) - time.time())
    except Exception:
        return -1


def _read_parse(adb_bin, serial):
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


def harvest_one(adb_bin, serial, nudge=True, min_remaining=600):
    """토큰 수확. 먼저 읽어(무-nudge) 아직 min_remaining 초 넘게 살아있으면 그대로 반환.
    만료임박/없음일 때만 nudge(앱 강제실행)해 앱이 갱신하도록 유도 → 재읽기.
    → 100계정 팜서 불필요한 앱실행 최소화(배터리·부하·방해 감소)."""
    cur = _read_parse(adb_bin, serial)
    if cur and _access_remaining(cur.get("access", "")) > min_remaining:
        return cur                       # 아직 신선 → nudge 불필요
    if nudge:
        # 이미 포그라운드인 앱에 launch 는 no-op → 콜드스타트(force-stop→launch)로
        # 앱이 refresh 하게 강제. 실측 10초 내 갱신, 최대 24초 대기.
        try:
            _adb(adb_bin, serial, "shell", "am", "force-stop", PKG, timeout=20)
            time.sleep(1)
            _adb(adb_bin, serial, "shell", "monkey", "-p", PKG,
                 "-c", "android.intent.category.LAUNCHER", "1", timeout=20)
        except Exception:
            pass
        for _ in range(8):
            time.sleep(3)
            fresh = _read_parse(adb_bin, serial)
            if fresh and _access_remaining(fresh.get("access", "")) > min_remaining:
                return fresh
        fresh = _read_parse(adb_bin, serial)
        if fresh:
            return fresh
    return cur


def merge_accounts(accounts_fp, rows):
    """수확분을 accounts.json 에 병합. 동시 호출에도 파일이 깨지지 않는다.

    읽기-병합-쓰기를 _MERGE_LOCK 으로 감싸고(안 그러면 나중 쓰기가 앞선 쓰기의
    삽입을 통째로 덮는다), 승격은 같은 디렉터리의 **고유** 임시파일에서 한다.
    고정 이름(accounts.json.tmp)을 쓰면 두 쓰기가 한 파일에 뒤섞인 뒤 그 잡탕이
    os.replace 로 원자적으로 승격된다 — replace 는 원자적이어도 내용은 아니다."""
    with _MERGE_LOCK:
        return _merge_accounts_locked(accounts_fp, rows)


def _merge_accounts_locked(accounts_fp, rows):
    base = json.load(open(accounts_fp, encoding="utf-8")) if os.path.exists(accounts_fp) else []
    # code 중복 제거(후행 항목 우선 — 최근 수확분)
    by = {}
    for a in base:
        by[a.get("code")] = a
    base = list(by.values())
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
    _atomic_write_json(accounts_fp, base)
    return upd, ins, len(base)


def _atomic_write_json(fp, data):
    """같은 디렉터리의 고유 임시파일 → fsync → os.replace. 같은 파일시스템 유지."""
    d = os.path.dirname(os.path.abspath(fp)) or "."
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(fp) + ".", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, fp)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def harvest_all(accounts_fp="./accounts.json", adb_bin=None, serials=None,
                nudge=True, log=None):
    """모든 LDPlayer 인스턴스 수확 → accounts.json 병합. (updated, inserted, total, harvested).

    프로세스 안에서 한 번에 하나만 돈다. 두 스레드가 동시에 들어오면 뒤쪽은
    앞쪽이 끝날 때까지 기다렸다가 갱신된 파일 위에서 다시 병합한다 — 함대를 두 번
    깨우지 않고, ensure_ldplayer 가 인스턴스를 동시 기동하지도 않는다.

    주의: 이 락은 프로세스 안에서만 유효하다. GUI 와 헤드리스를 같은 기계에서
    동시에 띄우면 두 프로세스가 각각 수확하며, 그건 파일락으로만 막힌다."""
    with _HARVEST_LOCK:
        return _harvest_all_locked(accounts_fp, adb_bin, serials, nudge, log)


def _harvest_all_locked(accounts_fp, adb_bin, serials, nudge, log):
    log = log or (lambda m: None)
    adb_bin = find_adb(adb_bin)
    use = list(serials or []) or list_instances(adb_bin)
    if not use:
        # LDPlayer 자동 부팅(클라가 안 켜도 됨) 후 재시도
        use = ensure_ldplayer(adb_bin, log=log)
    if not use:
        log("[수확] LDPlayer 인스턴스 없음 — 설치/.ldbk 복원 확인")
        return (0, 0, 0, 0)
    # 병렬 수확 — 100계정 팜서 순차(수분) → 병렬(수초). adb 는 인스턴스별 독립이라 안전.
    from concurrent.futures import ThreadPoolExecutor
    rows = []

    def _one(s):
        try:
            r = harvest_one(adb_bin, s, nudge=nudge)
            if r:
                log(f"[수확] {s} · {r['code']}")
            return r
        except Exception as e:
            log(f"[수확] {s} 실패: {str(e)[:80]}")
            return None

    with ThreadPoolExecutor(max_workers=min(16, max(1, len(use)))) as ex:
        for r in ex.map(_one, use):
            if r:
                rows.append(r)
    if not rows:
        return (0, 0, 0, 0)
    u, i, t = merge_accounts(accounts_fp, rows)
    log(f"[수확] 갱신 {u} · 신규 {i} · 총 {t}계정")
    return (u, i, t, len(rows))

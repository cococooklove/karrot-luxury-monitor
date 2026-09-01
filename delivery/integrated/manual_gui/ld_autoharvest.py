"""LDPlayer 온디바이스 토큰 자동수확 (GUI 번들).

기존 _refresh_tokens 의 HTTP refresh(WAF 403)를 대체한다:
LDPlayer(기본 루팅)의 정품 당근앱이 스스로 갱신한 access 를 su 로 직접 읽어
accounts.json 에 병합. 앱이 WAF·피닝을 처리하므로 PC 직접 refresh 불필요.

- 각 인스턴스 앱을 nudge(실행)해 만료임박 access 갱신 유발 → karrot_token.ds 읽기.
- accounts.json 스키마: [{code, refresh, access, proxy, label}] — AccountStore/freshest 호환.
"""
from __future__ import annotations

import base64
import contextlib
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

# ── 프로세스 간 락 ───────────────────────────────────────────────────────────
# 스레드락은 한 프로세스 안에서만 유효한데, 클라 PC 는 GUI 를 띄운 채 헤드리스
# 런타임을 돌릴 수 있다(테스트·이관 중 겹친다). 그때 lost update 가 나면 방금
# 수확한 토큰이 조용히 사라지고 그 계정은 다음 갱신에서 죽는다 — 복구는 폰 앱
# 스택뿐이다. 그래서 사이드카(accounts.json.lock)에 OS 파일락을 잡는다.
try:
    import fcntl as _fcntl            # POSIX(개발 Mac)
except ImportError:
    _fcntl = None
try:
    import msvcrt as _msvcrt          # Windows(배포 대상)
except ImportError:
    _msvcrt = None

# 락 대기 상한. 스테일 락 정책:
#   flock/msvcrt.locking 은 **파일핸들에 매달린 OS 락**이라 프로세스가 죽으면
#   커널이 즉시 놓는다 — 락파일 존재 여부 프로토콜과 달리 영구 스테일이 없다.
#   남는 위험은 살아 있는 프로세스가 오래 쥐는 경우뿐이고, 그때 수확기를 영원히
#   재우는 건 막으려던 lost update 보다 나쁘다. 그래서 상한을 넘기면 **크게 남기고
#   락 없이 진행한다**(= 최악이 손상이 아니라 lost update 로 되돌아갈 뿐).
LOCK_TIMEOUT = 20.0


def _try_lock(fd):
    """비블로킹 배타 락 시도. 성공 True / 남이 쥐고 있으면 False."""
    if _fcntl is not None:
        try:
            _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            return True
        except OSError:
            return False
    if _msvcrt is not None:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            # LK_NBLCK: 즉시 실패. EOF 너머 1바이트 구간도 잠글 수 있다.
            _msvcrt.locking(fd, _msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    return False


def _unlock(fd):
    if _fcntl is not None:
        _fcntl.flock(fd, _fcntl.LOCK_UN)
    elif _msvcrt is not None:
        os.lseek(fd, 0, os.SEEK_SET)
        _msvcrt.locking(fd, _msvcrt.LK_UNLCK, 1)


def lock_path(target_fp):
    return str(target_fp) + ".lock"


@contextlib.contextmanager
def _file_lock(target_fp, timeout=None, log=None):
    """accounts.json.lock 배타 락. 잡았으면 True, 못 잡았으면 False 를 넘긴다.

    못 잡아도 **예외를 내지 않고 진행한다** — 위 스테일 락 정책 참고. 대상 파일
    자체가 아니라 사이드카를 잠근다(대상은 os.replace 로 갈아끼워져 inode 가
    바뀌므로 거기에 건 락은 다음 writer 에게 안 보인다)."""
    _log = log or (lambda m: None)
    if _fcntl is None and _msvcrt is None:      # 락 수단 없는 플랫폼
        _log("[수확] 이 플랫폼에 파일락 수단이 없어 프로세스 간 보호 없이 진행합니다")
        yield False
        return
    timeout = LOCK_TIMEOUT if timeout is None else float(timeout)
    fd = None
    got = False
    try:
        try:
            d = os.path.dirname(os.path.abspath(target_fp)) or "."
            os.makedirs(d, exist_ok=True)
            fd = os.open(lock_path(target_fp), os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as e:
            _log(f"[수확] 파일락을 열 수 없어 락 없이 진행합니다: {str(e)[:80]}")
            yield False
            return
        deadline = time.time() + max(0.0, timeout)
        while True:
            got = _try_lock(fd)
            if got or time.time() >= deadline:
                break
            time.sleep(0.05)
        if not got:
            _log(f"[수확] accounts.json 파일락 {timeout:.0f}초 대기 초과 — 다른"
                 " 프로세스(GUI/헤드리스)가 쥔 채로 오래 있습니다. 락 없이"
                 " 진행합니다(수확분이 덮일 수 있음).")
        yield got
    finally:
        if fd is not None:
            if got:
                try:
                    _unlock(fd)
                except OSError:
                    pass
            try:
                os.close(fd)
            except OSError:
                pass

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


def ld_rows(console):
    """ldconsole list2 → [{index, name, started, pids}].

    list2: index,name,topWindowHandle,bindWindowHandle,androidStarted,pid,vboxPid,…

    started(=androidStarted)와 **pid 를 따로** 본다. 이 둘이 갈라지는 상태가
    이 코드의 핵심이다: VM 은 RUNNING 이고 dnplayer 프로세스도 있는데 게스트
    커널이 안 떠서 adb 기기가 영영 안 붙는 hang(= started 0 · pid 있음).
    그 상태에서 LDPlayer 는 그 인스턴스를 '이미 실행중'으로 보고 launch 를
    조용히 무시하므로, pid 를 봐야 quit 이 먼저 필요하다는 걸 알 수 있다."""
    try:
        p = subprocess.run([console, "list2"], capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = p.stdout.decode("utf-8", "ignore")
    except Exception:
        return []
    rows = []
    for line in out.splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) < 2 or not f[0].lstrip("-").isdigit():
            continue

        def _pid(i):
            try:
                v = int(f[i])
            except (IndexError, ValueError):
                return 0
            return v if v > 0 else 0

        rows.append({
            "index": f[0],
            "name": f[1],
            "started": len(f) >= 5 and f[4] not in ("0", "", "-1"),
            # dnplayer pid 와 vbox pid — 둘 중 하나라도 살아 있으면 프로세스가 있다.
            "pids": [x for x in (_pid(5), _pid(6)) if x],
        })
    return rows


# ── 함대 범위 ────────────────────────────────────────────────────────────────
# 어떤 인덱스가 "우리 함대"인지는 list2 로 알 수 없다. 운영 서버의 index 0 은
# LDPlayer 설치 때 딸려온 기본 인스턴스라 계정이 없고 사양도 다른데(6CPU/6144MB,
# 나머지는 2CPU/1024MB), 그걸 매 수확 사이클마다 깨우려다 기동 예산을 태웠다.
# ldboot.ps1 은 이미 1..5 로 하드코딩해 빼고 있었지만 앱은 그 목록을 몰랐다 —
# 함대 정의가 두 벌이면 한쪽만 고쳐지고 반드시 어긋난다. 파일 하나로 합친다.
FLEET_FILE = "data/fleet.json"


def fleet_indexes(app_dir=".", log=None):
    """함대로 볼 인덱스 목록. 파일이 없거나 깨졌으면 None(= 전부).

    없을 때 조용히 0 을 빼지 않는다. index 0 을 실제로 계정 인스턴스로 쓰는
    설치본이 있을 수 있고, 설정 없이 인스턴스가 사라지는 쪽이 더 나쁜 고장이다.
    서버는 data/fleet.json 을 두고, install.ps1 이 재설치 때 보존한다."""
    path = os.path.join(app_dir, FLEET_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        if log:
            log(f"[LDPlayer] {FLEET_FILE} 읽기 실패({e}) — 전체 인스턴스 대상")
        return None
    vals = raw.get("indexes") if isinstance(raw, dict) else raw
    if not isinstance(vals, list):
        if log:
            log(f"[LDPlayer] {FLEET_FILE} 형식이 아님(indexes 배열 필요) — 전체 대상")
        return None
    out = []
    for v in vals:
        try:
            out.append(str(int(v)))
        except (TypeError, ValueError):
            continue
    # 빈 목록은 "아무것도 켜지 마라"가 아니라 설정 실수로 본다 — 그대로 따르면
    # 함대 전체가 조용히 죽고 원인은 로그 어디에도 안 남는다.
    if not out:
        if log:
            log(f"[LDPlayer] {FLEET_FILE} 이 비었음 — 전체 인스턴스 대상")
        return None
    return out


def ld_list(console):
    """ldconsole list2 → [(index, name, is_running)]. (기존 호출자 호환)"""
    return [(r["index"], r["name"], r["started"]) for r in ld_rows(console)]


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


PROBE_TOKEN = "PROBE_OK"


def ld_probe(console, index, token=PROBE_TOKEN, timeout=None):
    """**인덱스로 직접** 그 인스턴스의 adb 에 말을 건다. 반환: 대답했는가.

    `ldconsole adb --index N --command "shell echo PROBE_OK"` — ldconsole 이 인덱스
    → serial 을 스스로 풀어준다. 그래서 우리가 포트 산술 같은 매핑을 지어낼 필요가
    없고(list2 에는 serial 필드가 없다), '이 인덱스가 대답하는가'를 집계가 아니라
    인스턴스 단위로 물을 수 있다. 실서버 실측:
        > ldconsole.exe adb --index 1 --command "shell echo PROBE_OK"
        PROBE_OK
        > ldconsole.exe adb --index 3 --command "shell echo PROBE_OK"
        adb.exe: device 'emulator-5560' not found

    성공 판정은 **종료코드 0 + 토큰만 단독으로 있는 줄**이다. 부분일치를 안 쓰는
    이유: ldconsole 버전에 따라 명령줄을 그대로 되울리는 경우가 있는데, 그러면
    실패 출력에도 토큰이 섞여 무응답을 응답으로 오독한다."""
    timeout = PROBE_TIMEOUT if timeout is None else timeout
    try:
        p = subprocess.run([console, "adb", "--index", str(index),
                            "--command", f"shell echo {token}"],
                           capture_output=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return False
    if p.returncode != 0:
        return False
    out = (p.stdout or b"").decode("utf-8", "ignore")
    return any(line.strip() == token for line in out.splitlines())


def ld_kill_pid(pid):
    """quit 이 안 먹을 때의 최후 수단. 비대화형 세션(작업 스케줄러·서비스)에서
    보낸 quit 은 대화형 데스크톱 세션이 소유한 프로세스를 못 죽인다. 실패해도
    예외를 내지 않는다 — 죽었는지는 호출자가 list2 로 확인한다."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], timeout=20,
                           capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            os.kill(int(pid), 9)
        return True
    except Exception:
        return False


# ── 토큰 신선도 정책 ─────────────────────────────────────────────────────────
# access 토큰 수명. JWT 의 exp-iat 실측값(2026-09-01, 서버 4계정 전부 동일).
# 서버가 발급하며 정한 값이라 우리가 못 바꾼다.
ACCESS_TTL = 1800
# nudge(force-stop→launch) 가 새 토큰을 받아오기까지의 실측 최대 대기. 3초 × 8회.
NUDGE_WORST = 24
#
# **당근 앱은 만료 전에 토큰을 갱신하지 않는다.** 이게 이 정책 전체를 정한다.
# 실서버 로그로 확정(2026-09-01):
#     20:07:44  갱신 4   ← 만료된 상태에서 nudge → 갱신됨
#     20:12:51  갱신 0   ← 잔여 ~1500초에 nudge → 앱이 갱신 안 함
#     20:32:51  갱신 0   ← 잔여 ~300초에 nudge → 그래도 갱신 안 함
#     20:37     만료 → 폴링이 "전계정(0)" 으로 헛돎
#     20:45     만료 후 nudge → 갱신 4
# 그래서 "만료 전에 미리 깨워 둔다"는 접근은 성립하지 않는다. 아무리 임계를
# 올려도 앱이 거절하고, 깨우는 비용(앱 콜드스타트)만 나간다. 우리가 할 수 있는
# 최선은 **만료 직후 최대한 빨리 깨우는 것**이고, 그러면 남은 문제는 "만료된 채
# 방치되는 시간을 얼마나 짧게 만드느냐"뿐이다.
NUDGE_BELOW = 30
# 그 시간을 짧게 만드는 방법은 고정 주기가 아니라 **만료 시각에서 역산한 스케줄**
# 이다. 고정 1200초 틱은 최악 20분을 죽은 채로 보낸다(실제로 그랬다).
HARVEST_INTERVAL = 300          # 아무 정보가 없을 때의 심장박동(상한)
HARVEST_MIN_SLEEP = 30          # 아래로는 안 내려간다 — nudge 폭주 방지


def next_harvest_delay(min_remaining, ceil=None, floor=HARVEST_MIN_SLEEP) -> int:
    """다음 수확까지 잘 시간. 가장 먼저 죽는 토큰의 만료 시각에서 역산한다.

    앱이 만료 전에는 갱신하지 않으므로 만료 **직후**에 깨어나야 한다. 너무 일찍
    깨면 헛수고(앱이 거절), 너무 늦게 깨면 그만큼 폴링이 계정 없이 헛돈다.
    잔여를 모르면(측정 실패) 심장박동 주기로 떨어진다.
    """
    ceil = HARVEST_INTERVAL if ceil is None else ceil
    try:
        rem = float(min_remaining)
    except (TypeError, ValueError):
        return int(ceil)
    # 만료 직후를 노린다. 이미 만료됐으면 바로 다시 간다(floor).
    return int(max(floor, min(ceil, rem + 1)))


# ── 함대 기동 정책 ───────────────────────────────────────────────────────────
# 한 사이클(수확 1틱)에 기동에 쓸 수 있는 총 시간. 6대 × 최대 180s + 간격이면
# 20분 폴링 주기를 통째로 잡아먹고 호출자를 물린다. 예산을 넘기면 남은 인스턴스는
# 다음 틱이 이어서 올린다 — 다만 토큰 수명이 30분(ACCESS_TTL)뿐이라 여유는 한 틱
# 남짓이다. 예산 초과가 연달아 나면 그 인스턴스의 토큰은 실제로 만료된다.
FLEET_BOOT_BUDGET = 600.0
# 인스턴스당 **한 사이클 내** 재기동 횟수 상한. 영구 고장난 인스턴스를 매 사이클
# 무한정 다시 깨우면 클라 PC 에서 adb/VM 폭주가 된다.
BOOT_RETRY = 1
# 응답 확인 대기. `adb devices` 목록은 살아있다는 증거가 못 된다 —
# 게스트 커널이 안 뜬 인스턴스도 device 로 남은 채 영원히 대답하지 않는다.
PROBE_TIMEOUT = 8
# 인덱스별 연속 기동 실패 횟수. 계속 실패하는 인스턴스를 부팅 순서 뒤로 미뤄
# 멀쩡한 인스턴스가 예산을 굶지 않게 한다(고장 1대가 나머지를 영구 차단하는 걸 막음).
_BOOT_FAILS = {}
# quit 이 실제로 먹어 프로세스가 사라질 때까지 기다리는 상한. 안 먹는 quit 이
# 호출자를 물면 안 되므로 반드시 유한하다.
QUIT_WAIT = 40
# taskkill 로 강제 종료한 뒤 사라짐을 확인하는 상한.
KILL_WAIT = 15


def _row_of(console, idx):
    for r in ld_rows(console):
        if str(r["index"]) == str(idx):
            return r
    return None


def _wait_process_gone(console, idx, limit):
    """list2 가 그 인덱스에 대해 pid/vboxPid 를 더는 보고하지 않을 때까지 대기.

    '프로세스가 사라졌다'의 근거를 list2 자신에게서 얻는다 — 인덱스로 바로 물어볼
    수 있고(serial 매핑 불필요) LDPlayer 가 launch 를 무시할지 판단하는 것과
    같은 정보원이다. 반환: 정말 사라졌는가."""
    waited = 0
    while True:
        r = _row_of(console, idx)
        if r is None or (not r["pids"] and not r["started"]):
            return True
        if waited >= limit:
            return False
        time.sleep(3)
        waited += 3


def _force_down(console, idx, name, log):
    """인스턴스 프로세스를 확실히 내린다. 반환: 정말 내려갔는가.

    **launch 전에 반드시 이걸 통과해야 한다.** dnplayer 프로세스가 남아 있으면
    LDPlayer 는 그 인스턴스를 이미 실행중으로 보고 `launch --index N` 을 조용히
    무시하며 성공을 반환한다(클라 서버에서 확인: launch 후 90초, 새 프로세스도
    새 adb 기기도 나타나지 않음). 확인 없이 켜면 함대는 영원히 죽어 있다."""
    r = _row_of(console, idx)
    if r is None or (not r["pids"] and not r["started"]):
        return True
    ld_quit(console, idx)
    if _wait_process_gone(console, idx, QUIT_WAIT):
        return True
    # quit 이 안 먹었다 — 비대화형 세션에서 보낸 quit 은 대화형 데스크톱 세션이
    # 소유한 프로세스를 못 죽인다. pid 직접 종료로 승격.
    r = _row_of(console, idx) or {}
    pids = r.get("pids") or []
    if pids:
        log(f"[LDPlayer] {name}(idx {idx}) quit 무반응 → pid {pids} 강제 종료")
        for p in pids:
            ld_kill_pid(p)
        if _wait_process_gone(console, idx, KILL_WAIT):
            return True
    log(f"[LDPlayer] {name}(idx {idx}) 프로세스가 안 내려갑니다 —"
        " 이 상태의 launch 는 무시되므로 건너뜁니다(다음 주기 재시도)")
    return False


def _responsive(adb_bin, serial, timeout=PROBE_TIMEOUT):
    """serial 이 실제로 대답하는가. hang 한 인스턴스를 '살아있음'으로 세면
    함대가 조용히 반쪽이 된다(오늘 클라 서버에서 실제로 일어난 일)."""
    try:
        return "ok" in _adb(adb_bin, serial, "shell", "echo", "ok", timeout=timeout)
    except Exception:
        return False


def live_instances(adb_bin, timeout=PROBE_TIMEOUT):
    """대답하는 기기 serial 만. list_instances 와 달리 hang 한 기기를 걸러낸다.

    이건 **수확기에 넘길 serial 목록**을 만드는 용도다(harvest_one 은 serial 로
    말한다). 어떤 인스턴스를 켜고 죽일지 정하는 데는 쓰지 않는다 — 그건
    ld_probe 로 인덱스마다 직접 묻는다."""
    return [s for s in list_instances(adb_bin) if _responsive(adb_bin, s, timeout)]


def ensure_ldplayer(adb_bin, boot_wait=180, log=None, gap=35, retry=BOOT_RETRY,
                    budget=FLEET_BOOT_BUDGET, console=None, app_dir="."):
    """설정된 **모든** 인스턴스가 떠 있도록 보장. 반환: 대답하는 serial 리스트.

    예전에는 기기가 하나라도 보이면 그대로 끝냈다. 그래서 6대 중 1대만 살아 있어도
    "함대가 있다"고 판단해 나머지 5대를 영영 안 깨웠고, 그 계정들의 토큰은 2시간 뒤
    만료된 채 방치됐다(= 유효계정 0). 이제는 집계를 안 본다: `ldconsole adb
    --index N` 으로 **인스턴스마다 직접** 대답을 듣고, 대답 못 하면 켠다.

    인스턴스별 판정:
      1) 프로브 응답      → 그대로 둔다.
      2) 무응답 + 프로세스(pid/vboxPid) 있음 또는 androidStarted=1
         → hang. VM 은 RUNNING 인데 게스트 커널이 안 떠 adb 가 영영 안 붙는다.
           **이 상태에서 launch 는 no-op 이다** — LDPlayer 가 이미 실행중으로 보고
           조용히 무시한다. quit(안 먹으면 pid 강제 종료) → 소멸 확인 → launch 순서.
      3) 무응답 + 프로세스 없음 → 그냥 launch.

    (2)에는 androidStarted=1 인데 대답 안 하는 인스턴스가 **포함된다** — 클라 서버가
    지금 딱 그 상태(6대 started, 5대 무응답)이고, 예전처럼 로그만 남기면 기계는
    고장난 채로 남는다. 인덱스 프로브가 있으니 지목이 모호하지 않아 조치할 수 있다.

    serial 은 반환값(수확기에 넘길 목록)에만 쓴다. 어떤 인덱스가 어떤 serial 인지는
    묻지 않는다 — list2 에 그 필드가 없고 이 코드베이스 어디에도 인덱스로 serial 을
    계산하는 곳이 없다. ldconsole 이 인덱스를 직접 받아 자기가 풀어준다.

    동시 기동은 VM 은 RUNNING 인데 게스트 커널이 안 뜨는 하드 실패다 → **순차 기동**."""
    log = log or (lambda m: None)
    deadline = time.time() + max(0.0, float(budget))
    console = console or find_ldconsole(adb_bin)
    if not console:
        log("[LDPlayer] ldconsole.exe 못찾음 — LDPlayer 설치경로 확인")
        return live_instances(adb_bin)
    insts = ld_rows(console)
    if not insts:
        log("[LDPlayer] 인스턴스 없음 — .ldbk 복원 필요")
        return live_instances(adb_bin)

    # 함대 밖 인스턴스는 프로브도 하지 않는다. 프로브만 해도 무응답으로 잡혀
    # 기동 대상이 되고, 그게 예산을 먹는다.
    want = fleet_indexes(app_dir, log)
    if want is not None:
        keep = [r for r in insts if r["index"] in want]
        skipped = [r["index"] for r in insts if r["index"] not in want]
        if not keep:
            log(f"[LDPlayer] {FLEET_FILE} 의 인덱스가 list2 에 하나도 없음"
                f"(설정 {','.join(want)}) — 전체 인스턴스 대상으로 진행")
        else:
            if skipped:
                log(f"[LDPlayer] 함대 밖 {len(skipped)}개 제외"
                    f"(index {','.join(skipped)}) — {FLEET_FILE}")
            insts = keep

    # (index, name, quit 이 먼저 필요한가) — 인덱스마다 직접 물어본 결과다.
    need, alive = [], 0
    for r in insts:
        if ld_probe(console, r["index"]):
            alive += 1
            continue
        need.append((r["index"], r["name"], bool(r["pids"]) or r["started"]))
    _hung = sum(1 for _i, _n, h in need if h)
    if _hung:
        log(f"[LDPlayer] 프로세스는 살아 있는데 응답 없는 인스턴스 {_hung}개 —"
            " 이 상태의 launch 는 무시되므로 종료부터 합니다")

    if not need:
        log(f"[LDPlayer] {alive}/{len(insts)}개 응답 — 추가 기동 불필요")
        return live_instances(adb_bin)

    def _key(item):
        try:
            n = int(item[0])
        except (TypeError, ValueError):
            n = 0
        return (_BOOT_FAILS.get(str(item[0]), 0), n)

    need.sort(key=_key)
    log(f"[LDPlayer] {len(insts)}개 중 {len(need)}개 무응답 —"
        f" 순차 부팅(간격 {gap}s · 예산 {int(budget)}s)…")
    for pos, (idx, name, hung) in enumerate(need):
        if time.time() >= deadline:
            log(f"[LDPlayer] 기동 예산 {int(budget)}s 소진 —"
                f" 남은 {len(need) - pos}개는 다음 수확 주기에 이어서 올립니다")
            break
        ok = down = False
        for attempt in range(retry + 1):
            if attempt:
                log(f"[LDPlayer] {name}(idx {idx}) 부팅 실패 → 재기동 {attempt}/{retry}")
            # hang 이면 첫 시도 전에, 재시도면 매번 — 프로세스가 정말 사라진 것을
            # 확인한 뒤에만 launch 한다. 안 그러면 launch 는 조용한 no-op 이다.
            if hung or attempt:
                down = _force_down(console, idx, name, log)
                if not down:
                    break       # 프로세스가 안 죽는다 → 이 인스턴스는 이번 주기 포기
            ld_launch(console, idx)
            waited = 0
            while waited < boot_wait and time.time() < deadline:
                time.sleep(5)
                waited += 5
                # 기동 성공도 그 인덱스에게 직접 묻는다. '아무 기기나 새로 생겼나'
                # 같은 집계는 다른 인스턴스가 늦게 뜬 것을 이 인스턴스의 성공으로
                # 오독한다.
                if ld_probe(console, idx):
                    log(f"[LDPlayer] {name}(idx {idx}) 기동 완료 ({waited}s)")
                    ok = True
                    break
            if ok:
                break
        if ok:
            alive += 1
            _BOOT_FAILS.pop(str(idx), None)
        else:
            # 실패해도 다음 인스턴스를 막지 않는다. 연속 실패는 다음 사이클 부팅
            # 순서를 뒤로 미루는 데만 쓴다(고장 1대가 예산을 선점하지 못하게).
            _BOOT_FAILS[str(idx)] = _BOOT_FAILS.get(str(idx), 0) + 1
            log(f"[LDPlayer] {name}(idx {idx}) 기동 실패 — 건너뜁니다"
                f" (연속 {_BOOT_FAILS[str(idx)]}회, 다음 주기 후순위)")
        if pos + 1 < len(need) and time.time() < deadline:
            time.sleep(gap)
    log(f"[LDPlayer] {alive}/{len(insts)}개 응답")
    return live_instances(adb_bin)


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


def harvest_one(adb_bin, serial, nudge=True, min_remaining=NUDGE_BELOW):
    """토큰 수확. 먼저 읽어(무-nudge) 아직 min_remaining 초 넘게 살아있으면 그대로 반환.
    만료임박/없음일 때만 nudge(앱 강제실행)해 앱이 갱신하도록 유도 → 재읽기.
    → 100계정 팜서 불필요한 앱실행 최소화(배터리·부하·방해 감소).

    기본 임계(NUDGE_BELOW)는 낮게 잡혀 있다. 앱이 만료 전 갱신을 거절하므로
    미리 깨우는 건 앱 콜드스타트만 낭비한다 — 위 상수 주석의 실측 로그 참고."""
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


def merge_accounts(accounts_fp, rows, log=None):
    """수확분을 accounts.json 에 병합. 동시 호출에도 파일이 깨지지 않는다.

    읽기-병합-쓰기 **전체**가 임계구역이다(base 를 읽고 나서 잠그면 이미 늦다):
    프로세스 안에서는 _MERGE_LOCK, 프로세스 사이에서는 accounts.json.lock 파일락.
    안 그러면 나중 쓰기가 앞선 쓰기의 삽입을 통째로 덮는다(lost update).
    승격은 같은 디렉터리의 **고유** 임시파일에서 한다 — 고정 이름
    (accounts.json.tmp)을 쓰면 두 쓰기가 한 파일에 뒤섞인 뒤 그 잡탕이
    os.replace 로 원자적으로 승격된다. replace 는 원자적이어도 내용은 아니다."""
    with _MERGE_LOCK:
        with _file_lock(accounts_fp, log=log):
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
                nudge=True, log=None, min_remaining=NUDGE_BELOW,
                stats=None):
    """모든 LDPlayer 인스턴스 수확 → accounts.json 병합. (updated, inserted, total, harvested).

    프로세스 안에서 한 번에 하나만 돈다. 두 스레드가 동시에 들어오면 뒤쪽은
    앞쪽이 끝날 때까지 기다렸다가 갱신된 파일 위에서 다시 병합한다 — 함대를 두 번
    깨우지 않고, ensure_ldplayer 가 인스턴스를 동시 기동하지도 않는다.

    주의: 이 락은 프로세스 안에서만 유효하다. GUI 와 헤드리스를 같은 기계에서
    동시에 띄우면 두 프로세스가 각각 수확하며, 그건 파일락으로만 막힌다."""
    with _HARVEST_LOCK:
        return _harvest_all_locked(accounts_fp, adb_bin, serials, nudge, log,
                                   min_remaining, stats)


def _harvest_all_locked(accounts_fp, adb_bin, serials, nudge, log,
                        min_remaining=NUDGE_BELOW, stats=None):
    log = log or (lambda m: None)
    adb_bin = find_adb(adb_bin)
    use = list(serials or [])
    if not use:
        # 기기가 '하나라도' 보이면 넘어가던 게 함대를 반쪽으로 만들었다. 매번
        # 설정된 인스턴스 전체를 보장한 뒤(클라가 LDPlayer 를 안 켜도 됨),
        # 그 결과 **대답하는** 기기만 수확한다.
        use = ensure_ldplayer(adb_bin, log=log)
    if not use:
        log("[수확] LDPlayer 인스턴스 없음 — 설치/.ldbk 복원 확인")
        return (0, 0, 0, 0)
    # 병렬 수확 — 100계정 팜서 순차(수분) → 병렬(수초). adb 는 인스턴스별 독립이라 안전.
    from concurrent.futures import ThreadPoolExecutor
    rows = []

    def _one(s):
        try:
            r = harvest_one(adb_bin, s, nudge=nudge, min_remaining=min_remaining)
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
    u, i, t = merge_accounts(accounts_fp, rows, log=log)
    # 다음 수확 시각을 정하려면 '가장 먼저 죽는 토큰'의 잔여가 필요하다.
    if stats is not None:
        rems = [_access_remaining(r.get("access", "")) for r in rows]
        rems = [x for x in rems if isinstance(x, (int, float))]
        stats["min_remaining"] = min(rems) if rems else None
        stats["harvested"] = len(rows)
    log(f"[수확] 갱신 {u} · 신규 {i} · 총 {t}계정")
    return (u, i, t, len(rows))

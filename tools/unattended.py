#!/usr/bin/env python3
"""
무인 자동 모니터 supervisor (크로스플랫폼: Windows/Mac/Linux).

온디바이스(LDPlayer/폰) 앱이 토큰을 스스로 갱신하고, 이 스크립트는
  1) 주기적으로 karrot_token.ds 를 adb 로 수확 → extract_tokens.py → accounts.json/config.json
  2) monitor.py 를 자식 프로세스로 상시 구동(죽으면 재시작)
두 축을 한 프로세스에서 감시한다. refresh(교환)는 앱이 하므로 여기엔 WAF 대상 호출이 없다.

클라 Windows 예시:
  python tools/unattended.py \
      --adb "C:\\LDPlayer\\LDPlayer9\\adb.exe" \
      --serial 127.0.0.1:5555 \
      --path /api/v5/integrate/search \
      --regions 6128 1234 --interval 300 --harvest-interval 1200

serial 미지정 시 adb devices 첫 기기 자동선택. adb 미지정 시 PATH + LDPlayer 흔한 경로 탐색.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = "com.towneers.www"
ACCOUNTS = os.path.join(ROOT, "data", "accounts.json")
CONFIG = os.path.join(ROOT, "data", "config.json")
STAGE = os.path.join(ROOT, "data", "harvest_stage")
EXTRACT = os.path.join(ROOT, "tools", "extract_tokens.py")
MONITOR = os.path.join(ROOT, "collector", "monitor.py")

# 토큰파일 경로(절대 or run-as 상대). 셸 메타문자 차단용 화이트리스트.
SAFE_PATH = re.compile(r"^/?[A-Za-z0-9][A-Za-z0-9/_.\-]*$")
APP_DATA = f"/data/data/{PKG}"

# 기기 접근 모드 캐시: "su"(루팅 LDPlayer) 또는 "run-as"(debuggable 재패키징)
_ACCESS_MODE = None

# LDPlayer 가 adb.exe 를 두는 흔한 위치(Windows)
LD_ADB_GUESSES = [
    r"C:\LDPlayer\LDPlayer9\adb.exe",
    r"C:\LDPlayer\LDPlayer4.0\adb.exe",
    r"C:\Program Files\LDPlayer\LDPlayer9\adb.exe",
    r"D:\LDPlayer\LDPlayer9\adb.exe",
]


def find_adb(explicit):
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        sys.exit(f"[adb] 지정 경로 없음: {explicit}")
    onpath = shutil.which("adb")
    if onpath:
        return onpath
    for g in LD_ADB_GUESSES:
        if os.path.isfile(g):
            return g
    sys.exit("[adb] adb 를 못 찾음. --adb 로 LDPlayer adb.exe 경로 지정.")


def adb(adb_bin, serial, *args, binary=False, timeout=30):
    """adb 를 인자 리스트로 실행(shell 미사용 → 인젝션 불가). bytes/str 반환."""
    cmd = [adb_bin]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"adb {' '.join(args[:2])} 실패: {err[:200]}")
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def pick_serial(adb_bin):
    out = adb(adb_bin, None, "devices")
    devs = [ln.split("\t")[0] for ln in out.splitlines()[1:]
            if ln.strip() and ln.endswith("device")]
    if not devs:
        sys.exit("[adb] 연결된 기기 없음. LDPlayer 켜졌는지 / adb connect 확인.")
    return devs[0]


def detect_access(adb_bin, serial):
    """토큰파일 읽기 경로 판별: su(루팅) 우선, 안 되면 run-as(debuggable)."""
    global _ACCESS_MODE
    if _ACCESS_MODE:
        return _ACCESS_MODE
    # LDPlayer 는 기본 루팅 → su 우선 시도
    try:
        out = adb(adb_bin, serial, "exec-out", "su", "-c", f"ls {APP_DATA}")
        if out and "No such" not in out and "not found" not in out.lower():
            _ACCESS_MODE = "su"
            return _ACCESS_MODE
    except Exception:
        pass
    # 폴백: 재패키징된 debuggable 앱
    try:
        adb(adb_bin, serial, "exec-out", "run-as", PKG, "ls")
        _ACCESS_MODE = "run-as"
        return _ACCESS_MODE
    except Exception:
        pass
    raise RuntimeError("토큰 접근 불가: su(루팅)도 run-as(debuggable)도 실패. "
                       "LDPlayer 루팅 ON 또는 앱 재패키징 필요.")


def discover_ds(adb_bin, serial, mode):
    """앱 데이터 안의 karrot_token.ds 경로들을 찾는다(모드별)."""
    if mode == "su":
        out = adb(adb_bin, serial, "exec-out", "su", "-c",
                  f"find {APP_DATA} -name karrot_token.ds")
    else:
        out = adb(adb_bin, serial, "exec-out", "run-as", PKG,
                  "find", ".", "-name", "karrot_token.ds")
    paths = []
    for ln in out.splitlines():
        p = ln.strip()
        if mode != "su":
            p = p.lstrip("./")
        if p and SAFE_PATH.match(p):     # 셸 메타문자 차단
            paths.append(p)
    return paths


def cat_ds(adb_bin, serial, mode, path):
    """토큰파일 raw 바이트 추출. path 는 SAFE_PATH 통과분만."""
    if mode == "su":
        return adb(adb_bin, serial, "exec-out", "su", "-c", f"cat {path}",
                   binary=True)
    return adb(adb_bin, serial, "exec-out", "run-as", PKG, "cat", path,
               binary=True)


def harvest_once(adb_bin, serial, verbose=True):
    """토큰파일 수확 → staging → extract_tokens.py → accounts.json/config.json."""
    mode = detect_access(adb_bin, serial)
    paths = discover_ds(adb_bin, serial, mode)
    if not paths:
        if verbose:
            print(f"[harvest] karrot_token.ds 못 찾음(mode={mode}, 로그인 확인).")
        return False
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE, ignore_errors=True)
    os.makedirs(STAGE, exist_ok=True)
    n = 0
    for i, p in enumerate(paths):
        data = cat_ds(adb_bin, serial, mode, p)   # raw 바이트(개행변환 없음)
        if not data:
            continue
        with open(os.path.join(STAGE, f"karrot_token_{i}.ds"), "wb") as f:
            f.write(data)
        n += 1
    if not n:
        if verbose:
            print("[harvest] 수확 0건.")
        return False
    # claude-45 의 extract_tokens.py 를 호출만(수정 안 함) → accounts/config 병합
    r = subprocess.run(
        [sys.executable, EXTRACT, STAGE, "--out", ACCOUNTS, "--headers-out", CONFIG],
        capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[harvest] extract_tokens 실패: {r.stderr.strip()[:200]}")
        return False
    if verbose:
        print(f"[harvest] {n}개 .ds → accounts.json 갱신 완료. {r.stdout.strip()[:120]}")
    return True


def harvest_loop(adb_bin, serial, interval, stop):
    while not stop.is_set():
        try:
            harvest_once(adb_bin, serial)
        except Exception as e:
            print(f"[harvest] 오류: {e}")
        stop.wait(interval)


def monitor_loop(path, regions, region_param, interval, code, stop):
    """monitor.py 를 자식으로 상시 구동. 죽으면 백오프 후 재시작."""
    argv = [sys.executable, MONITOR, "--path", path,
            "--region-param", region_param, "--regions", *regions,
            "--interval", str(interval), "--accounts", ACCOUNTS]
    if code:
        argv += ["--code", code]
    backoff = 5
    while not stop.is_set():
        print(f"[monitor] 시작: regions={regions}")
        proc = subprocess.Popen(argv, cwd=ROOT)
        while proc.poll() is None and not stop.is_set():
            time.sleep(1)
        if stop.is_set():
            proc.terminate()
            return
        print(f"[monitor] 종료(code={proc.returncode}). {backoff}s 후 재시작.")
        stop.wait(backoff)
        backoff = min(backoff * 2, 300)


def main():
    ap = argparse.ArgumentParser(description="무인 자동 모니터 supervisor")
    ap.add_argument("--adb", help="adb 실행파일 경로(미지정 시 PATH/LDPlayer 탐색)")
    ap.add_argument("--serial", help="기기 serial(미지정 시 첫 기기)")
    ap.add_argument("--path", required=True, help="검색 엔드포인트 경로")
    ap.add_argument("--regions", nargs="+", required=True)
    ap.add_argument("--region-param", default="region_id")
    ap.add_argument("--code", help="특정 계정 code 만 모니터(미지정 시 수명 최장)")
    ap.add_argument("--interval", type=int, default=300, help="모니터 폴링 주기 초")
    ap.add_argument("--harvest-interval", type=int, default=1200,
                    help="토큰 수확 주기 초(access 30분보다 짧게)")
    ap.add_argument("--no-monitor", action="store_true", help="수확만(모니터 미구동)")
    args = ap.parse_args()

    adb_bin = find_adb(args.adb)
    serial = args.serial or pick_serial(adb_bin)
    print(f"[init] adb={adb_bin} serial={serial}")

    # 시작 시 1회 즉시 수확(토큰 신선화 후 모니터 시작)
    try:
        harvest_once(adb_bin, serial)
    except Exception as e:
        print(f"[harvest] 초기 수확 실패(계속 진행): {e}")

    stop = threading.Event()
    threads = [threading.Thread(
        target=harvest_loop, args=(adb_bin, serial, args.harvest_interval, stop),
        daemon=True)]
    if not args.no_monitor:
        threads.append(threading.Thread(
            target=monitor_loop,
            args=(args.path, args.regions, args.region_param, args.interval,
                  args.code, stop), daemon=True))
    for t in threads:
        t.start()
    print("[run] 무인 구동 중. Ctrl+C 로 종료.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[run] 종료 신호. 정리 중…")
        stop.set()
        for t in threads:
            t.join(timeout=5)


if __name__ == "__main__":
    main()

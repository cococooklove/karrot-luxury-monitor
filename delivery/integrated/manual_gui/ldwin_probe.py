"""클라 PC(Windows)에서 에뮬레이터 탭 기능을 한 번에 진단한다.

맥에서는 검증할 수 없는 세 가지(창 핸들 확정 / 썸네일 캡처 / 탭 부착·복구)를
실제 LDPlayer 를 상대로 확인하고 PASS·FAIL 로 찍는다.

    python ldwin_probe.py            # 전체 진단(부착 테스트 6초 포함)
    python ldwin_probe.py --no-embed # 창 건드리지 않고 조회만
    python ldwin_probe.py --standin  # LDPlayer 없이: 메모장 창으로 Win32 레이어만 검증

--standin 은 LDPlayer 가 없는 Windows(VM 포함)에서 쓴다. 메모장을 띄워 그 창으로
창 탐색·캡처·치우기·부착·복구를 그대로 돌린다. LDPlayer 고유 부분(에뮬레이터가
자식 창 안에서 실제로 그려지는지)만 빠지고, 나머지 Win32 동작은 전부 확인된다.

부착 테스트는 인스턴스 창을 잠깐 가져왔다가 반드시 원래대로 되돌린다.
중간에 강제 종료하면 창이 앱과 함께 사라질 수 있으니 6초만 기다릴 것.
"""

import sys
import time

import ldwin

RESULTS = []

# SSH·cmd 콘솔은 cp1252/cp949 라 한글에서 UnicodeEncodeError 로 죽는다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def section(title):
    print(f"\n=== {title} ===")


def standin_target():
    """LDPlayer 대신 쓸 대역 창 — 메모장을 띄우고 그 창 핸들을 잡는다.

    다른 프로세스의 top-level 창이라는 점이 LDPlayer 와 같아서, SetParent·
    스타일 변경·PrintWindow 같은 위험한 부분을 그대로 검증할 수 있다.
    """
    import subprocess
    proc = subprocess.Popen(["notepad.exe"])
    for _ in range(40):                       # 창 뜰 때까지 최대 4초
        time.sleep(0.1)
        wins = ldwin.top_windows(pid=proc.pid, min_edge=50)
        if wins:
            return proc, wins[0]
    proc.terminate()
    return None, None


def run_standin(app):
    section("대역 창(메모장)으로 Win32 레이어 검증")
    proc, win = standin_target()
    if not check("대역 창 생성", win is not None):
        return summary()
    hwnd = win["hwnd"]
    print(f"    hwnd={hwnd} pid={win['pid']} title={win['title']!r}")

    def dump(label):
        print(f"    · {label}: {ldwin.window_state(hwnd)}")

    try:
        check("EnumWindows 로 창 탐색", True, f"제목·PID 확인됨")
        dump("초기")

        shot = ldwin.capture_ex(hwnd)
        if shot:
            w, h, _b, method = shot
            check("PrintWindow 캡처", True, f"{w}x{h} {method}")
        else:
            check("PrintWindow 캡처", False, "전부 검정 — 썸네일 대신 대체 문구 표시됨")

        emb = ldwin.Embedder()
        emb.stow(hwnd)
        time.sleep(0.3)
        check("창 치우기", ldwin.is_stowed(hwnd) and ldwin.is_window(hwnd))
        dump("치운 뒤")
        shot2 = ldwin.capture_ex(hwnd)
        check("치운 창도 캡처됨", bool(shot2),
              "화면 밖이어도 썸네일이 유지되는지 — 이게 SW_HIDE 를 안 쓴 이유")
        emb.unstow_all()
        time.sleep(0.3)
        check("창 되돌리기", not ldwin.is_stowed(hwnd) and ldwin.is_visible(hwnd))
        dump("되돌린 뒤")

        from PyQt6 import QtWidgets
        host = QtWidgets.QWidget()
        host.setWindowTitle("ldwin probe — 대역 창 부착 테스트")
        host.resize(420, 620)
        host.show()
        app.processEvents()

        ok = emb.embed(hwnd, int(host.winId()), host.width(), host.height())
        check("SetParent 부착", ok, "반환값이 아니라 GetParent 로 판정")
        dump("부착 뒤")
        if ok:
            deadline = time.time() + 4
            while time.time() < deadline:
                app.processEvents()
                time.sleep(0.05)
            shot3 = ldwin.capture_ex(hwnd)
            check("부착 상태에서 렌더", bool(shot3), "자식 창이 실제로 그려지는가")
            emb.release(hwnd)
            time.sleep(0.4)
            app.processEvents()
            check("분리 후 원래 창으로 복구",
                  ldwin.is_window(hwnd) and ldwin.is_visible(hwnd)
                  and not ldwin.is_stowed(hwnd))
            dump("분리 뒤")
        host.close()
        app.processEvents()
        check("복구 후에도 대역 프로세스 생존", proc.poll() is None)
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
    print("\n  참고: LDPlayer 는 가속 렌더라 캡처·부착 결과가 메모장과 다를 수 있다.")
    print("  실제 인스턴스가 있는 PC 에서 --standin 없이 한 번 더 돌릴 것.")
    return summary()


def main():
    do_embed = "--no-embed" not in sys.argv

    section("환경")
    print(f"  platform : {sys.platform}")
    print(f"  python   : {sys.version.split()[0]} "
          f"({'64bit' if sys.maxsize > 2**32 else '32bit'})")
    if not check("Windows 에서 실행", ldwin.IS_WINDOWS, sys.platform):
        print("\n이 스크립트는 LDPlayer 가 도는 Windows PC 에서 돌려야 합니다.")
        return 1

    # Qt 는 시작할 때 프로세스 DPI 인식을 PER_MONITOR_AWARE_V2 로 바꾼다. 그 전후로
    # GetWindowRect 가 돌려주는 좌표계가 달라지므로(200% 스케일이면 정확히 2배 차이),
    # 창 좌표를 건드리기 전에 먼저 QApplication 을 만들어 좌표계를 고정한다.
    # 실제 앱도 QApplication → MainWindow → ldwin 순서라 이게 운영과 같은 조건이다.
    app = None
    if "--no-embed" not in sys.argv:
        from PyQt6 import QtWidgets
        app = QtWidgets.QApplication(sys.argv[:1])

    if "--standin" in sys.argv:
        return run_standin(app)

    boot_idx = None
    if "--boot" in sys.argv:
        pos = sys.argv.index("--boot")
        boot_idx = int(sys.argv[pos + 1]) if len(sys.argv) > pos + 1 else 1

    section("1. ldconsole")
    console = ldwin.find_console()
    print(f"  경로: {console}")
    if not check("ldconsole.exe 발견", bool(console)):
        return 1

    import subprocess
    raw = subprocess.run([console, "list2"], capture_output=True, timeout=20,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    text = raw.stdout.decode("utf-8", "ignore")
    print("  list2 원문:")
    for line in text.splitlines():
        print(f"    | {line}")
    parsed = ldwin.parse_list2(text)
    check("list2 파싱", bool(parsed), f"{len(parsed)}행")
    for r in parsed:
        print(f"    index={r['index']} name={r['name']!r} top_hwnd={r['top_hwnd']} "
              f"bind={r['bind_hwnd']} running={r['running']} pid={r['pid']}")

    section("2. 실제 창 탐색")
    wins = ldwin.player_windows()
    for w in wins:
        print(f"    hwnd={w['hwnd']} pid={w['pid']} title={w['title']!r} "
              f"visible={ldwin.is_visible(w['hwnd'])} stowed={ldwin.is_stowed(w['hwnd'])}")
    if wins or boot_idx is None:
        check("LDPlayer 창 발견", bool(wins), f"{len(wins)}개")
    else:
        print(f"  [INFO] 실행 중인 인스턴스 없음 — --boot {boot_idx} 로 직접 띄운다")

    rows = ldwin.resolve_instances(parsed, wins)
    live = [r for r in rows if r["running"] and r["top_hwnd"]]
    raw_hwnd = {p["index"]: p["top_hwnd"] for p in parsed}
    for r in rows:
        same = "list2 그대로" if r["top_hwnd"] == raw_hwnd.get(r["index"]) else "보정됨"
        print(f"    index={r['index']} → hwnd={r['top_hwnd']} ({same}) "
              f"title={r.get('title')!r} running={r['running']}")
    booted = None
    if not live and boot_idx is not None:
        # 검증용으로 인스턴스를 하나만 띄운다(동시 기동은 부팅 hang 을 부른다).
        section(f"1-b. 인스턴스 {boot_idx} 부팅 (검증 끝나면 다시 끔)")
        subprocess.run([console, "launch", "--index", str(boot_idx)], timeout=60,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for waited in range(0, 180, 3):
            time.sleep(3)
            wins = ldwin.player_windows()
            if wins:
                print(f"    창 등장 — {waited + 3}초")
                break
        rows = ldwin.resolve_instances(
            ldwin.parse_list2(subprocess.run(
                [console, "list2"], capture_output=True, timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            ).stdout.decode("utf-8", "ignore")), ldwin.player_windows())
        live = [r for r in rows if r["running"] and r["top_hwnd"]]
        booted = boot_idx if live else None
        check(f"인스턴스 {boot_idx} 부팅", bool(live))

    check("인스턴스↔창 매칭", bool(live), f"실행 중 {len(live)}개")
    if not live:
        print("\nLDPlayer 인스턴스를 하나 이상 켠 뒤 다시 실행하세요.")
        print("(--boot <index> 를 주면 이 스크립트가 직접 띄웠다가 끕니다)")
        return 1

    def shutdown_booted():
        if booted is None:
            return
        print(f"\n  인스턴스 {booted} 종료 — 검증 전 상태로 되돌림")
        subprocess.run([console, "quit", "--index", str(booted)], timeout=60,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    section("3. 썸네일 캡처")
    shot_ok = 0
    for r in live:
        t0 = time.time()
        shot = ldwin.capture_ex(r["top_hwnd"])
        ms = int((time.time() - t0) * 1000)
        if shot:
            shot_ok += 1
            w, h, _buf, method = shot
            print(f"    index={r['index']} {w}x{h} {method} {ms}ms")
        else:
            print(f"    index={r['index']} 캡처 실패({ms}ms) — 카드에 대체 문구 표시됨")
    check("썸네일 캡처", shot_ok > 0,
          f"{shot_ok}/{len(live)} 성공 (0이면 그리드는 이름·상태만 표시)")

    section("4. 창 치우기(stow) 왕복")
    emb = ldwin.Embedder()
    target = live[0]
    hwnd = target["top_hwnd"]
    before = ldwin.is_stowed(hwnd)
    emb.stow(hwnd)
    time.sleep(0.4)
    stowed = ldwin.is_stowed(hwnd)
    still_alive = ldwin.is_window(hwnd)
    emb.unstow_all()
    time.sleep(0.4)
    back = not ldwin.is_stowed(hwnd) and ldwin.is_visible(hwnd)
    check("창 치우기", stowed and not before, "화면 밖으로 이동")
    check("치운 뒤에도 인스턴스 생존", still_alive)
    check("창 되돌리기", back, "화면 안 + 보임")

    if not do_embed:
        shutdown_booted()
        return summary()

    section("5. 탭 부착 왕복 (6초)")
    from PyQt6 import QtWidgets

    host = QtWidgets.QWidget()
    host.setWindowTitle("ldwin probe — 부착 테스트")
    host.resize(420, 720)
    host.show()
    app.processEvents()

    st_before = ldwin.window_state(hwnd)
    print(f"    · 부착 전: {st_before}")
    ok = emb.embed(hwnd, int(host.winId()), host.width(), host.height())
    check("SetParent 부착", ok)
    if ok:
        deadline = time.time() + 6
        while time.time() < deadline:
            app.processEvents()
            time.sleep(0.05)
        print("    (이 6초 동안 창 안에 화면이 보였는지 / 클릭·키입력이 먹었는지 확인)")
        emb.release(hwnd)
        time.sleep(0.5)
        app.processEvents()
        st = ldwin.window_state(hwnd)
        print(f"    · 분리 뒤: {st}")
        restored = (ldwin.is_window(hwnd) and ldwin.is_visible(hwnd)
                    and not ldwin.is_stowed(hwnd))
        check("분리 후 원래 창으로 복구", restored)
        # 부모에서 떨어졌는지 + 창 장식(WS_CAPTION)이 돌아왔는지까지 본다.
        # 이걸 안 보면 '자식인 채 살아 있는' 상태를 복구로 오판한다.
        check("부모에서 분리됨", st.get("parent", -1) in (0, ldwin.desktop_hwnd()))
        # LDPlayer 는 타이틀바를 직접 그리는 borderless popup 이라 WS_CAPTION 이
        # 원래 없다. 특정 비트가 아니라 '부착 전과 똑같은가'로 봐야 한다.
        check("창 스타일·위치 원복",
              (st.get("style"), st.get("exstyle"), st.get("rect"))
              == (st_before.get("style"), st_before.get("exstyle"),
                  st_before.get("rect")),
              f"전 {st_before.get('style')}/{st_before.get('rect')} → "
              f"후 {st.get('style')}/{st.get('rect')}")
    host.close()
    app.processEvents()
    check("복구 후에도 인스턴스 생존", ldwin.is_window(hwnd))

    shutdown_booted()
    return summary()


def summary():
    section("결과")
    bad = [n for n, ok in RESULTS if not ok]
    for n, ok in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    if bad:
        print(f"\n실패 {len(bad)}건: {', '.join(bad)}")
        print("이 출력을 그대로 복사해서 전달하면 원인 파악됩니다.")
        return 1
    print("\n전부 통과 — 에뮬레이터 탭을 그대로 써도 됩니다.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n중단됨 — 창이 이상하면 앱을 켜면 자동 복구됩니다(rescue).")
        raise SystemExit(130)

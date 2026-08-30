"""클라 PC(Windows)에서 에뮬레이터 탭 기능을 한 번에 진단한다.

맥에서는 검증할 수 없는 세 가지(창 핸들 확정 / 썸네일 캡처 / 탭 부착·복구)를
실제 LDPlayer 를 상대로 확인하고 PASS·FAIL 로 찍는다.

    python ldwin_probe.py            # 전체 진단(부착 테스트 6초 포함)
    python ldwin_probe.py --no-embed # 창 건드리지 않고 조회만

부착 테스트는 인스턴스 창을 잠깐 가져왔다가 반드시 원래대로 되돌린다.
중간에 강제 종료하면 창이 앱과 함께 사라질 수 있으니 6초만 기다릴 것.
"""

import sys
import time

import ldwin

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def section(title):
    print(f"\n=== {title} ===")


def main():
    do_embed = "--no-embed" not in sys.argv

    section("환경")
    print(f"  platform : {sys.platform}")
    print(f"  python   : {sys.version.split()[0]} "
          f"({'64bit' if sys.maxsize > 2**32 else '32bit'})")
    if not check("Windows 에서 실행", ldwin.IS_WINDOWS, sys.platform):
        print("\n이 스크립트는 LDPlayer 가 도는 Windows PC 에서 돌려야 합니다.")
        return 1

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
    check("LDPlayer 창 발견", bool(wins), f"{len(wins)}개")

    rows = ldwin.resolve_instances(parsed, wins)
    live = [r for r in rows if r["running"] and r["top_hwnd"]]
    raw_hwnd = {p["index"]: p["top_hwnd"] for p in parsed}
    for r in rows:
        same = "list2 그대로" if r["top_hwnd"] == raw_hwnd.get(r["index"]) else "보정됨"
        print(f"    index={r['index']} → hwnd={r['top_hwnd']} ({same}) "
              f"title={r.get('title')!r} running={r['running']}")
    check("인스턴스↔창 매칭", bool(live), f"실행 중 {len(live)}개")
    if not live:
        print("\nLDPlayer 인스턴스를 하나 이상 켠 뒤 다시 실행하세요.")
        return 1

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
        return summary()

    section("5. 탭 부착 왕복 (6초)")
    from PyQt6 import QtWidgets

    app = QtWidgets.QApplication(sys.argv[:1])
    host = QtWidgets.QWidget()
    host.setWindowTitle("ldwin probe — 부착 테스트")
    host.resize(420, 720)
    host.show()
    app.processEvents()

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
        restored = (ldwin.is_window(hwnd) and ldwin.is_visible(hwnd)
                    and not ldwin.is_stowed(hwnd))
        check("분리 후 원래 창으로 복구", restored)
    host.close()
    app.processEvents()
    check("복구 후에도 인스턴스 생존", ldwin.is_window(hwnd))

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

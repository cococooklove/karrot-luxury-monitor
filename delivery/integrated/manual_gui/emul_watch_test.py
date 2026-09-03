"""에뮬레이터 창 감시 — launch 직후 뜬 창을 스캔(8s)을 기다리지 않고 즉시 치운다 (offscreen).

    QT_QPA_PLATFORM=offscreen python emul_watch_test.py

순서: LDPlayer 창이 뜬다 → 150ms 감시가 발견 → 화면 밖으로 치움 → 스캔 즉시 →
탭 부착. 창이 바탕화면에 머무는 시간은 감시 주기 하나뿐이어야 한다.
Win32 없이 검증하려고 ldwin 모듈과 Embedder 를 가짜로 바꿔 끼운다.
"""
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


from PyQt6 import QtWidgets

import importlib.util

spec = importlib.util.spec_from_file_location("_main_under_test", "main.py")
m = importlib.util.module_from_spec(spec)
saved = sys.argv
sys.argv = ["main.py"]
try:
    spec.loader.exec_module(m)
except SystemExit:
    pass
finally:
    sys.argv = saved

try:
    import ld_autoharvest
    ld_autoharvest.harvest_all = lambda *a, **k: (0, 0, 0, 0)
    ld_autoharvest.ensure_ldplayer = lambda *a, **k: []
except Exception:
    pass
m.guest_proxy_sync = lambda *a, **k: {}

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class FakeLdwin:
    IS_WINDOWS = True

    def __init__(self):
        self.alive = set()
        self.tops = []          # player_windows() 가 돌려줄 top-level 창

    def is_window(self, h):
        return h in self.alive

    def rescue(self, h):
        return False

    def player_windows(self):
        return [{"hwnd": h, "pid": 0, "title": ""} for h in self.tops]


class FakeEmbedder:
    def __init__(self):
        self.embedded = {}
        self.stowed = set()
        self.calls = []

    def embed(self, hwnd, host_hwnd, w, h):
        self.calls.append(("embed", hwnd))
        self.embedded[hwnd] = host_hwnd
        self.stowed.discard(hwnd)
        return True

    def release(self, hwnd):
        return self.embedded.pop(hwnd, None) is not None

    def stow(self, hwnd):
        self.calls.append(("stow", hwnd))
        if hwnd in self.embedded:
            return False
        self.stowed.add(hwnd)
        return True

    def unstow_all(self):
        self.stowed.clear()

    def release_all(self):
        self.embedded.clear()

    def fit(self, *a):
        pass

    def prune(self):
        pass


class FakeThread:
    def __init__(self, running):
        self._r = running

    def isRunning(self):
        return self._r


def row(index, hwnd):
    return {"index": index, "name": f"계정{index}", "top_hwnd": hwnd,
            "bind_hwnd": 0, "running": True, "pid": 0, "title": f"계정{index}"}


w = m.MainWindow("watch")
ld, emb = FakeLdwin(), FakeEmbedder()
w._ldwin, w._emul = ld, emb
w._emul_closing = False
w._emul_console = "fake"
scans = []
w._emul_scan = lambda: scans.append(1)

print("=== 감시 타이머는 존재하고 스캔 타이머보다 훨씬 촘촘하다 ===")
ck("watch timer 있음", hasattr(w, "_emul_watch_timer"))
ck("주기 ≤ 250ms", w._emul_watch_timer.interval() <= 250, str(w._emul_watch_timer.interval()))
ck("스캔 타이머(8s)보다 촘촘", w._emul_watch_timer.interval() < w._emul_timer.interval())

print("=== 첫 스캔(잔재 복구) 전에는 감시가 손대지 않는다 ===")
ld.alive = {101}; ld.tops = [101]
w._emul_watch_tick()
ck("rescue 전 stow 없음", not emb.stowed and not scans, str(emb.calls))

print("=== 첫 스캔 뒤 새 창 등장 → 즉시 치움 + 스캔 앞당김 ===")
w._emul_apply([])                                  # 첫 스캔(빈 결과) → rescued
ck("rescued 플래그", w._emul_rescued)
w._emul_watch_tick()
ck("뜬 창 즉시 stow", 101 in emb.stowed, str(emb.calls))
ck("스캔 즉시 1회", len(scans) == 1, str(len(scans)))

print("=== 같은 창은 다시 스캔을 부르지 않는다(재stow 는 해도 된다) ===")
w._emul_watch_tick(); w._emul_watch_tick()
ck("스캔 여전히 1회", len(scans) == 1, str(len(scans)))

print("=== 스캔이 붙이면 감시는 그 창을 건드리지 않는다 ===")
w._emul_apply([row(1, 101)])
ck("탭 부착", 101 in emb.embedded and 1 in w._emul_hosts)
n = len(emb.calls)
w._emul_watch_tick()
ck("부착 창 stow 호출 없음", not [c for c in emb.calls[n:] if c == ("stow", 101)],
   str(emb.calls[n:]))

print("=== 스캔 도중 새 창 → 스캔 끝나면 바로 한 번 더 ===")
ld.alive.add(102); ld.tops = [101, 102]
w._emul_thread = FakeThread(running=True)
w._emul_watch_tick()
ck("스캔 중엔 직접 호출 안 함", len(scans) == 1, str(len(scans)))
ck("재스캔 예약", w._emul_rescan)
ck("그래도 창은 바로 치움", 102 in emb.stowed)
w._emul_thread = None
w._emul_apply([row(1, 101)])                       # 스캔 결과 도착(아직 102 미해결)
app.processEvents()
ck("결과 도착 직후 재스캔", len(scans) == 2, str(len(scans)))
ck("예약 해제", not w._emul_rescan)

print("=== 죽은 창의 hwnd 가 재사용되면 새 창으로 본다 ===")
ld.alive.discard(102); ld.tops = [101]
w._emul_apply([row(1, 101)])                       # prune → 102 는 seen 에서 빠짐
ld.alive.add(102); ld.tops = [101, 102]
w._emul_watch_tick()
ck("재등장 → 스캔 다시", len(scans) == 3, str(len(scans)))

print("=== 종료 시 감시 타이머도 멈춘다 ===")
w._emul_watch_timer.start()
w._emul_shutdown()
ck("watch timer 정지", not w._emul_watch_timer.isActive())

fails = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(fails)}/{len(R)} passed")
if fails:
    print("FAILED:", fails)
    sys.exit(1)

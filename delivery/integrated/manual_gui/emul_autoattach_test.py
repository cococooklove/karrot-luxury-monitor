"""에뮬레이터 탭 — 실행 중 인스턴스는 스캔 즉시 전부 탭으로 붙는다 (offscreen).

    QT_QPA_PLATFORM=offscreen python emul_autoattach_test.py

LDPlayer 창은 앱 바깥(바탕화면)에 절대 나타나면 안 된다. 그래서:
  · 카드 클릭 없이 스캔이 준 live 인스턴스 전부를 탭으로 부착한다
  · 부착 상한 없음
  · 부착 실패한 창은 화면 밖으로 치운다(다음 스캔에서 재시도)
  · 탭은 닫을 수 없다(닫으면 바탕화면으로 나가므로)
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

    def is_window(self, h):
        return h in self.alive

    def rescue(self, h):
        return False


class FakeEmbedder:
    def __init__(self):
        self.fail = set()
        self.embedded = {}
        self.stowed = set()
        self.calls = []

    def embed(self, hwnd, host_hwnd, w, h):
        self.calls.append(("embed", hwnd))
        if hwnd in self.fail:
            return False
        self.embedded[hwnd] = host_hwnd
        self.stowed.discard(hwnd)
        return True

    def release(self, hwnd):
        self.calls.append(("release", hwnd))
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

    def focus(self, *a):
        pass

    def prune(self):
        pass


def row(index, hwnd):
    return {"index": index, "name": f"계정{index}", "top_hwnd": hwnd,
            "bind_hwnd": 0, "running": True, "pid": 0, "title": f"계정{index}"}


w = m.MainWindow("watch")
ld, emb = FakeLdwin(), FakeEmbedder()
w._ldwin, w._emul = ld, emb
w._emul_closing = False
w._emul_console = "fake"

print("=== 자동 부착 ===")
ld.alive = {101, 102, 103}
w._emul_apply([row(1, 101), row(2, 102), row(3, 103)])
ck("live 3개 → 탭 3개", w.emulTabs.count() == 3, str(w.emulTabs.count()))
ck("전부 embed 됨", sorted(emb.embedded) == [101, 102, 103], str(emb.embedded))
ck("hosts 3개", sorted(w._emul_hosts) == [1, 2, 3], str(sorted(w._emul_hosts)))
first_tab = w.emulTabs.currentIndex()

print("=== 같은 스캔 반복 → 재부착 없음 ===")
n_before = len(emb.calls)
w._emul_apply([row(1, 101), row(2, 102), row(3, 103)])
ck("embed 재호출 없음", len(emb.calls) == n_before, str(emb.calls[n_before:]))
ck("탭 그대로 3개", w.emulTabs.count() == 3)

print("=== 새 인스턴스 등장 → 자동 부착, 현재 탭 유지 ===")
w.emulTabs.setCurrentIndex(1)
ld.alive.add(104)
w._emul_apply([row(1, 101), row(2, 102), row(3, 103), row(4, 104)])
ck("탭 4개", w.emulTabs.count() == 4, str(w.emulTabs.count()))
ck("보던 탭 안 바뀜", w.emulTabs.currentIndex() == 1, str(w.emulTabs.currentIndex()))

print("=== 부착 실패 → 바탕화면 대신 치움, 다음 스캔 재시도 ===")
ld.alive.add(105); emb.fail.add(105)
w._emul_apply([row(1, 101), row(2, 102), row(3, 103), row(4, 104), row(5, 105)])
ck("실패 창은 탭 없음", 5 not in w._emul_hosts and w.emulTabs.count() == 4)
ck("실패 창은 치워짐", 105 in emb.stowed, str(emb.stowed))
emb.fail.clear()
w._emul_apply([row(1, 101), row(2, 102), row(3, 103), row(4, 104), row(5, 105)])
ck("재시도 성공 → 탭 5개", w.emulTabs.count() == 5 and 105 in emb.embedded)

print("=== 인스턴스 죽음 → 탭 제거 ===")
ld.alive.discard(102)
w._emul_apply([row(1, 101), row(3, 103), row(4, 104), row(5, 105)])
ck("탭 4개", w.emulTabs.count() == 4, str(w.emulTabs.count()))
ck("hosts 에서 빠짐", 2 not in w._emul_hosts)
ck("카드도 빠짐", 2 not in w._emul_cards)

print("=== 상한·닫기 없음 ===")
ld.alive |= set(range(200, 230))
w._emul_apply([row(i, 200 + i) for i in range(30)])
ck("30개 전부 부착(상한 없음)", w.emulTabs.count() == 30, str(w.emulTabs.count()))
ck("탭 닫기 불가", not w.emulTabs.tabsClosable())
ck("모두닫기·치우기 컨트롤 없음",
   not hasattr(w, "emulCloseAllBtn") and not hasattr(w, "emulStowChk"))

fails = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(fails)}/{len(R)} passed")
if fails:
    print("FAILED:", fails)
    sys.exit(1)

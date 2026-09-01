"""창을 실제로 만들어 본다 — 참조 불일치는 이것으로만 잡힌다.

2026-09-01, 반쪽만 담긴 커밋이 배포돼 운영이 4분 멈췄다. main.py 는 새 코드,
daangn/controller.py 는 옛 코드였고 기동 즉시 이렇게 죽었다:

    AttributeError: 'MainController' object has no attribute 'task_progress'

`ast.parse` 로는 절대 안 잡힌다 — 구문은 멀쩡했다. 창을 실제로 만들어 봐야
한다. 그래서 커밋 전에 이걸 돌린다.

디스플레이가 없는 서버·CI 를 위해 offscreen 으로 띄운다. PyQt6 가 없으면
건너뛴다(그 환경에서는 어차피 GUI 를 안 쓴다).

실행: python gui_boot_test.py
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


try:
    from PyQt6 import QtWidgets
except Exception as e:
    print(f"[SKIP] PyQt6 없음 — GUI 기동 검사를 건너뜁니다 ({type(e).__name__})")
    raise SystemExit(0)

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

# 기동 검사는 **밀폐돼야 한다.** 창을 만들면 수확 스레드가 즉시 한 번 돌고,
# 그건 실서버에서 LDPlayer 함대를 실제로 깨우는 일이다(force-stop → launch).
# 무엇이 참조 불일치 없이 뜨는지만 보면 되므로 바깥일은 전부 막는다.
try:
    import ld_autoharvest
    ld_autoharvest.harvest_all = lambda *a, **k: (0, 0, 0, 0)
    ld_autoharvest.ensure_ldplayer = lambda *a, **k: []
except Exception:
    pass
m.guest_proxy_sync = lambda *a, **k: {}

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

EXPECT = {
    "all": ["수동 검색", "매물 감시", "에뮬레이터"],
    "watch": ["매물 감시", "에뮬레이터"],
    "manual": ["수동 검색"],
}

print("=== 창이 실제로 떠야 한다 (모드별) ===")
wins = []
for mode, tabs in EXPECT.items():
    try:
        w = m.MainWindow(mode)
    except Exception as e:
        ck(f"{mode} 기동", False, f"{type(e).__name__}: {str(e)[:120]}")
        continue
    wins.append(w)
    got = [w.tabs.tabText(i) for i in range(w.tabs.count())]
    ck(f"{mode} 기동", True)
    ck(f"{mode} 탭 구성", got == tabs, str(got))

print("\n=== 모드가 백그라운드 기동을 가른다 ===")
# 수동 전용에서 수확기가 같이 돌면 같은 인스턴스에 force-stop 이 겹친다.
if wins:
    by_mode = dict(zip(EXPECT.keys(), wins))
    mw = by_mode.get("manual")
    ww = by_mode.get("watch")
    if mw is not None:
        ck("수동 전용은 수확 스레드 없음",
           getattr(mw, "_harvest_thread", None) is None)
    if ww is not None:
        ck("감시 모드는 수확 스레드 있음",
           getattr(ww, "_harvest_thread", None) is not None)

print("\n=== 화면에서 부르는 것들이 실제로 있다 ===")
# 버튼이 없는 메서드를 가리키면 클릭하는 순간 죽는다. 연결 대상이 있는지만 본다.
w0 = wins[0] if wins else None
for attr in ("on_emul_add_clicked", "on_accounts_btn_clicked",
             "on_auto_excel_clicked", "_alog"):
    ck(f"{attr} 있음", callable(getattr(w0, attr, None)))
ck("계정 추가 버튼 있음", getattr(w0, "emulAddBtn", None) is not None)

bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패:", bad)
# 창을 정리하는 동안 타이머가 이미 삭제된 위젯을 건드려 시끄러운 예외가 난다.
# 여기서 볼 것은 '떴는가' 뿐이라 정리 경로를 타지 않고 그대로 끝낸다.
sys.stdout.flush()
os._exit(1 if bad else 0)

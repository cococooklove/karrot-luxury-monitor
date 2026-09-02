"""부팅 자동실행 커맨드가 지금 창의 모드를 싣는가.

운영은 수동검색과 매물감시를 **분리해서** 쓴다. 3탭 합본(all)은 쓰지 않는다 —
합본이 뜨면 그 창이 수확·폴링·라우터를 소유해, 따로 띄운 매물감시 창과 같은
keyword_routes.json 을 놓고 다툰다(실서버 2026-09-02 에 엑셀 조건이 사라진 경로).

그런데 `_boot_command` 는 --watchdog 만 붙이고 모드 인자를 빼먹었다. 매물감시
창에서 부팅 자동실행을 켜면 다음 부팅부터 합본이 떴다.

실행: python boot_command_test.py
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
    from PyQt6 import QtWidgets  # noqa: F401
except Exception as e:
    print(f"[SKIP] PyQt6 없음 ({type(e).__name__})")
    raise SystemExit(0)

import importlib.util

spec = importlib.util.spec_from_file_location("_m", "main.py")
m = importlib.util.module_from_spec(spec)
saved = sys.argv
sys.argv = ["main.py"]
try:
    spec.loader.exec_module(m)
except SystemExit:
    pass
finally:
    sys.argv = saved


class _Fake:
    """_boot_command 만 돌리는 최소 self."""

    def __init__(self, mode, crash=False):
        self.mode = mode
        self._crash = crash

    def _load_alert_settings(self):
        return {"crash_recover": self._crash}

    _MODE_FLAG = m.MainWindow._MODE_FLAG
    _ALERT_DEFAULTS = m.MainWindow._ALERT_DEFAULTS
    _alert_setting = m.MainWindow._alert_setting
    _boot_command = m.MainWindow._boot_command


print("=== 1. 매물감시 창은 --watch 를 실어 보낸다 (이번 버그) ===")
cmd = _Fake("watch")._boot_command()
ck("--watch 가 있다", "--watch" in cmd, cmd)
ck("--manual 은 없다", "--manual" not in cmd, cmd)

print("\n=== 2. 수동검색 창은 --manual ===")
cmd = _Fake("manual")._boot_command()
ck("--manual 이 있다", "--manual" in cmd, cmd)
ck("--watch 는 없다", "--watch" not in cmd, cmd)

print("\n=== 3. 크래시 자동복구와 함께 쓸 수 있다 ===")
cmd = _Fake("watch", crash=True)._boot_command()
ck("--watchdog 와 --watch 가 함께", "--watchdog" in cmd and "--watch" in cmd, cmd)

print("\n=== 4. 모르는 모드(옛 합본)도 --watch 로 보낸다 — 합본은 없다 ===")
cmd = _Fake("all")._boot_command()
ck("--watch 가 있다", "--watch" in cmd and "--manual" not in cmd, cmd)

bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패:", bad)
sys.stdout.flush()
os._exit(1 if bad else 0)

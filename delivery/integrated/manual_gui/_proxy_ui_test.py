"""프록시 목록 버튼 UI (네트워크 불필요).

    python _proxy_ui_test.py

프록시 관리 UI 는 '매물 감시' 탭의 [계정+프록시] 창 하나로 모았다 — 수동 탭의
중복 버튼(accountsBtn/proxyViewBtn)과 감시 탭의 별도 [프록시 목록] 버튼은
제거됐고, 창 안의 프록시 버튼 문구가 "프록시 목록 (N)" 이다.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, app_dir)
os.chdir(app_dir)

from PyQt6.QtWidgets import QApplication

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


app = QApplication.instance() or QApplication([])
import main

w = main.MainWindow()

n = len(w._collect_proxies())

ck("감시 탭 별도 프록시 버튼 제거", not hasattr(w, "autoProxyViewBtn"))
ck("수동 탭 중복 버튼 제거",
   not hasattr(w, "proxyViewBtn") and not hasattr(w, "accountsBtn"))
ck("on_proxy_view_clicked 존재", callable(getattr(w, "on_proxy_view_clicked", None)))

from PyQt6 import QtWidgets as _QW
_opened = []
_orig_exec = _QW.QDialog.exec
_QW.QDialog.exec = lambda self: (_opened.append(self), 0)[1]
try:
    w.on_accounts_btn_clicked()
finally:
    _QW.QDialog.exec = _orig_exec
_btns = {b.text(): b for d in _opened for b in d.findChildren(_QW.QPushButton)}
ck("계정+프록시 창 안 프록시 버튼 문구가 프록시 수를 반영",
   f"프록시 목록 ({n})" in _btns, str(sorted(_btns)))
ck("계정 현황·프록시 진단도 같은 창 안",
   "계정 현황" in _btns and "프록시 진단" in _btns, str(sorted(_btns)))
for d in _opened:
    d.close()

print(f"\n프록시 UI OK — 감시 탭 버튼 문구 '프록시 목록 ({n})' / 목록 다이얼로그 존재")

print("\n" + "=" * 50)
passed = sum(1 for _, c in R if c)
print(f"===== {passed}/{len(R)} PASS =====")
bad = [nm for nm, c in R if not c]
if bad:
    print("FAIL:", *bad, sep="\n  - ")
sys.exit(0 if passed == len(R) else 1)

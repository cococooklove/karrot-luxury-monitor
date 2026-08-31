"""프록시 목록 버튼 UI (네트워크 불필요).

    python _proxy_ui_test.py

프록시 관리 UI 는 '매물 감시' 탭 하나로 모았다 — 수동 탭의 중복 버튼
(accountsBtn/proxyViewBtn)은 제거됐고, _refresh_proxy_labels() 가
autoProxyViewBtn 문구를 "프록시 목록 (N)" 으로 갱신한다.
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

ck("autoProxyViewBtn 존재", hasattr(w, "autoProxyViewBtn"))
ck("수동 탭 중복 버튼 제거",
   not hasattr(w, "proxyViewBtn") and not hasattr(w, "accountsBtn"))
ck("on_proxy_view_clicked 존재", callable(getattr(w, "on_proxy_view_clicked", None)))
ck("_refresh_proxy_labels 존재", callable(getattr(w, "_refresh_proxy_labels", None)))

w._refresh_proxy_labels()
ck("자동 탭 버튼 문구가 프록시 수를 반영",
   w.autoProxyViewBtn.text() == f"프록시 목록 ({n})", w.autoProxyViewBtn.text())

print(f"\n프록시 UI OK — 감시 탭 버튼 문구 '프록시 목록 ({n})' / 목록 다이얼로그 존재")

print("\n" + "=" * 50)
passed = sum(1 for _, c in R if c)
print(f"===== {passed}/{len(R)} PASS =====")
bad = [nm for nm, c in R if not c]
if bad:
    print("FAIL:", *bad, sep="\n  - ")
sys.exit(0 if passed == len(R) else 1)

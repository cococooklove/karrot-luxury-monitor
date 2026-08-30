"""프록시 목록 버튼 UI (네트워크 불필요).

    python _proxy_ui_test.py

수동/자동 탭에는 더 이상 별도 "적용 프록시: N개" 라벨(proxyLabel/autoProxyLabel)이
없다 — _refresh_proxy_labels() 가 proxyViewBtn/autoProxyViewBtn 버튼 자체의
문구를 "프록시 목록 (N)" 으로 갱신하는 방식으로 바뀌었다(main.py:3001).
이 파일은 그 옛 라벨 존재를 assert 하다가 항상 실패했다 — 현재 모양으로 갱신.
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

ck("proxyViewBtn/autoProxyViewBtn 존재",
   hasattr(w, "proxyViewBtn") and hasattr(w, "autoProxyViewBtn"))
ck("on_proxy_view_clicked 존재", callable(getattr(w, "on_proxy_view_clicked", None)))
ck("_refresh_proxy_labels 존재", callable(getattr(w, "_refresh_proxy_labels", None)))

w._refresh_proxy_labels()
ck("수동 탭 버튼 문구가 프록시 수를 반영",
   w.proxyViewBtn.text() == f"프록시 목록 ({n})", w.proxyViewBtn.text())
ck("자동 탭 버튼 문구가 프록시 수를 반영",
   w.autoProxyViewBtn.text() == f"프록시 목록 ({n})", w.autoProxyViewBtn.text())

print(f"\n프록시 UI OK — 수동/자동 버튼 문구 '프록시 목록 ({n})' / 목록 다이얼로그 존재")

print("\n" + "=" * 50)
passed = sum(1 for _, c in R if c)
print(f"===== {passed}/{len(R)} PASS =====")
bad = [nm for nm, c in R if not c]
if bad:
    print("FAIL:", *bad, sep="\n  - ")
sys.exit(0 if passed == len(R) else 1)

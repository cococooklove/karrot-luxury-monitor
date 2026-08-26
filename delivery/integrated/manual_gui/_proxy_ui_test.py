import main
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
w = main.MainWindow()
n = len(w._collect_proxies())
assert hasattr(w, "proxyLabel") and hasattr(w, "autoProxyLabel"), "프록시 라벨 없음"
assert hasattr(w, "on_proxy_view_clicked"), "프록시 뷰 없음"
assert w.proxyLabel.text() == f"적용 프록시: {n}개", w.proxyLabel.text()
assert w.autoProxyLabel.text() == f"적용 프록시: {n}개"
print(f"프록시 UI OK — 수동/자동 라벨 '적용 프록시: {n}개' / 목록 다이얼로그 존재")

import main
from PyQt6.QtWidgets import QApplication
from daangn.task import CrawlTask
from daangn.auto_monitor import AutoMonitor, load_conditions_from_excel

app = QApplication([])
w = main.MainWindow()
assert w.tabs.count() == 2
# 자동 신규 위젯
assert all(hasattr(w, x) for x in ("autoExcelBtn", "autoCondLabel", "auto_conditions"))
assert hasattr(w, "on_auto_excel_clicked") and hasattr(w, "_collect_proxies")
# AutoMonitor cfg 다중조건/프록시 경로 구성 (인스턴스화만, 실행X)
m = AutoMonitor(w, {"conditions": [{"keyword": "샤넬"}], "proxies": ["http://a:1"],
                    "out_json": "./OUT.json", "db_path": "/tmp/_t.db", "scope": "regions",
                    "regions": []})
p0, nxt = m._proxy_cycle()
assert p0 == "http://a:1"
print("탭2 / 엑셀버튼·조건·프록시 위젯 OK / AutoMonitor 다중조건+프록시 구성 OK")
print("proxy_cycle:", p0)

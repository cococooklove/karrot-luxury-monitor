import main
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
w = main.MainWindow()
w.resize(1200, 800)
w.show()
app.processEvents()

def info(name, wd):
    try:
        g = wd.geometry()
        print(f"  {name}: visible={wd.isVisible()} geo=({g.x()},{g.y()},{g.width()}x{g.height()}) parent={type(wd.parent()).__name__}")
    except Exception as e:
        print(f"  {name}: ERR {e}")

print("탭:", [w.tabs.tabText(i) for i in range(w.tabs.count())])
print("현재 탭 index:", w.tabs.currentIndex())
print("[수동 추가위젯]")
for n in ("extraEdit", "excludeEdit", "adaptiveCheck", "tokenRefreshCheck",
          "accountsBtn", "proxyLabel", "proxyViewBtn"):
    info(n, getattr(w, n))
print("gridLayout_2 rowCount:", w.ui.gridLayout_2.rowCount(),
      "itemCount:", w.ui.gridLayout_2.count())
# 수동 탭 위젯의 최소/실제 크기
mt = w.tabs.widget(0)
print("수동탭 sizeHint:", mt.sizeHint(), "size:", mt.size())
print("[자동 위젯]")
for n in ("autoKeyword", "autoStartBtn", "autoProxyLabel"):
    info(n, getattr(w, n))

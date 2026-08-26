import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
import main
w = main.MainWindow()
w.resize(1180, 820)
w.show()
for _ in range(10):
    app.processEvents(); time.sleep(0.05)
# 수동 탭
w.tabs.setCurrentIndex(0)
for _ in range(6): app.processEvents(); time.sleep(0.05)
w.grab().save("/tmp/ui_manual.png")
# 자동 탭
w.tabs.setCurrentIndex(1)
for _ in range(6): app.processEvents(); time.sleep(0.05)
w.grab().save("/tmp/ui_auto.png")
print("saved /tmp/ui_manual.png /tmp/ui_auto.png")

import os, sys, time, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
import main
w = main.MainWindow()
errs = []
w.alert = lambda *a, **k: errs.append(("alert", a[0] if a else ""))
w.autoKeyword.setText("구찌")
w.autoRestMin.setValue(1); w.autoRestMax.setValue(2)
logs = []
try:
    w.on_auto_start_clicked()          # ← 시작 버튼
    if w.auto_monitor:
        w.auto_monitor.log.connect(lambda m: logs.append(m))
    for _ in range(120):               # 12초 이벤트 펌프
        app.processEvents(); time.sleep(0.1)
    if w.auto_monitor:
        w.auto_monitor.stop(); w.auto_monitor.wait(8000)
    print("시작 예외: 없음")
except Exception:
    print("시작 예외 발생:\n" + traceback.format_exc())
print("alert:", errs)
print("로그(초):")
for l in logs[:15]:
    print("   ", l.replace(chr(10), " ")[:80])

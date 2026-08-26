import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
import main
from daangn.task import CrawlTask
w = main.MainWindow()
before = w.products_model.rowCount()
w.controller.start_task([CrawlTask(("역삼동","역삼동-6035"),"구찌",True,None,None)])
# 스레드 완료까지 이벤트 펌프
t0=time.time()
while w.controller.is_task_running() and time.time()-t0<60:
    app.processEvents(); time.sleep(0.05)
# 완료 후 잔여 시그널(new_products) 전달 위해 추가 펌프
for _ in range(40):
    app.processEvents(); time.sleep(0.02)
print("RESULT 모델행:", before, "->", w.products_model.rowCount())
print("현재데이터:", len(w.controller.get_current_data()), "건")

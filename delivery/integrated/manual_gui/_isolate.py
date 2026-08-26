import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt
app = QApplication.instance() or QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import main
from daangn.task import CrawlTask
from daangn import api
w = main.MainWindow()

# 0) api 직접 (프록시)
prox = w._collect_proxies()[0]
prds = api.get_products("역삼동-6035","역삼동","구찌",True,None,None,proxy=prox)
print("api.get_products 직접:", len(prds), "건")

# 1) controller.start_task 직접 (스레드→모델)
def pump(cond, t=90):
    s=time.time()
    while not cond() and time.time()-s<t: app.processEvents(); time.sleep(0.1)
    return cond()
before = w.products_model.rowCount()
task = CrawlTask(("역삼동","역삼동-6035"),"구찌",True,None,None)
w.controller.start_task([task])
print("task 시작됨:", w.controller.is_task_running())
pump(lambda: not w.controller.is_task_running(), 25)
print("task 끝. 모델 행:", before, "→", w.products_model.rowCount())

# 2) 핸들러 조기반환 진단
w.ui.keywordEdit.setText("구찌")
found=[ch for ch in w.all_last_child if ch.data(0, Qt.ItemDataRole.UserRole)=="역삼동-6035"]
print("역삼동 트리아이템:", len(found))
if found:
    found[0].setCheckState(0, Qt.CheckState.Checked)
    sel=[c for c in w.all_last_child if c.checkState(0)==Qt.CheckState.Checked]
    print("체크된 지역 수:", len(sel))
print("ask('x') 반환:", w.ask("x"))

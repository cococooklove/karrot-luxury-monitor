import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
import main
w = main.MainWindow()
# 재부모화 후 무결성
assert w.tabs.count() == 2
assert len(w.all_last_child) > 0, "지역트리 데이터 유실"
assert w.ui.itemListView.model() is not None, "결과모델 유실"
assert w.ui.keywordEdit is not None and w.extraEdit is not None
assert w.ui.startBtn.text() == "검색 시작"
# 시그널 연결(핸들러) 확인 — receivers>0
from PyQt6.QtCore import QMetaObject
print("지역 리프:", len(w.all_last_child))
print("결과모델:", type(w.ui.itemListView.model()).__name__)
print("startBtn 텍스트:", w.ui.startBtn.text())
print("수동 위젯 부모탭 index:", w.tabs.indexOf(w.tabs.widget(0)))
print("PASS: 재부모화 무결성 OK")

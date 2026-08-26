import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
app = QApplication.instance() or QApplication([])
import main
w = main.MainWindow()
assert hasattr(w, "autoAreaTree"), "자동 지역트리 없음"
leaves = w.auto_area_leaves
print("자동 지역(구) 총:", len(leaves))
# 강남구 체크
gn = [it for it in leaves if it.data(0, Qt.ItemDataRole.UserRole) == "강남구-381"]
assert gn, "강남구 없음"
gn[0].setCheckState(0, Qt.CheckState.Checked)
# 서초구도
sc = [it for it in leaves if it.data(0, Qt.ItemDataRole.UserRole) and it.text(0) == "서초구"]
if sc: sc[0].setCheckState(0, Qt.CheckState.Checked)
sel = w._selected_auto_regions()
print("선택된 구:", sel)
assert "강남구-381" in sel
print("PASS: 자동 지역선택 동작")

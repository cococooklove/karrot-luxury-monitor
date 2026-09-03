import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication, QLineEdit, QPushButton
from PyQt6.QtCore import Qt
app = QApplication.instance() or QApplication([])
import main
w = main.MainWindow()

# 자동 트리 패널: 검색 필터
leaves = w.auto_area_leaves
# 패널 내부 search/버튼 찾기 (autoAreaTree의 형제)
panel = w.autoAreaTree.parent()
search = panel.findChild(QLineEdit)
btns = panel.findChildren(QPushButton)
print("검색박스:", search is not None, "버튼:", [b.text() for b in btns])
# "강남" 필터 → 강남구만 보이고 나머지 숨김
search.setText("강남")
visible = [l.text(0) for l in leaves if not l.isHidden()]
print("'강남' 필터 결과:", visible[:5], f"(총 {len(visible)})")
assert all("강남" in v for v in visible) and len(visible) >= 1
# 전체선택(필터된 것만)
[b for b in btns if b.text() == "전체 선택"][0].click()
sel = w._selected_auto_regions()
print("전체선택(강남 필터) → 선택:", sel)
# 선택값은 '동-id' 꼴이라 구 이름이 없다 — 필터에 보이던 동만 골랐는지 본다.
# (지역 트리가 접힌 고급 패널 뒤에 있던 동안은 전체 선택이 0건이라 이 검사가
# 비어 있는 채로 통과했다. 조건 탭에 펼쳐 놓은 뒤로 실제로 고른다.)
_dongs = [v.split()[-1] for v in visible]
assert len(sel) == len(visible) >= 1, (len(sel), len(visible))
assert all(any(s.startswith(d) for d in _dongs) for s in sel)
# 해제
[b for b in btns if b.text() == "전체 해제"][0].click()
print("전체해제 후 선택:", len(w._selected_auto_regions()))
print("PASS: 지역검색+전체선택/해제 동작")

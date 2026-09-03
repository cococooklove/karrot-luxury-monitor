"""조건 그리드 위젯 + 조건 탭 배선 (offscreen PyQt6).

    QT_QPA_PLATFORM=offscreen python rule_grid_gui_test.py

엑셀 파일 대신 화면 표에 조건을 바로 적는다. 표는 엑셀처럼 굴어야 한다 —
붙여넣기·Delete·끝줄 자동 추가·엑셀 행 번호. 적용은 [조건 적용] 한 버튼이고
엑셀은 표를 채우는 보조 경로일 뿐이다.
"""
import json
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, app_dir)
os.chdir(app_dir)

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


from PyQt6 import QtCore, QtWidgets
_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
import main as m
from daangn_ext.rule_grid import RULE_COLS

print("=== A. RuleGrid 위젯 ===")
g = m.RuleGrid()
ck("열은 조건표 열 그대로",
   [g.horizontalHeaderItem(i).text() for i in range(g.columnCount())] == RULE_COLS)
ck("빈 표도 적을 줄이 있다", g.rowCount() >= m.RuleGrid.MIN_ROWS)
ck("행 라벨은 엑셀 번호(머리글=1행)", g.verticalHeaderItem(0).text() == "2")
ck("빈 표 → 빈 셀 목록", g.cells() == [])

g.set_cells([["루이비통", "오버 더 문", "500,000", "1,500,000", ""],
             ["", "반둘리에 50", "", "2,000,000", ""]])
ck("채운 뒤 끝에 빈 줄이 남아 이어 적을 수 있다",
   g.rowCount() >= 3 and g.cells() == [
       ["루이비통", "오버 더 문", "500,000", "1,500,000", ""],
       ["", "반둘리에 50", "", "2,000,000", ""]], str(g.cells()))

edits = []
g.edited.connect(lambda: edits.append(1))
g.setCurrentCell(2, 0)
g.paste_text("보테가베네타\t카세트백\t1000000\t2500000\n샤넬\t클래식\n")
ck("붙여넣기는 현재 칸에서 시작해 여러 줄을 채운다",
   g.cells()[2] == ["보테가베네타", "카세트백", "1000000", "2500000", ""]
   and g.cells()[3][:2] == ["샤넬", "클래식"], str(g.cells()))
ck("붙여넣기 뒤에도 끝에 빈 줄", g.rowCount() >= 5)
ck("편집 신호", len(edits) >= 1)

n0 = g.rowCount()
g.setCurrentCell(n0 - 1, 1)
g.item(n0 - 1, 1).setText("마지막 줄")
ck("끝 줄에 적으면 새 빈 줄이 붙는다", g.rowCount() == n0 + 1, f"{n0}→{g.rowCount()}")

g.setRangeSelected(QtWidgets.QTableWidgetSelectionRange(0, 0, 0, 4), True)
g.clear_selected()
ck("Delete 로 선택 칸 비움 — 줄은 남는다",
   g.cells()[0] == ["", "", "", "", ""] and g.cells()[1][1] == "반둘리에 50", str(g.cells()[:2]))

g.mark_errors(["4행 '보테가베네타 카세트백': 최소가격이 최대가격보다 큽니다 — 건너뜀"])
ck("오류 행은 표에서 같은 번호 줄이 표시된다",
   g.error_rows() == {2}, str(g.error_rows()))
g.mark_errors([])
ck("오류 없으면 표시 지움", g.error_rows() == set())

g.setCurrentCell(1, 0)
g.remove_selected_rows()
ck("선택 줄 삭제", g.cells()[1][0] == "보테가베네타", str(g.cells()[:2]))
g.add_row()
ck("줄 추가는 현재 줄 아래에", g.rowCount() >= 6)

print("=== B. 조건 탭 배선 ===")
_tmp = tempfile.mkdtemp()
_rules = os.path.join(_tmp, "alert_rules.json")
with open(_rules, "w", encoding="utf-8") as f:
    json.dump({"rules": [{"keyword": "루이비통 오버 더 문", "brand": "루이비통",
                          "product": "오버 더 문", "min": 500000, "max": 1500000,
                          "exclude": ["레플리카"]}],
               "applied_at": 1}, f, ensure_ascii=False)
m.ALERT_RULES_FILE = _rules
_win = None
try:
    _win = m.MainWindow()
except Exception as e:
    ck("MainWindow 생성", False, f"{type(e).__name__}: {str(e)[:80]}")
if _win is not None:
    ck("조건 탭에 그리드가 있다",
       isinstance(getattr(_win, "rulesGrid", None), m.RuleGrid)
       and _win.rulesGrid in _win.condBox.findChildren(QtWidgets.QWidget))
    ck("시작 시 적용 중인 조건이 표에 들어온다",
       _win.rulesGrid.cells()[:1] == [["루이비통", "오버 더 문", "500,000", "1,500,000", "레플리카"]],
       str(_win.rulesGrid.cells()[:1]))
    ck("주 버튼은 [조건 적용]",
       _win.rulesApplyBtn.text().startswith("조건 적용")
       and _win.rulesApplyBtn.objectName() == "startBtn"
       and callable(getattr(_win, "on_rules_apply", None)))
    ck("엑셀은 표를 채우는 보조 버튼",
       _win.rulesImportBtn.objectName() == "linkBtn"
       and callable(getattr(_win, "on_rules_import_excel", None)))
    ck("엑셀 열기·다시 읽기·엑셀 다이얼로그 제거",
       not any(hasattr(_win, a) for a in (
           "alertRulesBtn", "rulesOpenBtn", "rulesReloadBtn",
           "on_alert_rules_excel", "on_rules_open_excel", "on_rules_reload_excel",
           "RULE_SAMPLE")))
    ck("행 추가·삭제 버튼", hasattr(_win, "rulesAddRowBtn") and hasattr(_win, "rulesDelRowBtn"))
    ck("처음엔 미수정", not _win._rules_dirty
       and "수정" not in _win.rulesApplyBtn.text())
    _win.rulesGrid.item(0, 1).setText("오버 더 문 정품")
    ck("표를 고치면 미적용 표시",
       _win._rules_dirty and "수정" in _win.rulesApplyBtn.text()
       and "미적용" in _win.rulesSummary.text(),
       _win.rulesSummary.text())
    # 파일이 밖에서 바뀌어도 고치는 중인 표는 덮어쓰지 않는다.
    _win._refresh_rules_view()
    ck("수정 중엔 파일이 표를 덮지 않는다",
       _win.rulesGrid.cells()[0][1] == "오버 더 문 정품")
    # 적용: 확인·등록은 막고 저장 경로만 본다.
    _win._confirm_rules = lambda *a, **k: True
    _win._register_rule_brands = lambda *a, **k: None
    QtWidgets.QMessageBox.information = staticmethod(lambda *a, **k: None)
    QtWidgets.QMessageBox.warning = staticmethod(lambda *a, **k: None)
    _win.rulesGrid.setCurrentCell(1, 0)
    _win.rulesGrid.paste_text("샤넬\t클래식\t3000000\t1000000")   # 최소>최대 → 오류
    _win.on_rules_apply()
    with open(_rules, encoding="utf-8") as f:
        saved = json.load(f)
    ck("적용하면 표 내용이 조건표 파일이 된다(오류 줄은 빠짐)",
       [r["keyword"] for r in saved["rules"]] == ["루이비통 오버 더 문 정품"],
       str([r["keyword"] for r in saved["rules"]]))
    ck("오류 줄은 표에 표시", _win.rulesGrid.error_rows() == {1}, str(_win.rulesGrid.error_rows()))
    ck("적용 뒤 미수정", not _win._rules_dirty and "수정" not in _win.rulesApplyBtn.text())
    ck("적용 뒤에도 표는 남는다(오류 줄 포함)",
       _win.rulesGrid.cells()[1][0] == "샤넬")
    ck("source 는 파일 경로가 아니다", not saved.get("source"))
    # 빈 표 적용은 조건 삭제가 아니라 거절 — 삭제는 전체 삭제 버튼이 한다.
    _win.rulesGrid.set_cells([])
    _win.on_rules_apply()
    with open(_rules, encoding="utf-8") as f:
        ck("빈 표 적용은 파일을 건드리지 않는다",
           len(json.load(f)["rules"]) == 1)

n_ok = sum(1 for _, c in R if c)
print(f"\n{n_ok}/{len(R)} PASS")
sys.exit(0 if n_ok == len(R) else 1)

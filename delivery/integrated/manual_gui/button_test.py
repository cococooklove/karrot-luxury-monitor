"""모든 버튼 클릭 단위 테스트 — 블로킹 다이얼로그 몽키패치 후 핸들러 실행."""
import os, sys, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog, QDialog
from PyQt6.QtCore import Qt

R = []
def ck(n, c, e=""):
    R.append((n, bool(c))); print(f"  [{'PASS' if c else 'FAIL'}] {n}  {e}")

app = QApplication.instance() or QApplication([])

# ── 블로킹 다이얼로그 몽키패치 ──
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.critical = staticmethod(lambda *a, **k: None)
_saved = {}
QDialog.exec = lambda self: (_saved.__setitem__("dlg", self), 0)[1]   # 즉시 반환(빌드만)

import main
w = main.MainWindow()
w.alert = lambda *a, **k: None          # 알림 무음
PROXIES = w._collect_proxies()

def pump(cond, timeout=90):
    t0 = time.time()
    while not cond() and time.time() - t0 < timeout:
        app.processEvents(); time.sleep(0.1)
    return cond()

print("=== 수동 버튼 ===")
# 1) startBtn: 지역 1개 체크 + 키워드 → 검색 → 결과 모델 채움
w.ui.keywordEdit.setText("구찌")
w.adaptiveCheck.setChecked(False)
# 트리에서 데이터 많은 지역(역삼동-6035) 우선 체크
region_item = None
for ch in w.all_last_child:
    if ch.data(0, Qt.ItemDataRole.UserRole) == "역삼동-6035":
        ch.setCheckState(0, Qt.CheckState.Checked); region_item = ch; break
if region_item is None:                     # 폴백: 아무 유효 지역
    for ch in w.all_last_child:
        if ch.data(0, Qt.ItemDataRole.UserRole):
            ch.setCheckState(0, Qt.CheckState.Checked); region_item = ch; break
ck("지역 선택 가능", region_item is not None,
   region_item.data(0, Qt.ItemDataRole.UserRole) if region_item else "")
before = w.products_model.rowCount()
w.on_start_btn_clicked()                 # ← startBtn 클릭
started = pump(lambda: w.controller.is_task_running(), 10)
done = pump(lambda: not w.controller.is_task_running(), 90)
after = w.products_model.rowCount()
ck("startBtn 검색→결과 채움", done and after > before, f"{before}→{after}행")

# 2) saveToExcelBtn: 결과 있으면 엑셀 저장
xlsx_out = tempfile.mktemp(suffix=".xlsx")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (xlsx_out, ""))
try:
    w.save_to_excel()                    # ← 엑셀 저장 클릭
    saved = pump(lambda: os.path.exists(xlsx_out), 30)
    ck("saveToExcelBtn 엑셀 저장", saved, xlsx_out if saved else "미생성")
except Exception as e:
    ck("saveToExcelBtn", False, str(e)[:50])

# 3) accountsBtn 다이얼로그 빌드 (exec 몽키패치)
try:
    w.on_accounts_btn_clicked(); ck("accountsBtn 다이얼로그", True)
except Exception as e:
    ck("accountsBtn 다이얼로그", False, str(e)[:50])
# 4) proxyViewBtn 다이얼로그
try:
    w.on_proxy_view_clicked(); ck("proxyViewBtn 다이얼로그", True)
except Exception as e:
    ck("proxyViewBtn 다이얼로그", False, str(e)[:50])
# 5) 매물 상세 (첫 행 선택) — 이미지 다운로드 제외 로직만
try:
    if w.products_model.rowCount() > 0:
        prds = w.controller.get_current_data()
        w.load_detail(prds[0])           # ← 상세 로드
        ck("매물 상세뷰 로드", True, prds[0].name[:20])
    else:
        ck("매물 상세뷰 로드", False, "결과 없음")
except Exception as e:
    ck("매물 상세뷰 로드", False, str(e)[:50])

print("=== 자동 버튼 ===")
# 6) autoExcelBtn: 파일다이얼로그 패치 → 조건 로드
from openpyxl import Workbook
cxls = tempfile.mktemp(suffix=".xlsx"); wb = Workbook(); ws = wb.active
ws.append(["대분류","키워드","제외키워드","최소금액"]); ws.append(["가방","구찌","레플",100000]); wb.save(cxls)
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (cxls, ""))
try:
    w.on_auto_excel_clicked()
    ck("autoExcelBtn 조건로드", len(w.auto_conditions) == 1, f"{len(w.auto_conditions)}조건")
except Exception as e:
    ck("autoExcelBtn", False, str(e)[:50])
# 7) autoStartBtn: 시작→정지
w.autoKeyword.setText("구찌")
w.auto_conditions = []          # 단일조건으로
w.autoRestMin.setValue(1); w.autoRestMax.setValue(2)
try:
    w.on_auto_start_clicked()            # ← 시작
    run = pump(lambda: w.auto_monitor and w.auto_monitor.isRunning(), 5)
    time.sleep(8)
    w.on_auto_start_clicked()            # ← 정지(토글)
    stopped = pump(lambda: not (w.auto_monitor and w.auto_monitor.isRunning()), 15)
    ck("autoStartBtn 시작/정지", run and stopped, "시작→정지 OK")
except Exception as e:
    ck("autoStartBtn", False, str(e)[:50])

print("\n===== 결과 =====")
ok = sum(1 for _, c in R if c); print(f"{ok}/{len(R)} PASS")
for n, c in R:
    if not c: print(f"  실패: {n}")

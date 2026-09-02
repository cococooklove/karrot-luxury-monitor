"""버튼 배선 테스트 — 핸들러가 붙어 있고, 다이얼로그가 실제로 열리는가.

    python button_test.py

옛 버전은 [검색] 을 눌러 진짜 당근에서 매물을 받아오고 자동 모니터를 30초
돌렸다. 자격증명·프록시가 없는 환경에서는 영원히 빨갛고, 있어도 네트워크 상태에
따라 흔들린다. 실수집 검증은 nationwide_test.py 같은 라이브 스크립트가 따로
한다. 여기서는 네트워크 없이 확인할 수 있는 것만 본다 — 버튼이 핸들러에
연결돼 있는가, 다이얼로그가 크래시 없이 서는가, 폼 값이 작업 객체로 옮겨지는가.
(자동 모니터 탭 버튼(autoStartBtn 등)은 탭째 없어졌으므로 여기서 뺐다.)
"""
import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, app_dir)
os.chdir(app_dir)

from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


app = QApplication.instance() or QApplication([])

# ── 블로킹 다이얼로그 몽키패치 — 열되 멈추지 않는다 ──
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.critical = staticmethod(lambda *a, **k: None)
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
_opened = []
QDialog.exec = lambda self: (_opened.append(self), 0)[1]
# 모달(exec)뿐 아니라 비모달(show)로 뜨는 창도 있다 — 둘 다 잡는다.
_orig_show = QDialog.show


def _rec_show(self):
    _opened.append(self)
    _orig_show(self)


QDialog.show = _rec_show

import main
from daangn.task import CrawlTask

w = main.MainWindow()
w.alert = lambda *a, **k: None          # 알림 무음

print("=== 버튼 → 핸들러 연결 ===")
# receivers() 가 0 이면 눌러도 아무 일이 없다 — 런타임에만 드러나는 고장이다.
for attr in ("alertAddBtn", "alertRefreshBtn",
             "alertDelBtn", "alertDelAllBtn", "alertPollBtn", "alertPollAllBtn",
             "alertBulkAllBtn", "alertCoverageBtn", "alertFleetBtn",
             "alertTgTestBtn", "watchToggleBtn", "alertRulesBtn", "autoNotifyBtn",
             "autoAccountsBtn", "autoProxyViewBtn"):
    b = getattr(w, attr, None)
    ck(f"{attr} 연결됨", b is not None and b.receivers(b.clicked) > 0)
ck("검색 버튼 연결됨", w.ui.startBtn.receivers(w.ui.startBtn.clicked) > 0)
for key in main.MainWindow.CHIP_TARGETS:
    c = w._chips[key]
    ck(f"상태칩 {key} 연결됨", c.receivers(c.clicked) > 0)

print("\n=== 다이얼로그가 선다(자격증명 없이도) ===")
for name, fn in (("계정·프록시", "on_accounts_btn_clicked"),
                 ("프록시 목록", "on_proxy_view_clicked"),
                 ("알림 설정", "on_auto_notify_clicked"),
                 ("계정 현황", "on_alert_fleet")):
    _opened.clear()
    try:
        getattr(w, fn)()
        ck(f"{name} 다이얼로그", bool(_opened), f"{fn} → {len(_opened)}개")
    except Exception as e:
        ck(f"{name} 다이얼로그", False, f"{type(e).__name__}: {str(e)[:60]}")
# 열어 둔 자동갱신 타이머가 뒤에 남지 않게 닫는다.
for d in _opened:
    try:
        d.close()
    except Exception:
        pass

print("\n=== 조건표 엑셀 로드: 취소해도 안 죽는다 ===")
try:
    w.on_alert_rules_excel()           # getOpenFileName 이 "" → 취소 경로
    ck("조건표 엑셀 취소 처리", True)
except Exception as e:
    ck("조건표 엑셀 취소 처리", False, f"{type(e).__name__}: {str(e)[:60]}")

print("\n=== 검색폼 → CrawlTask ===")
w.ui.keywordEdit.setText("샤넬")
w.extraEdit.setText("정품")
w.excludeEdit.setText("레플 미러")
w.ui.minimumEdit.setText("500000")
w.ui.maximumEdit.setText("3000000")
extra = [x for x in re.split(r"[,\s]+", w.extraEdit.text().strip()) if x]
exclude = [x for x in re.split(r"[,\s]+", w.excludeEdit.text().strip()) if x]
task = CrawlTask(("강남구", "강남구-381"), w.ui.keywordEdit.text(), True,
                 500000, 3000000, extra_keywords=extra, exclude_keywords=exclude)
ck("추가·제외 키워드 분해",
   task.extra_keywords == ["정품"] and task.exclude_keywords == ["레플", "미러"],
   f"{task.extra_keywords} / {task.exclude_keywords}")
ck("가격 범위 전달", task.minimum == 500000 and task.maximum == 3000000)

print("\n=== 지역 트리에서 동을 고를 수 있다 ===")
picked = next((c for c in w.all_last_child
               if c.data(0, main.QtCore.Qt.ItemDataRole.UserRole)), None)
ck("지역 트리 채워짐", picked is not None,
   picked.data(0, main.QtCore.Qt.ItemDataRole.UserRole) if picked else "비어 있음")

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

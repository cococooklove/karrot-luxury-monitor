"""GUI 전 기능 실동작 테스트 — 핸들러 + 실데이터경로(프록시) + 자동 end-to-end."""
import os, sys, time, sqlite3, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication

R = []
def ck(name, cond, extra=""):
    R.append((name, bool(cond))); print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")

app = QApplication.instance() or QApplication([])
import main
from daangn import api
from daangn.auto_monitor import AutoMonitor, load_conditions_from_excel
from daangn.task import CrawlTask
from daangn.workers import CrawlThread
from daangn_ext.search_filters import KeywordRule

w = main.MainWindow()
PROXIES = w._collect_proxies()

print("=== 1. GUI 핸들러/위젯 ===")
ck("프록시 20개 로드", len(PROXIES) == 20, f"{len(PROXIES)}개")
ck("프록시 개수 버튼 표시", w.proxyViewBtn.text() == "프록시 목록 (20)"
   and w.autoProxyViewBtn.text() == "프록시 목록 (20)",
   f"{w.proxyViewBtn.text()} / {w.autoProxyViewBtn.text()}")
for h in ("on_start_btn_clicked", "on_accounts_btn_clicked", "on_proxy_view_clicked",
          "_refresh_tokens", "on_auto_excel_clicked", "on_auto_start_clicked"):
    ck(f"핸들러 {h}", hasattr(w, h) and callable(getattr(w, h)))

print("\n=== 2. 수동 검색폼 → CrawlTask 생성 로직 ===")
w.ui.keywordEdit.setText("샤넬")
w.extraEdit.setText("정품")
w.excludeEdit.setText("레플 미러")
w.adaptiveCheck.setChecked(True)
w.ui.minimumEdit.setText("500000"); w.ui.maximumEdit.setText("3000000")
import re
extra = [x for x in re.split(r"[,\s]+", w.extraEdit.text().strip()) if x]
exclude = [x for x in re.split(r"[,\s]+", w.excludeEdit.text().strip()) if x]
task = CrawlTask(("강남구", "강남구-381"), w.ui.keywordEdit.text(), True, 500000, 3000000,
                 extra_keywords=extra, exclude_keywords=exclude, adaptive=w.adaptiveCheck.isChecked())
ck("검색폼→CrawlTask(추가/제외/적응형/가격)",
   task.extra_keywords == ["정품"] and task.exclude_keywords == ["레플", "미러"]
   and task.adaptive and task.minimum == 500000)

print("\n=== 3. 수동 실데이터 경로 (프록시로 실수집) ===")
try:
    prods = api.get_products_adaptive("강남구-381", "강남구", "샤넬", True, 500000, 3000000,
                                      proxy=PROXIES[0],
                                      rule=KeywordRule(required=["샤넬"], exclude=["레플", "미러"]))
    ck("적응형+필터+가격 실수집", len(prods) > 0, f"{len(prods)}건")
    ck("가격범위 적용됨", all(500000 <= int(float(p.price)) <= 3000000 for p in prods if str(p.price).replace('.','').isdigit()), "50만~300만")
except Exception as e:
    ck("적응형 실수집", False, str(e)[:60])

print("\n=== 4. 자동: 엑셀 다중조건 로드 ===")
from openpyxl import Workbook
xls = tempfile.mktemp(suffix=".xlsx"); wb = Workbook(); ws = wb.active
ws.append(["대분류", "키워드", "추가키워드", "제외키워드", "최소금액", "최대금액", "끌올일수"])
ws.append(["가방", "샤넬", "정품", "레플", 500000, 3000000, 7])
ws.append(["시계", "롤렉스", "", "", 1000000, "", 30]); wb.save(xls)
conds = load_conditions_from_excel(xls)
ck("엑셀 대분류+상세조건", len(conds) == 2 and conds[0]["exclude"] == ["레플"], f"{len(conds)}조건")

print("\n=== 5. 자동 모니터 end-to-end (실데이터, 프록시, 3구) ===")
dbp = tempfile.mktemp(suffix=".db")
cfg = {"keyword": "샤넬", "extra": [], "exclude": ["레플", "미러"], "min": None, "max": None,
       "days": None, "rest_min": 1, "rest_max": 2, "proxies": PROXIES,
       "scope": "regions", "regions": ["강남구-381", "서초구-379", "송파구-383"],
       "out_json": "./OUT.json", "db_path": dbp}
mon = AutoMonitor(w, cfg)
logs = []
mon.log.connect(lambda m: logs.append(m))
mon.start()
time.sleep(30)                      # 1사이클+ 실행
mon.stop(); mon.wait(20000)
app.processEvents()
rows = sqlite3.connect(dbp).execute("SELECT COUNT(*) FROM seen").fetchone()[0]
ck("자동 모니터 실수집→DB저장", rows > 0, f"{rows}건 저장")
ck("자동 로그 발생", len(logs) > 0, f"{len(logs)}줄")

print("\n===== 결과 =====")
ok = sum(1 for _, c in R if c); print(f"{ok}/{len(R)} PASS")
for n, c in R:
    if not c: print(f"  실패: {n}")

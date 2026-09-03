"""창이 조립되는가 + 스윕 엔진 cfg 가 서는가 (네트워크 불필요).

    python _construct_test.py

가장 값싼 회귀 그물이다 — import 만 하는 테스트는 위젯 배선이 끊긴 것을 못 잡고,
여기가 빨개지면 앱이 아예 안 뜬다. 옛 버전은 탭 2개와 없어진 자동 모니터 탭
위젯(autoCondLabel·auto_conditions)을 확인해서 오래 빨간 채로 있었다.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, app_dir)
os.chdir(app_dir)

from PyQt6.QtWidgets import QApplication

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


import main
from daangn.auto_monitor import AutoMonitor

app = QApplication.instance() or QApplication([])
w = main.MainWindow()

titles = [w.tabs.tabText(i) for i in range(w.tabs.count())]
# 3탭 합본 모드는 없앴다 — 합본 창은 수확·폴링·라우터를 같이 소유해 따로 띄운
# 매물 감시 창과 같은 keyword_routes.json 을 놓고 다툰다. 인자가 없으면 매물 감시다.
ck("기본은 매물 감시 4탭", w.tabs.count() == 4, str(titles))
ck("탭 이름", titles == ["조건", "결과", "에뮬레이터", "설정"], str(titles))
_wm = main.MainWindow(mode="manual")
_mt = [_wm.tabs.tabText(i) for i in range(_wm.tabs.count())]
ck("수동 검색은 제 모드로만 뜬다", _mt == ["수동 검색"], str(_mt))
# 자동 모니터 탭은 없앴다 — 엔진은 남기고 UI 만 지웠으므로 그 탭 위젯은 없어야 한다.
ck("자동 모니터 탭 위젯 제거",
   not any(hasattr(w, x) for x in ("autoCondLabel", "auto_conditions",
                                   "autoStartBtn", "autoLog")))
# 스윕 설정은 조건 탭(지역)·설정 탭(알림)으로 이사했다.
ck("스윕 설정 위젯 존재",
   all(hasattr(w, x) for x in ("notifyToken", "autoAreaTree", "autoRestMin")))
# 조건은 '매물 감시' 탭의 표에 바로 적는다. 엑셀은 표를 채우는 보조 버튼 하나.
ck("조건 적용·엑셀 불러오기 배선",
   callable(getattr(w, "on_rules_apply", None))
   and callable(getattr(w, "on_rules_import_excel", None)))
ck("고급 패널에 엑셀 버튼 없음", not hasattr(w, "autoExcelBtn"))
ck("프록시 수집 배선", callable(getattr(w, "_collect_proxies", None)))
ck("스윕 cfg 조립 배선",
   callable(getattr(w, "_auto_cfg_base", None))
   and callable(getattr(w, "_sweep_cfg", None)))

# 엔진: 다중조건 + 프록시 cfg 로 인스턴스화(실행은 안 한다)
m = AutoMonitor(w, {"conditions": [{"keyword": "샤넬"}],
                    "proxies": ["http://a:1", "http://b:2"],
                    "out_json": "./OUT.json", "db_path": "/tmp/_construct_t.db",
                    "scope": "regions", "regions": []})
p0, nxt = m._proxy_cycle()
ck("프록시 로테이션", p0 == "http://a:1" and nxt() == "http://b:2", str(p0))
ck("프록시 없으면 None", AutoMonitor(
    w, {"out_json": "./OUT.json", "db_path": "/tmp/_construct_t2.db",
        "scope": "regions", "regions": []})._proxy_cycle()[0] is None)

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

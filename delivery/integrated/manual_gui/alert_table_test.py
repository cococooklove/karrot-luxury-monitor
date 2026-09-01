"""엑셀로 넣은 조건이 표에 보이는가.

클라 보고: "자동에서 엑셀을 올리면 리스트가 보여야 하는데 안 보임."

원인: 표를 **서버 등록 목록 + 스윕 대기열** 둘로만 그렸다. 엑셀로 넣은 조건은
등록이 끝나는 즉시 라우터에 들어오지만, 서버 목록 조회는 토큰이 없으면 실패한다.
그러면 `data=None` 이고 대기열도 비어 있어 표를 통째로 안 그리고 로그 한 줄만
남겼다 — 사용자에게는 "올렸는데 아무것도 안 뜬다"로 보였다.

라우터는 **항상 있는 진실**이다. 셋을 합쳐 그린다.

실행: python alert_table_test.py
"""
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


try:
    from PyQt6 import QtWidgets
except Exception as e:
    print(f"[SKIP] PyQt6 없음 ({type(e).__name__})")
    raise SystemExit(0)

import importlib.util

spec = importlib.util.spec_from_file_location("_m", "main.py")
m = importlib.util.module_from_spec(spec)
saved = sys.argv
sys.argv = ["main.py"]
try:
    spec.loader.exec_module(m)
except SystemExit:
    pass
finally:
    sys.argv = saved

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _Fake:
    """_alert_populate 만 돌리는 최소 self."""

    def __init__(self, routes, entries):
        self._routes = routes
        self._entries = entries
        self.logs = []
        self.alertTable = QtWidgets.QTableWidget(0, len(m.ALERT_COLS))
        self.alertSubLabel = QtWidgets.QLabel()
        self._router = None

    def _queue_entries(self):
        return self._entries

    def _routes_map(self):
        return self._routes

    def _alog(self, s):
        self.logs.append(s)

    _alert_row = m.MainWindow._alert_row


def rows_of(f):
    out = []
    for r in range(f.alertTable.rowCount()):
        cells = [f.alertTable.item(r, c).text() if f.alertTable.item(r, c) else ""
                 for c in range(len(m.ALERT_COLS))]
        out.append(cells)
    return out


populate = m.MainWindow._alert_populate

EXCEL_ROUTES = {
    "샤넬": {"keyword": "샤넬", "route": "app",
             "cond": {"min": 500000, "max": 3000000,
                      "exclude": ["레플", "미러"], "extra": ["정품"], "days": 7}},
    "구찌": {"keyword": "구찌", "route": "app", "cond": {}},
}

print("=== 1. 서버 목록을 못 읽어도 엑셀 조건이 보인다 (이번 버그) ===")
f = _Fake(EXCEL_ROUTES, [])
populate(f, None)
rows = rows_of(f)
ck("표가 비어 있지 않다", len(rows) == 2, f"{len(rows)}행")
kw = [r[0] for r in rows]
ck("엑셀로 넣은 키워드가 보인다", set(kw) == {"샤넬", "구찌"}, str(kw))
sh = [r for r in rows if r[0] == "샤넬"][0]
ck("가격범위가 보인다", sh[2] == "500000~3000000", sh[2])
ck("제외어가 보인다", sh[3] == "레플,미러", sh[3])
ck("추가어가 보인다", sh[4] == "정품", sh[4])
ck("끌올일수가 보인다", sh[5] == "7일", sh[5])
ck("못 읽었다는 사실을 남긴다", any("목록" in x for x in f.logs), str(f.logs))

print("\n=== 2. 서버 목록이 있으면 그쪽 값이 우선 ===")
data = {"user_keywords": [
    {"keyword": "샤넬", "min_price": 700000, "max_price": None,
     "exclude_keywords": ["짝퉁"], "id": "u1"}]}
f = _Fake(EXCEL_ROUTES, [])
populate(f, data)
rows = rows_of(f)
sh = [r for r in rows if r[0] == "샤넬"][0]
ck("서버 가격이 쓰인다", sh[2] == "700000~", sh[2])
ck("id 가 채워진다", sh[6] == "u1", sh[6])
ck("서버에 없는 키워드도 함께 보인다", any(r[0] == "구찌" for r in rows),
   str([r[0] for r in rows]))
ck("중복 줄이 없다", len(rows) == 2, f"{len(rows)}행")

print("\n=== 3. 스윕 대기열도 함께 ===")
f = _Fake(EXCEL_ROUTES, [{"keyword": "롤렉스", "min": 1000000, "max": None,
                          "exclude": ["레플"]}])
populate(f, None)
kw = [r[0] for r in rows_of(f)]
ck("대기열 키워드가 보인다", "롤렉스" in kw, str(kw))
ck("셋이 다 보인다", len(kw) == 3, str(kw))

print("\n=== 4. 아무것도 없으면 그대로 둔다 ===")
f = _Fake({}, [])
f.alertTable.insertRow(0)          # 기존 내용
populate(f, None)
ck("표를 지우지 않는다", f.alertTable.rowCount() == 1)
ck("로그도 안 남긴다", f.logs == [], str(f.logs))

bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패:", bad)
sys.stdout.flush()
os._exit(1 if bad else 0)

"""등록 표(alertTable) 한 줄 구성 확인 (Qt 창 안 띄움).

    python alert_row_test.py

엑셀 조건으로 들어온 추가키워드·끌올일수는 keyword_routes.json 의 cond 에
저장되지만 표에는 안 보였다. 라우터가 실어 보내는 route 레코드에서 그 둘을
꺼내 그리는 것이 여기서 확인하는 계약이다.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, app_dir)
os.chdir(app_dir)  # OUT.json 을 어디서 돌리든 찾게

import main as m

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


def route(kind="app", reason="앱 알림 등록", **cond):
    r = {"route": kind, "reason": reason}
    if cond:
        r["cond"] = cond
    return r


S, RT, D = m.ALERT_COL_STATUS, m.ALERT_COL_ROUTE, m.ALERT_COL_DAYS

# ── 열 정의 ──────────────────────────────────────────────
ck("열 8개", len(m.ALERT_COLS) == 8, str(m.ALERT_COLS))
ck("상태 열 = 키워드 바로 옆", m.ALERT_COL_STATUS == 1, str(m.ALERT_COLS))
ck("추가 열 있음", "추가" in m.ALERT_COLS)
ck("끌올 열 있음", any("끌올" in c for c in m.ALERT_COLS), str(m.ALERT_COLS))
ck("id 열 인덱스 = 7", m.ALERT_COL_ID == 7, str(m.ALERT_COL_ID))
ck("키워드 열 인덱스 = 0", m.ALERT_COL_KEYWORD == 0)

# ── 엑셀 조건이 실린 앱 경로 키워드 ───────────────────────
vals, tips = m.alert_row_cells(
    "샤넬", route("app", extra=["정품"], days=7), "500000~3000000", "레플,미러", "8842",
    m.REG_SERVER)
ck("값 8개", len(vals) == 8, str(vals))
ck("키워드", vals[0] == "샤넬", str(vals))
ck("상태 이름", vals[S] == "서버 등록", str(vals))
ck("경로 이름", vals[RT] == "앱 알림", str(vals))
ck("가격범위 그대로", vals[RT + 1] == "500000~3000000")
ck("제외 그대로", vals[RT + 2] == "레플,미러")
ck("추가키워드 표시", vals[RT + 3] == "정품", str(vals))
ck("끌올일수 표시", vals[D] == "7일", str(vals))
ck("id 는 마지막", vals[m.ALERT_COL_ID] == "8842", str(vals))
ck("상태 셀 툴팁", "실제 등록" in (tips.get(S) or ""), str(tips))
ck("경로 셀 툴팁 = 사유", tips.get(RT) == "앱 알림 등록", str(tips))
ck("앱+끌올 → 끌올 셀 경고 툴팁", "적용되지 않" in (tips.get(D) or ""), str(tips))

# ── 상태 열: 서버/스윕/미등록/확인불가/없음 ────────────────
for _st, _name in (("sweep", "스윕 대기"), ("missing", "미등록"), ("unknown", "확인 불가")):
    vals, tips = m.alert_row_cells("샤넬", route("app"), "", "", "", _st)
    ck(f"상태 {_st} → {_name} + 툴팁", vals[S] == _name and bool(tips.get(S)),
       str((vals[S], tips.get(S))))
vals, tips = m.alert_row_cells("샤넬", route("app"), "", "", "")
ck("상태 없으면 -", vals[S] == "-" and S not in tips, str((vals, tips)))

# ── 추가키워드 여러 개 ────────────────────────────────────
vals, _ = m.alert_row_cells("구찌", route("app", extra=["정품", "박스"]), "", "", "1")
ck("추가키워드 쉼표 결합", vals[RT + 3] == "정품,박스", str(vals))

# ── 스윕 경로 — 끌올이 실제로 걸리므로 경고 없음 ──────────
# 스윕도 route 에 cond 를 남긴다(슬롯 만원으로 밀린 엑셀 키워드가 조건을
# 잃지 않게). 그래서 추가키워드·끌올일수가 여기서도 보여야 한다.
vals, tips = m.alert_row_cells(
    "롤렉스", route("sweep", reason="앱 슬롯 만원(30)", extra=["정품"], days=7),
    "1000000~", "레플", "")
ck("스윕 경로 이름", vals[RT] == "검색 스윕", str(vals))
ck("스윕도 추가키워드 표시", vals[RT + 3] == "정품", str(vals))
ck("스윕 끌올 표시", vals[D] == "7일", str(vals))
ck("스윕은 끌올 경고 없음", tips.get(D) is None, str(tips))

# ── cond 없는 옛 레코드 (마이그레이션 없이 그려야 한다) ────
vals, tips = m.alert_row_cells("에르메스", route("app"), "", "", "77")
ck("cond 없으면 추가 = -", vals[RT + 3] == "-", str(vals))
ck("cond 없으면 끌올 = -", vals[D] == "-", str(vals))
ck("cond 없으면 끌올 툴팁 없음", tips.get(D) is None, str(tips))

# ── 라우터가 모르는 키워드 (route=None) ───────────────────
vals, tips = m.alert_row_cells("프라다", None, "", "", "12")
ck("route 없으면 경로 = -", vals[RT] == "-", str(vals))
ck("route 없으면 추가 = -", vals[RT + 3] == "-")
ck("route 없으면 끌올 = -", vals[D] == "-")
ck("route 없으면 툴팁 없음", tips == {}, str(tips))

# ── 빈 값 방어 ────────────────────────────────────────────
vals, _ = m.alert_row_cells("디올", route("app", extra=[], days=None), "", "", "")
ck("extra 빈 리스트 = -", vals[RT + 3] == "-", str(vals))
ck("days None = -", vals[D] == "-", str(vals))
ck("모든 셀이 문자열", all(isinstance(v, str) for v in vals), str(vals))

# ── 요약 ──────────────────────────────────────────────────
bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패: " + ", ".join(bad))
sys.exit(1 if bad else 0)

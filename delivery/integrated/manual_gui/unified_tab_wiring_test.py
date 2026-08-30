"""매물 표(listingTable) 순수 함수 배선 확인 (Qt 창 안 띄움).

    python unified_tab_wiring_test.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main as m

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


import main as m
from daangn_ext import article_watch as aw

NOW = 1788000000
DAY = 86400


def row(**kw):
    base = {"id": "1", "title": "샤넬 클미", "region": "압구정", "url": "u",
            "price": 2600000, "first_price": 2850000, "keyword": "샤넬",
            "tier": "fresh", "first_seen": NOW - 100, "last_change": 0,
            "last_delta": 0, "source": "app"}
    base.update(kw)
    return base


rows = m.listing_display_rows([row()], NOW)
ck("행 1건", len(rows) == 1, str(rows))
r = rows[0]
ck("상태 new", r["state"] == aw.STATE_NEW, str(r))
ck("아이콘 있음", r["icon"] == m.STATE_ICONS[aw.STATE_NEW], str(r))
ck("키워드", r["keyword"] == "샤넬")
ck("Δ 음수 표기", r["delta_text"].startswith("-"), r["delta_text"])
ck("Δ 퍼센트 포함", "%" in r["delta_text"], r["delta_text"])
ck("변동 없으면 마지막변동 -", r["last_change_text"] == "-", r["last_change_text"])
ck("url 보존", r["url"] == "u")

ck("first_price 없으면 Δ 는 -",
   m.listing_display_rows([row(first_price=0)], NOW)[0]["delta_text"] == "-")
ck("가격 같으면 Δ 는 0 표기",
   m.listing_display_rows([row(price=2850000)], NOW)[0]["delta_text"].startswith("0"))

# 정렬: 최초 감지 내림차순
many = m.listing_display_rows(
    [row(id="a", first_seen=NOW - 3 * DAY), row(id="b", first_seen=NOW - 100)], NOW)
ck("최신 먼저", [x["id"] for x in many] == ["b", "a"], str([x["id"] for x in many]))

# 필터
mixed = [row(id="n", first_seen=NOW - 100),
         row(id="d", first_seen=NOW - 5 * DAY, last_change=NOW - 10,
             last_delta=-100),
         row(id="e", tier="dead")]
ck("all 은 전부", len(m.listing_display_rows(mixed, NOW, "all")) == 3)
ck("new 필터", [x["id"] for x in m.listing_display_rows(mixed, NOW, "new")] == ["n"])
ck("down 필터", [x["id"] for x in m.listing_display_rows(mixed, NOW, "down")] == ["d"])
ck("ended 필터",
   [x["id"] for x in m.listing_display_rows(mixed, NOW, "ended")] == ["e"])
ck("알 수 없는 필터는 전부", len(m.listing_display_rows(mixed, NOW, "??")) == 3)
ck("빈 입력", m.listing_display_rows([], NOW) == [])

# ── 검색 스윕 결과 정규화 ──
found = {"id": 555, "region": "분당", "title": "루이비통 알마",
         "price": 1200000, "url": "https://x/555", "image": "",
         "desc": "", "boostedAt": "2026-08-30T10:00:00+09:00",
         "status": "신규"}
norm = m.sweep_found_to_match(found, keyword="루이비통")
ck("article_id 로 옮김", norm["article_id"] == "555", str(norm))
ck("키워드 채움", norm["keyword"] == "루이비통")
ck("가격 그대로", norm["price"] == 1200000)
ck("boostedAt → time epoch", norm["time"] > 0, str(norm.get("time")))
ck("url 보존", norm["url"] == "https://x/555")
ck("id 없으면 None", m.sweep_found_to_match({"title": "x"}, "k") is None)

# ── 탭 구성 ──
ck("자동 모니터 탭 빌더 제거됨", not hasattr(m.MainWindow, "_build_auto_tab"))
ck("감시 컨트롤러 모듈 import 가능",
   __import__("daangn_ext.supervisor", fromlist=["SupervisorController"]) is not None)
ck("슬롯 상한 키 정의", m.SLOT_CAP_KEY == "keyword_slot_cap")

# ── 실제 창 구성 (offscreen) ──
# 창을 눈으로 보는 대신 여기서 조립해 본다. 위젯 배선이 끊기면 런타임에만
# 터지는데, import-only 테스트는 그걸 잡지 못한다.
_win = None
_win_err = ""
try:
    from PyQt6 import QtWidgets as _QW
    _app = _QW.QApplication.instance() or _QW.QApplication([])
    _win = m.MainWindow()
except Exception as _e:
    import traceback as _tb
    _win_err = f"{type(_e).__name__}: {_e}"
    _tb.print_exc()

ck("MainWindow 생성", _win is not None, _win_err)
if _win is not None:
    titles = [_win.tabs.tabText(i) for i in range(_win.tabs.count())]
    ck("탭 3개", _win.tabs.count() == 3, str(titles))
    ck("탭 이름", titles == ["수동 검색", "매물 감시", "에뮬레이터"], str(titles))
    ck("감시 토글 존재", hasattr(_win, "watchToggleBtn"))
    ck("고급 패널 존재", hasattr(_win, "advancedBox"))
    ck("고급 패널 접힘",
       getattr(getattr(_win, "advancedBox", None), "isChecked", bool)() is False)
    if hasattr(_win, "advancedBox"):
        # qt_ 내부 위젯(콤보 팝업 스크롤 컨테이너 등)은 Qt 가 관리한다 — 제외.
        _kids = [k for k in _win.advancedBox.findChildren(_QW.QWidget)
                 if not k.objectName().startswith("qt_")]
        # 체크 해제는 자식을 비활성화만 한다 — 실제로 접혔는지(숨겨졌는지) 본다.
        ck("고급 자식 숨김", _kids and all(k.isHidden() for k in _kids),
           f"{sum(1 for k in _kids if k.isHidden())}/{len(_kids)}")
        _win.advancedBox.setChecked(True)
        ck("펼치면 다시 보임", not any(k.isHidden() for k in _kids))
        _win.advancedBox.setChecked(False)
    ck("감시 토글 핸들러", callable(getattr(_win, "on_watch_toggle", None)))
    ck("라우터 속성", hasattr(_win, "_router"))
    ck("컨트롤러 속성", hasattr(_win, "_supervisor"))
    ck("스윕 결과 핸들러", callable(getattr(_win, "_on_sweep_found", None)))
    ck("스윕 cfg 조립", callable(getattr(_win, "_auto_cfg_base", None))
       and callable(getattr(_win, "_sweep_cfg", None)))
    for _attr in ("autoAreaTree", "autoExtra", "autoExclude", "autoMin",
                  "autoMax", "autoDays", "autoRestMin", "autoRestMax",
                  "autoGapMin", "autoGapMax", "autoLanes", "autoTokenRefresh",
                  "autoProxyViewBtn", "autoExcelBtn", "autoNotifyBtn",
                  "autoAccountsBtn"):
        ck(f"스윕 설정 이사: {_attr}", hasattr(_win, _attr))
    for _attr in ("autoKeyword", "autoStartBtn", "autoStatus", "autoProgress",
                  "autoTable", "autoLog"):
        ck(f"안 옮긴 위젯 제거: {_attr}", not hasattr(_win, _attr))
    ck("자동폴링 버튼 제거", not hasattr(_win, "alertAutoPollBtn"))
    ck("경로 열 추가", getattr(_win, "alertTable", None) is not None
       and _win.alertTable.columnCount() == 5)
    # close() 는 부르지 않는다 — closeEvent 가 모달 확인창을 띄워 offscreen 에서 멈춘다.

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

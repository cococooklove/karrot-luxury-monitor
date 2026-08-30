"""매물 표(listingTable) 순수 함수 배선 확인 (Qt 창 안 띄움).

    python unified_tab_wiring_test.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, app_dir)
os.chdir(app_dir)  # Ensure OUT.json is found regardless of where test is run from

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

# ── 백필이 세운 중복판정용 묘비(source=match_seen)는 표에 안 나온다 ──
# 기준은 출처다. '제목이 비었다'로 거르면 제목 없이 들어온 실제 매물이 종료되는
# 순간 표에서 조용히 사라진다.
tomb = row(id="t", title="", region="", tier=aw.TIER_DEAD, price=0,
           first_price=0, keyword="", source=aw.SOURCE_MATCH_SEEN)
ck("백필 묘비는 숨김", m.listing_display_rows([tomb], NOW) == [], "")
ck("백필 묘비는 ended 필터에서도 숨김",
   m.listing_display_rows([tomb], NOW, "ended") == [])
ck("match_seen 은 제목이 있어도 숨김",
   m.listing_display_rows([dict(tomb, title="샤넬")], NOW) == [])
ck("match_seen 은 살아 있어도(fresh) 숨김",
   m.listing_display_rows([dict(tomb, tier=aw.TIER_FRESH)], NOW) == [])
ck("제목 없는 dead 라도 출처가 있으면 보인다",
   [x["id"] for x in m.listing_display_rows(
       [dict(tomb, source="app")], NOW)] == ["t"], "종료 사유는 사용자가 봐야 한다")
ck("제목 없는 dead 는 ended 필터에도 걸린다",
   [x["id"] for x in m.listing_display_rows(
       [dict(tomb, source="sweep")], NOW, "ended")] == ["t"])
ck("제목 있는 dead 는 보인다",
   [x["id"] for x in m.listing_display_rows(
       [dict(tomb, title="샤넬", source="app")], NOW)] == ["t"])
ck("evicted 는 제목 없어도 안 숨김",
   [x["id"] for x in m.listing_display_rows(
       [dict(tomb, tier=aw.TIER_EVICTED, source="app")], NOW)] == ["t"])
ck("묘비를 섞어도 나머지는 그대로",
   [x["id"] for x in m.listing_display_rows([row(id="a"), tomb], NOW)] == ["a"])
ck("백필이 세우는 출처가 표의 필터 기준과 같다",
   'aw.SOURCE_MATCH_SEEN' in open(
       os.path.join(app_dir, "tools", "backfill_listings.py"),
       encoding="utf-8").read())

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
_sup = __import__("daangn_ext.supervisor",
                  fromlist=["SupervisorController", "SupervisorPolicy"])
ck("감시 컨트롤러 모듈이 두 클래스를 낸다",
   all(callable(getattr(_sup, n, None))
       for n in ("SupervisorController", "SupervisorPolicy")),
   str(sorted(n for n in dir(_sup) if n[0].isupper())))
ck("컨트롤러가 수명 API 를 갖춘다",
   all(callable(getattr(_sup.SupervisorController, n, None))
       for n in ("start", "stop", "is_running", "retune")))
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
       hasattr(_win, "advancedBox") and _win.advancedBox.isChecked() is False)
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
    # ── 상태칩 → 고급 패널 항목 (설계 §1: 칩 클릭은 해당 항목으로 스크롤) ──
    ck("상태칩 존재",
       set(getattr(_win, "_chips", {})) == {"token", "accounts", "coverage", "poll"},
       str(sorted(getattr(_win, "_chips", {}))))
    ck("칩 목적지가 실재하는 위젯",
       all(getattr(_win, a, None) is not None
           for a in _win.CHIP_TARGETS.values()),
       str(_win.CHIP_TARGETS))
    ck("칩 목적지는 전부 고급 패널 안",
       all(getattr(_win, a) in _win.advancedBox.findChildren(_QW.QWidget)
           for a in _win.CHIP_TARGETS.values()))
    ck("탭이 스크롤 영역 안에 있다",
       _win._enclosing_scroll(_win.alertCoverMode) is not None)
    _win.advancedBox.setChecked(False)
    _moved = _win.on_chip_clicked("coverage")
    ck("칩을 누르면 접힌 고급 패널이 펴진다",
       _moved and _win.advancedBox.isChecked())
    ck("커버리지 칩 → 커버 모드로 데려간다",
       _win.focusWidget() is _win.alertCoverMode, str(_win.focusWidget()))
    ck("펴진 목적지는 보인다", not _win.alertCoverMode.isHidden())
    ck("이미 펴져 있어도 데려간다", _win.on_chip_clicked("poll"))
    ck("다음폴링 칩 → 폴링 주기", _win.focusWidget() is _win.alertPollInterval,
       str(_win.focusWidget()))
    ck("토큰·계정 칩 → 계정 현황",
       _win.on_chip_clicked("token") and _win.on_chip_clicked("accounts")
       and _win.focusWidget() is _win.alertFleetBtn, str(_win.focusWidget()))
    # 대응 항목 없는 칩은 아무 데도 데려가지 않는다(엉뚱한 목적지보다 낫다).
    ck("추적중은 목적지가 없다", "watch" not in _win.CHIP_TARGETS)
    ck("모르는 칩은 무시", _win.on_chip_clicked("watch") is False)
    _win.advancedBox.setChecked(False)
    # 칩 문구는 헬스 갱신이 채운다(자격증명 없어도 크래시 없이 값이 바뀐다).
    _win._refresh_alert_health()
    ck("헬스 갱신이 칩 문구를 채운다",
       _win._chips["token"].text().startswith("토큰")
       and _win._chips["accounts"].text().startswith("계정")
       and _win._chips["coverage"].text().startswith("커버리지")
       and "폴링" in _win._chips["poll"].text(),
       " / ".join(c.text() for c in _win._chips.values()))

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
    ck("단일계정 일괄등록 제거", not hasattr(_win, "alertBulkBtn")
       and not hasattr(_win, "on_alert_bulk"))
    ck("엑셀 조건 캐시 제거", not hasattr(_win, "auto_conditions"))

    # ── 엑셀 조건 → 라우터 (워크북 안 연다) ──
    class _FakeRouter:
        def __init__(self):
            self.calls = []

        def add_many(self, keywords, min_price=None, max_price=None,
                     exclude=None, core_only=False, log=None):
            self.calls.append((list(keywords), min_price, max_price,
                               list(exclude or []), core_only))
            return [{"keyword": k, "route": "app", "reason": "앱 알림 등록"}
                    for k in keywords]

    _conds = [
        {"category": "가방", "keyword": "샤넬", "extra": ["정품"],
         "exclude": ["레플"], "min": 500000, "max": 3000000, "days": 7},
        {"category": "가방", "keyword": "구찌", "extra": [],
         "exclude": ["레플"], "min": 500000, "max": 3000000, "days": 7},
        {"category": "시계", "keyword": "롤렉스", "extra": [],
         "exclude": [], "min": 1000000, "max": None, "days": 30},
        {"category": "", "keyword": "", "extra": [], "exclude": [],
         "min": None, "max": None, "days": None},          # 빈 키워드 = 버림
    ]
    _groups = _win._condition_groups(_conds)
    ck("필터 같은 행은 한 그룹", len(_groups) == 2, str(_groups))
    ck("빈 키워드 버림",
       all(kw for g in _groups for kw in g[0]), str(_groups))
    _g0 = next(g for g in _groups if "샤넬" in g[0])
    ck("그룹에 두 키워드", sorted(_g0[0]) == ["구찌", "샤넬"], str(_g0))
    ck("그룹이 행의 가격·제외를 그대로 든다",
       (_g0[1], _g0[2], _g0[3]) == (500000, 3000000, ["레플"]), str(_g0))

    _fake = _FakeRouter()
    _real_router = _win._router
    _win._router = _fake
    _logged = []
    _res = _win._route_conditions(_conds, core_only=True, log=_logged.append)
    _win._router = _real_router
    ck("엑셀 조건이 라우터 add_many 로 간다", len(_fake.calls) == 2,
       str(_fake.calls))
    ck("core_only 전달", all(c[4] is True for c in _fake.calls))
    ck("모든 키워드 배정",
       sorted(k for c in _fake.calls for k in c[0]) == ["구찌", "롤렉스", "샤넬"],
       str(_fake.calls))
    ck("라우터 결과를 돌려준다", len(_res) == 3, str(_res))
    ck("빈 조건이면 그룹 없음", _win._condition_groups([]) == [])
    _empty = _FakeRouter()
    _win._router = _empty
    _win._route_conditions([], core_only=False, log=_logged.append)
    _win._router = _real_router
    ck("빈 조건이면 라우터를 아예 안 부른다", _empty.calls == [], str(_empty.calls))

    # ── 대기열 변화 → 검색 스윕 재시작 (Finding 1) ──
    class _FakeQueue:
        def __init__(self, kws):
            self._k = list(kws)

        def keywords(self):
            return list(self._k)

        def entries(self):
            return [{"keyword": k, "min": None, "max": None,
                     "exclude": [], "at": 0} for k in self._k]

        def __len__(self):
            return len(self._k)

    class _FakeSupervisor:
        def __init__(self, running=True):
            self._r = running

        def is_running(self):
            return self._r

        def retune(self):
            pass

    class _FakeAM:
        def __init__(self, running):
            self._r = running

        def isRunning(self):
            return self._r

    def _rig(queue_kws, have, running_supervisor=True, sweep_alive=False):
        """_resync_search_sweep 만 떼어 본다 — 진짜 스레드도 네트워크도 안 쓴다."""
        calls = []
        _win.alertLog.clear()
        _win._sweep_queue = _FakeQueue(queue_kws)
        _win._supervisor = _FakeSupervisor(running_supervisor)
        _win._sweep_kws = have
        _win.auto_monitor = _FakeAM(sweep_alive) if sweep_alive else None
        _win._start_search_sweep = lambda: calls.append("start")
        _win._stop_search_sweep = lambda: (calls.append("stop"),
                                           setattr(_win, "_sweep_kws", None))[0]
        _win._resync_search_sweep()
        return calls

    _saved = (_win._sweep_queue, _win._supervisor, _win._sweep_kws,
              _win.auto_monitor)
    ck("키워드 늘면 재시작", _rig(["샤넬", "구찌"], {"샤넬"}) == ["stop", "start"])
    ck("승격으로 줄면 재시작", _rig(["샤넬"], {"샤넬", "구찌"}) == ["stop", "start"])
    ck("같고 살아 있으면 안 건드림",
       _rig(["샤넬"], {"샤넬"}, sweep_alive=True) == [])
    # AutoMonitor.run 이 치명오류로 빠지면 _sweep_kws 는 그대로 남는다. running 을
    # 안 보면 want == have 가 계속 성립해 스윕이 세션 내내 죽은 채 방치된다.
    ck("같아도 스레드가 죽었으면 되살림", _rig(["샤넬"], {"샤넬"}) == ["stop", "start"])
    ck("되살림 로그는 재시작과 구분됨",
       "죽어 있음" in _win.alertLog.toPlainText(), _win.alertLog.toPlainText())
    _rig(["샤넬", "구찌"], {"샤넬"})
    ck("키워드 변경 로그는 되살림과 구분됨",
       "죽어 있음" not in _win.alertLog.toPlainText()
       and "키워드 변경" in _win.alertLog.toPlainText(),
       _win.alertLog.toPlainText())
    ck("큐가 비면 정지만", _rig([], {"샤넬"}) == ["stop"])
    ck("안 떠 있고 큐가 차면 시작", _rig(["샤넬"], None) == ["start"])
    ck("안 떠 있고 큐도 비면 무동작", _rig([], None) == [])
    ck("빈 집합끼리 같으면 죽었어도 무동작", _rig([], set()) == [])
    ck("감시 꺼져 있으면 무동작",
       _rig(["샤넬"], {"구찌"}, running_supervisor=False) == [])
    # 인스턴스 속성으로 덮어쓴 메서드는 지워서 클래스 구현으로 되돌린다.
    for _n in ("_start_search_sweep", "_stop_search_sweep"):
        _win.__dict__.pop(_n, None)
    (_win._sweep_queue, _win._supervisor, _win._sweep_kws,
     _win.auto_monitor) = _saved
    ck("메서드 원복", _win._start_search_sweep.__func__ is
       m.MainWindow._start_search_sweep)

    _seen = []
    _sv_router = _win._router
    _win._resync_search_sweep = lambda: _seen.append("resync")
    # 폴링은 이제 _alert_run 워커로 나간다(씨딩·승격이 그 안에 들어갔다).
    _win._alert_run = lambda fn, on_done=None: _seen.append("poll")
    _win._router = None
    _win._auto_poll_tick()
    for _n in ("_resync_search_sweep", "_alert_run"):
        _win.__dict__.pop(_n, None)
    _win._router = _sv_router
    ck("_auto_poll_tick → 재동기화 후 폴링", _seen == ["resync", "poll"], str(_seen))

    # ── 앱 목록을 못 읽어도 대기열은 그린다 (Finding 2) ──
    _sq = _win._sweep_queue
    _win._sweep_queue = _FakeQueue(["샤넬", "구찌"])
    _win.alertLog.clear()
    _win._alert_populate(None)
    _rows = _win.alertTable.rowCount()
    _txt = _win.alertLog.toPlainText()
    _win._sweep_queue = _FakeQueue([])
    _win.alertTable.setRowCount(3)
    _win._alert_populate(None)
    _kept = _win.alertTable.rowCount()
    _win._sweep_queue = _sq
    _win.alertTable.setRowCount(0)
    ck("목록 실패해도 대기열 행은 그린다", _rows == 2, f"{_rows}행")
    ck("목록을 못 읽었다고 로그에 남긴다", "앱 등록 목록을 못 읽었" in _txt,
       _txt.strip()[:80])
    ck("대기열도 비면 표를 건드리지 않는다", _kept == 3, f"{_kept}행")
    ck("경로 열 추가", getattr(_win, "alertTable", None) is not None
       and _win.alertTable.columnCount() == 5)

    # ── 첫 실행에서 서버에 이미 있는 키워드를 앱 슬롯으로 인정한다 ──
    # routes 파일이 없으면 라우터는 used=0 으로 본다. 그대로 두면 이미 꽉 찬
    # 서버 한도에 계속 등록을 시도하고 전부 스윕으로 밀린다.
    import tempfile as _tf
    from daangn_ext.keyword_router import KeywordRouter as _KR
    from daangn_ext.sweep_queue import SweepQueue as _SQ

    class _NoFleet:
        def register_all(self, *a, **k):
            raise AssertionError("씨딩은 네트워크를 쓰면 안 된다")

    _dS = _tf.mkdtemp()
    _rS = _KR(_NoFleet(), _SQ(os.path.join(_dS, "q.json")), slot_cap=30,
              routes_fp=os.path.join(_dS, "routes.json"))
    _svr, _svq = _win._router, _win._sweep_queue
    _win._router = _rS
    _win._sweep_queue = _FakeQueue([])
    _win.alertLog.clear()
    _win._alert_populate({"user_keywords": [{"keyword": "샤넬", "id": 1},
                                            {"keyword": "루이비통", "id": 2}]})
    _cap = _rS.capacity()
    ck("첫 실행에 서버 등록분을 슬롯으로 인식", _cap["used"] == 2, str(_cap))
    ck("씨딩 사실을 로그에 남긴다",
       "앱 슬롯으로 인식" in _win.alertLog.toPlainText(),
       _win.alertLog.toPlainText().strip()[:100])
    ck("표의 경로가 '-' 가 아니다",
       _win.alertTable.item(0, 1).text() != "-",
       _win.alertTable.item(0, 1).text())
    # 두 번째 그리기는 씨딩하지 않는다
    _win.alertLog.clear()
    _win._alert_populate({"user_keywords": [{"keyword": "에르메스", "id": 3}]})
    ck("두 번째 그리기는 씨딩 안 함", _rS.capacity()["used"] == 2,
       str(_rS.capacity()))
    ck("두 번째는 씨딩 로그 없음",
       "앱 슬롯으로 인식" not in _win.alertLog.toPlainText())
    _win._router, _win._sweep_queue = _svr, _svq
    _win.alertTable.setRowCount(0)
    _win.alertLog.clear()
    # close() 는 부르지 않는다 — closeEvent 가 모달 확인창을 띄워 offscreen 에서 멈춘다.

# ── 중복 판정(dedupe_new_matches) ──
# match_seen.json 을 없앤 자리다. 여기가 틀리면 같은 매물을 폴링마다 재알림한다.
print("=== 중복 판정 ===")


class _FakeStore:
    """id 로 행을 돌려주는 최소 watch 저장소."""

    def __init__(self, ids=()):
        self.ids = set(ids)
        self.asked = []

    def get(self, aid):
        self.asked.append(aid)
        return {"id": aid, "tier": "dead"} if aid in self.ids else None


# 1) 키 순서: watch 는 article_id 로 키를 잡는다. 알림 인박스 id 를 먼저 보면
#    저장소가 절대 가질 수 없는 키로 물어보게 된다.
_st = _FakeStore({"777"})
_fb = set()
_fresh, _dropped = m.dedupe_new_matches(
    [{"article_id": "777", "id": "inbox-1", "title": "이미 본 매물"}], _st, _fb)
ck("article_id 로 물어본다", _st.asked == ["777"], str(_st.asked))
ck("저장소에 있으면 신규 아님", _fresh == [] and _dropped == 0, str(_fresh))

# 2) 저장소에 없으면 신규다. fallback 에는 넣지 않는다 — add_from_matches 가
#    행(묘비 포함)을 쓰므로 다음 회차엔 저장소가 답한다.
_st2 = _FakeStore()
_fb2 = set()
_fresh2, _ = m.dedupe_new_matches(
    [{"article_id": "888", "id": "inbox-2"}], _st2, _fb2)
ck("저장소에 없으면 신규", [x["article_id"] for x in _fresh2] == ["888"],
   str(_fresh2))
ck("저장소가 있으면 fallback 안 씀", _fb2 == set(), str(_fb2))

# 3) article_id 없는 payload: 저장소는 인박스 id 를 절대 못 가지므로 물어보면
#    영원히 None 이다. fallback 으로만 막는다.
_st3 = _FakeStore()
_fb3 = set()
_NOART = [{"id": "inbox-9", "title": "article_id 없음"}]
_f3a, _ = m.dedupe_new_matches(_NOART, _st3, _fb3)
_f3b, _ = m.dedupe_new_matches(_NOART, _st3, _fb3)
ck("article_id 없어도 첫 회는 신규", len(_f3a) == 1, str(_f3a))
ck("article_id 없으면 저장소에 안 물어본다", _st3.asked == [], str(_st3.asked))
ck("article_id 없으면 fallback 이 재알림 막는다", _f3b == [], str(_f3b))
ck("fallback 에 인박스 id 가 들어간다", _fb3 == {"inbox-9"}, str(_fb3))

# 4) 저장소를 못 연 경우(None): fallback 이 유일한 방어선이다.
_fb4 = set()
_M4 = [{"article_id": "555", "id": "inbox-5"}]
_f4a, _ = m.dedupe_new_matches(_M4, None, _fb4)
_f4b, _ = m.dedupe_new_matches(_M4, None, _fb4)
ck("저장소 없어도 첫 회는 신규", len(_f4a) == 1, str(_f4a))
ck("저장소 없으면 두 번째는 안 알린다", _f4b == [], str(_f4b))
ck("저장소 없을 땐 article_id 로 fallback", _fb4 == {"555"}, str(_fb4))

# 4-b) 저장소가 seen_key 를 낼 수 있으면 article_id 없는 키는 거기에 남는다.
#      프로세스 집합은 재시작하면 비므로 그것만으론 폴링마다 재알림이었다.
import tempfile as _tf

_dbp = os.path.join(_tf.mkdtemp(), "watch.db")
_NOART2 = [{"id": "inbox-ad-1", "title": "광고 — articleId 없음"}]
_store_a = aw.WatchStore(_dbp)
_fb6 = set()
_f6a, _ = m.dedupe_new_matches(_NOART2, _store_a, _fb6)
ck("영속 저장소여도 첫 회는 신규", len(_f6a) == 1, str(_f6a))
ck("영속 저장소가 있으면 프로세스 집합은 안 쓴다", _fb6 == set(), str(_fb6))
_f6dup, _ = m.dedupe_new_matches(_NOART2 * 2, _store_a, _fb6)
ck("같은 회차에 같은 키가 둘이어도 한 번만", _f6dup == [], str(_f6dup))
_store_a.close()

_store_b = aw.WatchStore(_dbp)                      # 재시작
_f6b, _ = m.dedupe_new_matches(_NOART2, _store_b, set())
ck("재시작해도 다시 안 알린다", _f6b == [], str(_f6b))
ck("키는 매물 표에 안 뜬다",
   m.listing_display_rows(_store_b.listing_rows(), NOW) == [],
   str(_store_b.listing_rows()))
ck("키는 추적 대상이 아니다",
   aw.WatchTracker(_store_b).add_from_matches(_NOART2) == 0)
ck("키가 watch 행이 되지도 않는다", _store_b.get("inbox-ad-1") is None)
_store_b.close()

# 5) 키가 아예 없는 payload 는 버리되 건수를 돌려준다(로그로 보이게).
_f5, _d5 = m.dedupe_new_matches([{"title": "키 없음"}], _FakeStore(), set())
ck("키 없으면 버린다", _f5 == [], str(_f5))
ck("버린 건수를 돌려준다", _d5 == 1, str(_d5))

if _win is not None:
    # ── _match_populate 가 그 문을 실제로 쓰는가 ──
    _sv = (_win._watch_store, _win._watch_tracker, _win._match_seen_fallback)
    _notified = []
    _win._notify_matches = lambda items: _notified.append(list(items))
    _win._refresh_listing_table = lambda: None
    _win._refresh_alert_health = lambda: None
    _win._watch_tracker = None
    _win._watch_store = _FakeStore({"777"})
    _win._match_seen_fallback = set()
    _win.alertLog.clear()
    _win._match_populate([{"article_id": "777", "id": "inbox-1"},
                          {"article_id": "888", "id": "inbox-2"},
                          {"title": "키 없음"}])
    ck("본 매물은 빼고 신규만 알린다",
       [x.get("article_id") for x in (_notified[0] if _notified else [])] == ["888"],
       str(_notified))
    ck("_last_new 는 신규 건수", _win._last_new == 1, str(_win._last_new))
    ck("버린 payload 를 로그에 남긴다",
       "id 없는 payload" in _win.alertLog.toPlainText(),
       _win.alertLog.toPlainText().strip()[:80])

    # 저장소를 못 연 창(=None)이어도 같은 매물을 두 번 알리지 않는다.
    _win._watch_store = None
    _win._match_seen_fallback = set()
    _notified.clear()
    _win._match_populate([{"article_id": "999", "id": "inbox-3"}])
    _win._match_populate([{"article_id": "999", "id": "inbox-3"}])
    ck("저장소 없어도 한 번만 알린다", len(_notified) == 1, str(_notified))
    for _n in ("_notify_matches", "_refresh_listing_table", "_refresh_alert_health"):
        _win.__dict__.pop(_n, None)
    (_win._watch_store, _win._watch_tracker, _win._match_seen_fallback) = _sv
    _win.alertLog.clear()

# 헤드리스도 같은 문을 쓴다 — 소스에 옛 FIFO 가 남아 있으면 갈라진 것이다.
import inspect as _inspect

_src = _inspect.getsource(m._run_headless)
ck("헤드리스가 dedupe_new_matches 를 쓴다", "dedupe_new_matches(" in _src)
ck("헤드리스에 fallback 집합이 있다", "fallback_seen = set()" in _src)
ck("헤드리스 옛 FIFO 제거", not any(
    s in _src for s in ("SEEN_FP", "seen_order", "SEEN_CAP", "_save_seen")))
ck("GUI 에 match_seen 파일 코드 없음",
   not any(hasattr(m.MainWindow, n) for n in
           ("_MATCH_SEEN_FILE", "_load_match_seen", "_save_match_seen")))

if _win is not None:
    print("=== 스윕 설정 영속화 — GUI 에서 고른 값이 곧 서버 설정이다 ===")
    import json as _json2
    import tempfile as _tf2
    import shutil as _sh2
    _Qt2 = m.Qt

    ck("전국 훑기 체크박스 존재", hasattr(_win, "autoNationwide"))
    ck("전국 훑기는 기본 꺼짐", _win.autoNationwide.isChecked() is False)
    ck("전국 훑기도 고급 패널 안",
       _win.autoNationwide in _win.advancedBox.findChildren(_QW.QWidget))
    ck("저장 배선 존재", callable(getattr(_win, "_sweep_settings_patch", None))
       and callable(getattr(_win, "_save_sweep_settings", None))
       and callable(getattr(_win, "_restore_sweep_settings", None)))
    ck("저장은 디바운스된다(트리 체크 폭주 대비)",
       isinstance(getattr(_win, "_sweep_save_timer", None), QtCore_QTimer := __import__(
           "PyQt6.QtCore", fromlist=["QTimer"]).QTimer))

    _tmp2 = _tf2.mkdtemp(prefix="alertcfg_")
    _cfg_fp = os.path.join(_tmp2, "data", "alert_settings.json")
    _win._ALERT_SETTINGS_FILE = _cfg_fp        # 인스턴스 속성이 클래스 값을 가린다

    # 1) 새 설치(설정 파일 없음) — 전국이 아니라 기본 지역으로 떨어져야 한다.
    for _l in _win.auto_area_leaves:
        if _l.checkState(0) == _Qt2.CheckState.Checked:
            _l.setCheckState(0, _Qt2.CheckState.Unchecked)
    _win.autoNationwide.setChecked(False)
    _fresh = _win._auto_cfg_base()
    ck("새 설치 GUI 범위는 전국이 아니다", _fresh["scope"] == "regions", _fresh["scope"])
    ck("새 설치 GUI 범위 = 기본 지역",
       _fresh["regions"] == m.default_sweep_regions("./OUT.json"),
       str(len(_fresh["regions"])))
    ck("새 설치 헤드리스도 같은 범위",
       m.headless_sweep_cfg({}, [], {})["regions"] == _fresh["regions"])

    # 2) 위젯 값을 바꾸고 저장 → 헤드리스가 같은 키로 읽어 같은 cfg 를 만든다.
    _win.autoRestMax.setValue(140); _win.autoRestMin.setValue(55)
    _win.autoGapMax.setValue(2.5); _win.autoGapMin.setValue(0.9)
    _win.autoLanes.setValue(4); _win.autoDays.setValue(3)
    _win.autoExtra.setText("빈티지")
    _win.autoExclude.setText("레플, 미러")
    _win.autoMin.setText("100000"); _win.autoMax.setText("3000000")
    _picked = []
    for _l in _win.auto_area_leaves[:3]:
        _l.setCheckState(0, _Qt2.CheckState.Checked)
        _picked.append(_l.data(0, _Qt2.ItemDataRole.UserRole))
    _win._save_sweep_settings()
    ck("설정 파일이 쓰였다", os.path.exists(_cfg_fp), _cfg_fp)
    with open(_cfg_fp, encoding="utf-8") as _f2:
        _saved = _json2.load(_f2)
    for _k in ("sweep_regions", "sweep_rest_min", "sweep_rest_max", "sweep_gap_min",
               "sweep_gap_max", "sweep_lanes", "sweep_extra", "sweep_exclude",
               "sweep_min", "sweep_max", "sweep_days", m.SWEEP_NATIONWIDE_KEY):
        ck(f"저장 키: {_k}", _k in _saved, str(sorted(_saved)))
    _entries = [{"keyword": "샤넬", "min": None, "max": None, "exclude": []}]
    _hcfg = m.headless_sweep_cfg(_saved, _entries, {})
    _gcfg = dict(_win._auto_cfg_base())
    _gcfg["conditions"] = m.sweep_conditions(
        _entries, extra=_win._splt(_win.autoExtra.text()),
        exclude=_win._splt(_win.autoExclude.text()),
        min_price=_win._num(_win.autoMin.text()),
        max_price=_win._num(_win.autoMax.text()),
        days=_win.autoDays.value() or None)
    for _k in ("rest_min", "rest_max", "gap_min", "gap_max", "lanes",
               "scope", "regions"):
        ck(f"서버가 GUI 값을 그대로 읽는다: {_k}", _hcfg[_k] == _gcfg[_k],
           f"{_hcfg[_k]!r} vs {_gcfg[_k]!r}")
    ck("저장된 지역이 고른 지역", _hcfg["regions"] == _picked, str(_hcfg["regions"]))
    ck("서버 조건이 GUI 조건과 같다", _hcfg["conditions"] == _gcfg["conditions"],
       str(_hcfg["conditions"]))
    ck("서버가 읽은 휴식값", (_hcfg["rest_min"], _hcfg["rest_max"]) == (55, 140),
       str((_hcfg["rest_min"], _hcfg["rest_max"])))
    ck("서버가 읽은 끌올일수", _hcfg["conditions"][0]["days"] == 3)
    ck("서버가 읽은 제외", _hcfg["conditions"][0]["exclude"] == ["레플", "미러"],
       str(_hcfg["conditions"][0]["exclude"]))

    # 3) 되돌리기 — 위젯을 흩뜨린 뒤 복원하면 저장값으로 돌아온다.
    _win.autoRestMax.setValue(300); _win.autoRestMin.setValue(200)
    _win.autoLanes.setValue(0); _win.autoExtra.setText("")
    for _l in _win.auto_area_leaves[:3]:
        _l.setCheckState(0, _Qt2.CheckState.Unchecked)
    _win._restore_sweep_settings()
    ck("복원: 휴식", (_win.autoRestMin.value(), _win.autoRestMax.value()) == (55, 140),
       str((_win.autoRestMin.value(), _win.autoRestMax.value())))
    ck("복원: 레인", _win.autoLanes.value() == 4, str(_win.autoLanes.value()))
    ck("복원: 추가 키워드", _win.autoExtra.text() == "빈티지", _win.autoExtra.text())
    ck("복원: 지역 체크", _win._selected_auto_regions() == _picked,
       str(_win._selected_auto_regions()))

    # 4) 전국은 체크박스로만 켜지고, 그 선택도 저장된다.
    for _l in _win.auto_area_leaves[:3]:
        _l.setCheckState(0, _Qt2.CheckState.Unchecked)
    _win.autoNationwide.setChecked(True)
    ck("전국 체크 시 GUI 범위 전국", _win._auto_cfg_base()["scope"] == "nationwide")
    _win._save_sweep_settings()
    with open(_cfg_fp, encoding="utf-8") as _f2:
        _saved2 = _json2.load(_f2)
    ck("전국 선택이 저장된다", _saved2.get(m.SWEEP_NATIONWIDE_KEY) is True)
    ck("서버도 전국으로 읽는다",
       m.headless_sweep_cfg(_saved2, _entries, {})["scope"] == "nationwide")
    _win.autoNationwide.setChecked(False)
    _win.__dict__.pop("_ALERT_SETTINGS_FILE", None)
    _sh2.rmtree(_tmp2, ignore_errors=True)

    print("=== GUI 스윕 되살리기 — 상한이 있고 죽은 엔진을 버린다 ===")
    import daangn.auto_monitor as _am_mod
    _real_AM = _am_mod.AutoMonitor

    class _FakeSig:
        def __init__(self):
            self.n = 0

        def connect(self, *_a, **_k):
            self.n += 1

        def disconnect(self, *_a, **_k):
            if self.n <= 0:
                raise TypeError("no connection")   # Qt 와 같은 예외
            self.n = 0

    _made_am, _deleted_am = [], []

    class _FakeMonitor:
        """뜨자마자 죽는 엔진 — run() 안 치명오류로 스레드가 빠지는 그 상황."""

        def __init__(self, parent, cfg):
            self.cfg = cfg
            self.log = _FakeSig()
            self.found = _FakeSig()
            _made_am.append(self)

        def start(self):
            pass

        def isRunning(self):
            return False

        def stop(self):
            pass

        def deleteLater(self):
            _deleted_am.append(self)

    class _FakeSup:
        def is_running(self):
            return True

    class _FakeQ2:
        def __init__(self, kws):
            self._k = list(kws)

        def keywords(self):
            return list(self._k)

    _sv3 = (_win._supervisor, _win._sweep_queue, _win.auto_monitor,
            getattr(_win, "_sweep_kws", None))
    _am_mod.AutoMonitor = _FakeMonitor
    _fq = _FakeQ2(["샤넬"])
    _win._supervisor = _FakeSup()
    _win._sweep_queue = _fq
    _win.auto_monitor = None
    _win._sweep_kws = None
    _win._sweep_revives = 0
    _win._sweep_cfg = lambda: {"conditions": [{"keyword": "샤넬"}],
                               "out_json": "./OUT.json"}
    _win.alertLog.clear()
    for _ in range(m.SWEEP_REVIVE_MAX + 6):
        _win._resync_search_sweep()
    _txt = _win.alertLog.toPlainText()
    ck("되살리기는 상한까지만",
       len(_made_am) == 1 + m.SWEEP_REVIVE_MAX, str(len(_made_am)))
    ck("죽은 모니터를 전부 버린다",
       _deleted_am == _made_am[:-1], f"{len(_deleted_am)}/{len(_made_am) - 1}")
    ck("살아 있는 마지막 하나는 안 버린다", _made_am[-1] not in _deleted_am)
    ck("버릴 때 시그널을 끊는다",
       all(x.log.n == 0 and x.found.n == 0 for x in _deleted_am))
    ck("포기 로그는 한 번만", _txt.count("포기합니다") == 1, str(_txt.count("포기합니다")))
    ck("되살림 로그에 진행도", f"(1/{m.SWEEP_REVIVE_MAX})" in _txt)
    _before_am = len(_made_am)
    _fq._k = ["샤넬", "구찌"]                 # 대기열이 바뀌면 상한이 풀린다
    _win._resync_search_sweep()
    ck("대기열 변경은 상한을 푼다", len(_made_am) == _before_am + 1,
       str(len(_made_am)))
    ck("변경 재시작도 옛 모니터를 버린다", len(_deleted_am) == _before_am,
       str(len(_deleted_am)))
    _am_mod.AutoMonitor = _real_AM
    _win.__dict__.pop("_sweep_cfg", None)
    _win.auto_monitor = None
    (_win._supervisor, _win._sweep_queue, _win.auto_monitor,
     _win._sweep_kws) = _sv3
    _win._sweep_revives = 0
    _win.alertLog.clear()

    print("=== 관측 상한 초기화 — GUI 에서 닿는다 ===")
    ck("초기화 버튼 존재", hasattr(_win, "alertResetCapBtn"))
    ck("초기화 버튼은 고급 패널 안",
       _win.alertResetCapBtn in _win.advancedBox.findChildren(_QW.QWidget))
    ck("툴팁이 서버 플래그도 알려준다",
       "--reset-cap" in _win.alertResetCapBtn.toolTip(),
       _win.alertResetCapBtn.toolTip())

    class _CapRouter:
        def __init__(self, has):
            self.has = has
            self.calls = 0

        def reset_observed_cap(self, log=None):
            self.calls += 1
            if not self.has:
                return False
            self.has = False
            return True

    _sv4 = _win._router
    _win._router = _CapRouter(True)
    _win.alertLog.clear()
    ck("버튼이 관측치를 되돌린다", _win.on_reset_cap_clicked() is True)
    ck("되돌림 로그", "초기화" in _win.alertLog.toPlainText(),
       _win.alertLog.toPlainText().strip()[:80])
    _win.alertLog.clear()
    ck("되돌릴 게 없으면 False", _win.on_reset_cap_clicked() is False)
    ck("되돌릴 게 없다는 로그", "이미 비어" in _win.alertLog.toPlainText(),
       _win.alertLog.toPlainText().strip()[:80])
    ck("라우터를 실제로 불렀다", _win._router.calls == 2, str(_win._router.calls))
    # 고급 패널이 접혀 있으면 자식이 '비활성'이라 click() 이 먹지 않는다.
    _win.advancedBox.setChecked(True)
    _win.alertResetCapBtn.click()
    ck("클릭 시그널이 핸들러에 연결돼 있다", _win._router.calls == 3,
       str(_win._router.calls))
    _win.advancedBox.setChecked(False)
    _win._router = _sv4
    _win.alertLog.clear()

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

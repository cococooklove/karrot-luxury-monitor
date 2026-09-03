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

# ── 시작하자마자 저장된 매물을 그린다 ──
# watch.db 는 재시작에도 남는다(watch 테이블엔 DELETE 가 없다). 그런데 표를
# 채우는 트리거가 전부 이벤트(필터 클릭·신규 매칭·스윕 완료)뿐이라, 앱을 켜면
# 빈 표가 뜨고 감시를 시작해 최대 30분(야간)을 기다려야 채워졌다. 사용자
# 눈에는 매물이 사라진 것으로 보인다.
ck("시작 시 매물 표를 채운다",
   "_refresh_listing_table" in m.MainWindow._build_alert_tab.__code__.co_names,
   "탭을 세울 때 호출되지 않음")

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
    # 인자 없이 뜨면 매물 감시다(3탭 합본 모드는 없앴다). 감시는 조건·결과·설정
    # 세 탭으로 나뉜다 — 한 탭에 접이식 네 개로 쌓였던 동안 설정이 세 곳에 흩어졌다.
    ck("기본은 매물 감시 4탭", _win.tabs.count() == 4, str(titles))
    ck("탭 이름", titles == ["조건", "결과", "에뮬레이터", "설정"], str(titles))
    ck("첫 화면은 결과", _win.tabs.tabText(_win.tabs.currentIndex()) == "결과",
       _win.tabs.tabText(_win.tabs.currentIndex()))
    ck("감시 토글 존재", hasattr(_win, "watchToggleBtn"))
    ck("고급 패널 존재", hasattr(_win, "advancedBox"))
    ck("고급 패널 접힘",
       hasattr(_win, "advancedBox") and _win.advancedBox.isChecked() is False)
    if hasattr(_win, "advancedBox"):
        # qt_ 내부 위젯(콤보 팝업 스크롤 컨테이너 등)은 Qt 가 관리한다 — 제외.
        def _kept_hidden(k):
            """조건표로 옮겨간 옛 입력들 — 펼쳐도 안 보이는 게 맞다."""
            while k is not None and k is not _win.advancedBox:
                if getattr(k, "_keepHidden", False):
                    return True
                k = k.parentWidget()
            return False

        _kids = [k for k in _win.advancedBox.findChildren(_QW.QWidget)
                 if not k.objectName().startswith("qt_") and not _kept_hidden(k)]
        # 체크 해제는 자식을 비활성화만 한다 — 실제로 접혔는지(숨겨졌는지) 본다.
        ck("고급 자식 숨김", _kids and all(k.isHidden() for k in _kids),
           f"{sum(1 for k in _kids if k.isHidden())}/{len(_kids)}")
        _win.advancedBox.setChecked(True)
        ck("펼치면 다시 보임", not any(k.isHidden() for k in _kids))
        # 지역 훑기 상자를 없앴다 — 펼쳐도 지역 트리·전국 체크만 보이고
        # 휴식·지역 간·레인·주기·커버 스핀박스는 안 보인다.
        # isHidden 은 자기 자신에 hide 를 불렀을 때만 참이다 — 숨긴 것은
        # 컨테이너라 isVisibleTo(고급) 로 본다.
        _ab = _win.areaBox
        ck("펼쳐도 튜닝 스핀박스는 숨김",
           not any(w.isVisibleTo(_ab) for w in (
               _win.autoRestMin, _win.autoGapMin, _win.autoLanes,
               _win.alertPollInterval, _win.alertCoverMode)))
        ck("지역 트리·전국 체크는 보임",
           _win.autoAreaTree.isVisibleTo(_ab) and _win.autoNationwide.isVisibleTo(_ab))
        ck("'지역 훑기' 상자 없음",
           not any(b.title() == "지역 훑기"
                   for b in _win.areaBox.findChildren(_QW.QGroupBox)))
        _win.advancedBox.setChecked(False)
    # ── 상태 한 줄 (결과 탭에 누를 것은 감시 시작뿐) ──
    ck("상태칩 버튼·현황 상자 없음",
       not hasattr(_win, "_chips") and not hasattr(_win, "on_chip_clicked")
       and not hasattr(_win, "dashBox"))
    ck("상태줄은 라벨", isinstance(_win.statusLine, _QW.QLabel))

    def _tab_of(wdg):
        for _i in range(_win.tabs.count()):
            if wdg in _win.tabs.widget(_i).findChildren(_QW.QWidget):
                return _win.tabs.tabText(_i)
        return None
    _rp = next(_win.tabs.widget(_i) for _i in range(_win.tabs.count())
               if _win.tabs.tabText(_i) == "결과")
    _btns = [b for b in _rp.findChildren(_QW.QPushButton)
             if b.objectName() != "filterChip"]
    ck("결과 탭 버튼은 감시 시작 하나", _btns == [_win.watchToggleBtn],
       str([b.text() for b in _btns]))
    ck("커버 모드·주기 위젯은 살아 있되 숨김",
       not _win.alertCoverMode.isVisibleTo(_win.areaBox)
       and not _win.alertPollInterval.isVisibleTo(_win.areaBox))
    _win.advancedBox.setChecked(False)
    # 상태줄 문구는 헬스 갱신이 채운다(자격증명 없어도 크래시 없이 값이 바뀐다).
    _win._refresh_alert_health()
    _st = _win.statusLine.text()
    ck("헬스 갱신이 상태줄을 채운다",
       all(k in _st for k in ("토큰", "계정", "커버리지", "폴링", "텔레그램")), _st)
    _win._update_coverage([("a", "역삼동", 39), ("b", "정자동", 39)])
    ck("커버 조회가 상태줄 %를 채운다", "커버리지 1%" in _win.statusLine.text(),
       _win.statusLine.text())

    ck("감시 토글 핸들러", callable(getattr(_win, "on_watch_toggle", None)))
    ck("라우터 속성", hasattr(_win, "_router"))
    ck("컨트롤러 속성", hasattr(_win, "_supervisor"))
    ck("스윕 결과 핸들러", callable(getattr(_win, "_on_sweep_found", None)))
    ck("스윕 cfg 조립", callable(getattr(_win, "_auto_cfg_base", None))
       and callable(getattr(_win, "_sweep_cfg", None)))
    for _attr in ("autoAreaTree", "autoExtra", "autoExclude", "autoMin",
                  "autoMax", "autoDays", "autoRestMin", "autoRestMax",
                  "autoGapMin", "autoGapMax", "autoLanes", "autoAccountsBtn"):
        ck(f"스윕 설정 이사: {_attr}", hasattr(_win, _attr))
    # 알림 설정은 다이얼로그가 아니라 설정 탭의 폼이다.
    ck("알림 폼 위젯", all(hasattr(_win, a) for a in (
        "notifyBox", "notifyToken", "notifyChat", "notifySheet", "notifyCred",
        "notifyTestBtn", "notifySaveBtn", "notifyResult")))
    ck("알림 다이얼로그 제거", not hasattr(_win, "autoNotifyBtn")
       and not hasattr(_win, "on_auto_notify_clicked"))
    # 토큰 갱신은 스위치가 아니다 — 유일한 갱신 경로라 항상 켜져 있다.
    ck("토큰 갱신 체크박스 제거", not hasattr(_win, "autoTokenRefresh"))
    ck("스윕 cfg 는 토큰 공급자를 늘 단다",
       _win._auto_cfg_base().get("token_provider") is not None
       and _win._auto_cfg_base().get("stabilize") is True)
    ck("프록시 목록 버튼은 계정+프록시 창 안으로", not hasattr(_win, "autoProxyViewBtn"))
    for _attr in ("autoKeyword", "autoStartBtn", "autoStatus", "autoProgress",
                  "autoTable", "autoLog"):
        ck(f"안 옮긴 위젯 제거: {_attr}", not hasattr(_win, _attr))
    ck("자동폴링 버튼 제거", not hasattr(_win, "alertAutoPollBtn"))
    ck("단일계정 일괄등록 제거", not hasattr(_win, "alertBulkBtn")
       and not hasattr(_win, "on_alert_bulk"))
    ck("엑셀 조건 캐시 제거", not hasattr(_win, "auto_conditions"))
    # 엑셀 버튼은 조건 탭 하나로 모았다 — 등록용/알림용이 따로 있는 줄
    # 알고 같은 시트를 양쪽에 넣는 일이 반복됐다.
    ck("지역 상자 엑셀 버튼 제거", not hasattr(_win, "autoExcelBtn")
       and not hasattr(_win, "on_auto_excel_clicked"))
    ck("조건표 엑셀 버튼은 조건 탭에", hasattr(_win, "rulesImportBtn")
       and callable(getattr(_win, "on_rules_import_excel", None)))

    # ── 조건표 엑셀 → 브랜드 등록 (워크북 안 연다) ──
    class _FakeRouter:
        def __init__(self):
            self.calls = []

        def add_many(self, keywords, min_price=None, max_price=None,
                     exclude=None, core_only=False, log=None,
                     extra=None, days=None, replace_cond=False):
            self.calls.append((list(keywords), min_price, max_price,
                               list(exclude or []), core_only,
                               list(extra or []), days, replace_cond))
            return [{"keyword": k, "route": "app", "reason": "앱 알림 등록"}
                    for k in keywords]

    from daangn_ext.alert_rules import brands, parse_rule_rows
    _rows = [("키워드", "최소가격", "최대가격", "제외", "끌올일수"),
             ("샤넬 클래식 미디움", 500000, 3000000, "레플", 7),
             ("샤넬 보이백", 1000000, 4000000, "", 7),
             ("구찌 마몬트", 500000, 3000000, "레플", 30),
             ("롤렉스", 1000000, None, "", None),
             ("", None, None, "", None)]                   # 빈 키워드 = 버림
    _rules, _errs = parse_rule_rows(_rows)
    _bs = brands(_rules)
    ck("브랜드는 키워드 첫 어절, 중복 제거",
       _bs == ["샤넬", "구찌", "롤렉스"], str(_bs))
    ck("빈 키워드 버림", len(_rules) == 4, str([r.keyword for r in _rules]))

    _groups = m.brand_register_groups(_bs, _rules)
    ck("끌올일수가 다르면 그룹이 갈린다", len(_groups) == 3, str(_groups))
    ck("같은 끌올일수는 한 그룹",
       sorted(k for ks, d in _groups if d == 7 for k in ks) == ["샤넬"],
       str(_groups))
    ck("끌올일수 없는 브랜드는 days=None 그룹",
       any(d is None and ks == ["롤렉스"] for ks, d in _groups), str(_groups))

    # register() 가 도는 그대로 — 가격·제외는 넘기지 않는다.
    _fake = _FakeRouter()
    _res = []
    for _ks, _d in _groups:
        _res.extend(_fake.add_many(_ks, None, None, None, core_only=True,
                                   log=lambda m: None, days=_d,
                                   replace_cond=True))
    ck("브랜드만 라우터로 간다",
       sorted(k for c in _fake.calls for k in c[0]) == ["구찌", "롤렉스", "샤넬"],
       str(_fake.calls))
    ck("가격·제외·추가는 안 넘긴다 — 당근 서버가 먼저 자르면 조건표가 볼 매물이 없다",
       all(c[1] is None and c[2] is None and c[3] == [] and c[5] == []
           for c in _fake.calls), str(_fake.calls))
    ck("core_only 전달", all(c[4] is True for c in _fake.calls))
    ck("끌올일수는 그대로 간다",
       sorted((c[0][0], c[6]) for c in _fake.calls)
       == [("구찌", 30), ("롤렉스", None), ("샤넬", 7)], str(_fake.calls))
    ck("엑셀 경로만 replace_cond=True", all(c[7] is True for c in _fake.calls))
    ck("라우터 결과를 돌려준다", len(_res) == 3, str(_res))
    ck("브랜드가 없으면 라우터를 아예 안 부른다",
       m.brand_register_groups([], []) == [])

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
        # 앱 스윕은 기본 꺼짐(설정)이고 꺼지면 재동기화가 앞에서 끝난다.
        # 이 리그가 재는 것은 그 뒤의 판정이므로 스위치는 켜 놓는다.
        _win._load_alert_settings = lambda: {"sweep_app_enabled": True}
        _win._app_sweep_off_logged = False
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
    # 앱 스윕이 꺼져 있으면 재동기화는 스위치 검사에서 끝난다(헤드리스와 같다).
    _off_calls = []
    _win._sweep_queue = _FakeQueue(["샤넬"])
    _win._supervisor = _FakeSupervisor(True)
    _win._sweep_kws = None
    _win.auto_monitor = None
    _win._start_search_sweep = lambda: _off_calls.append("start")
    _win._stop_search_sweep = lambda: _off_calls.append("stop")
    _win._load_alert_settings = lambda: {"sweep_app_enabled": False}
    _win._app_sweep_off_logged = False
    _win._resync_search_sweep()
    ck("앱 스윕 꺼짐이면 재동기화는 시작도 정지도 안 한다",
       _off_calls == [], str(_off_calls))
    # 인스턴스 속성으로 덮어쓴 메서드는 지워서 클래스 구현으로 되돌린다.
    for _n in ("_start_search_sweep", "_stop_search_sweep",
               "_load_alert_settings"):
        _win.__dict__.pop(_n, None)
    (_win._sweep_queue, _win._supervisor, _win._sweep_kws,
     _win.auto_monitor) = _saved
    ck("메서드 원복", _win._start_search_sweep.__func__ is
       m.MainWindow._start_search_sweep)

    _seen = []
    _sv_router = _win._router
    _win._resync_search_sweep = lambda: _seen.append("resync")
    # 폴링은 이제 _alert_run 워커로 나간다(씨딩·승격이 그 안에 들어갔다).
    # label·queue 같은 인자가 늘어도 스텁이 먼저 죽지 않게 **kw 로 받는다.
    _win._alert_run = lambda fn, on_done=None, **kw: _seen.append("poll")
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
    ck("등록 표 열 = ALERT_COLS", getattr(_win, "alertTable", None) is not None
       and _win.alertTable.columnCount() == len(m.ALERT_COLS),
       str(m.ALERT_COLS))

    # ── 화면 순서: 매일 보는 매물 표가 위, 설정은 접어서 아래 ──
    from PyQt6.QtCore import QPoint as _QPoint
    from PyQt6 import QtWidgets as _QtW

    def _y(wdg):
        """창 좌표계에서의 세로 위치."""
        return wdg.mapTo(_win, _QPoint(0, 0)).y()
    # 탭 배치 — 결과(매물)·조건(조건표·지역·등록 상태)·설정(알림·계정·고급)
    ck("매물 표는 결과 탭", _tab_of(_win.listingTable) == "결과")
    ck("조건표·지역·등록 표는 조건 탭",
       all(_tab_of(x) == "조건" for x in (
           _win.rulesApplyBtn, _win.autoAreaTree, _win.alertTable)))
    ck("알림 폼·계정 버튼·전체 삭제는 설정 탭",
       all(_tab_of(x) == "설정" for x in (
           _win.notifyToken, _win.autoAccountsBtn, _win.alertDelAllBtn)))
    ck("감시 시작 버튼이 매물 표보다 위",
       _y(_win.watchToggleBtn) < _y(_win.listingTable))
    # 제 탭이 생긴 상자는 펴 두고, 되돌리기(고급)만 접는다.
    for _n, _title, _open in (("condBox", "감시 조건", True),
                              ("areaBox", "훑을 지역", True),
                              ("regBox", "당근 서버 등록 상태", True),
                              ("advancedBox", "고급", False), ("logBox", "로그", True)):
        _b = getattr(_win, _n, None)
        ck(f"접이식 {_title} ({'펼침' if _open else '접힘'})",
           _b is not None and _b.isCheckable() and _b.isChecked() is _open, str(_b))
    _win.condBox.setChecked(False)
    ck("접으면 높이도 접힌다",
       _win.condBox.maximumHeight() < 100, str(_win.condBox.maximumHeight()))
    _win.condBox.setChecked(True)
    # 창을 띄우지 않은 테스트라 isVisible() 은 항상 False 다 — 숨김 플래그를 본다.
    ck("펼치면 안이 보인다", not _win.rulesSummary.isHidden()
       and _win.condBox.maximumHeight() > 1000,
       f"hidden={_win.rulesSummary.isHidden()} / {_win.condBox.maximumHeight()}")
    ck("id 열은 감춘다", _win.alertTable.isColumnHidden(m.ALERT_COL_ID))
    # 전체 삭제는 표 옆에 두지 않는다 — 실서버서 등록 21건이 그렇게 날아갔다.
    ck("전체 삭제는 고급 안에",
       _win.alertDelAllBtn in _win.advancedBox.findChildren(_QtW.QPushButton))
    # 등록 표·삭제는 '시스템이 당근에 올린 결과'다. 클라가 넣은 조건과 같은
    # 자리에 두면 둘을 같은 것으로 읽는다.
    ck("등록 표는 조건 탭의 제 상자 안에(조건 상자와 별개)",
       _win.alertTable in _win.regBox.findChildren(_QtW.QWidget)
       and _win.alertTable not in _win.condBox.findChildren(_QtW.QWidget))
    # 삭제 경로는 전체 삭제 하나다. 낱개 삭제와 수동 등록 폼은 조건표와
    # 어긋나는 뒷문이라 없앴다.
    ck("낱개 삭제·수동 등록 폼 제거",
       not hasattr(_win, "alertDelBtn") and not hasattr(_win, "alertAddBtn")
       and not hasattr(_win, "alertKeyword"))
    # 조건은 화면 표에 바로 적는다 — 엑셀은 표를 채우는 보조 경로다.
    # 열기·다시 읽기(파일 원본 전제)가 되살아나면 여기서 잡는다.
    ck("감시 조건 안에는 표·적용·요약·엑셀 불러오기",
       isinstance(getattr(_win, "rulesGrid", None), m.RuleGrid)
       and _win.rulesGrid in _win.condBox.findChildren(_QtW.QWidget)
       and _win.rulesSummary in _win.condBox.findChildren(_QtW.QLabel)
       and all(b in _win.condBox.findChildren(_QtW.QPushButton)
               for b in (_win.rulesApplyBtn, _win.rulesImportBtn)))
    ck("엑셀 열기·다시 읽기 없음",
       not hasattr(_win, "rulesOpenBtn") and not hasattr(_win, "rulesReloadBtn"))
    # 우측 상단 판 표시 — 판·설치 시각만. '최신' 표시는 없다(틀릴 수 있어서).
    ck("헤더 우측에 판 라벨", _win.versionLabel.text().startswith(("v ", "판 미상")),
       _win.versionLabel.text())
    ck("'최신' 표시 없음", "최신" not in _win.versionLabel.text(), _win.versionLabel.text())
    ck("조건 수가 섹션 제목에 보인다", "조건" in _win.condBox.title(),
       _win.condBox.title())
    ck("조건이 없으면 그 사실을 말한다",
       "없음" in _win.condBox.title() or "0개" in _win.condBox.title(),
       _win.condBox.title())
    # 폴링·커버 계산은 감시 시작이 하고, 계정 현황·진단·텔레그램 테스트는
    # 각자의 창 안에 있다. 고급 패널에 남는 버튼은 전체 삭제 하나다.
    ck("고급 패널 버튼은 전체 삭제 하나",
       _win.alertDelAllBtn in _win.advancedBox.findChildren(_QtW.QPushButton)
       and not any(hasattr(_win, a) for a in (
           "alertPollBtn", "alertPollAllBtn", "alertCoverageBtn", "alertFleetBtn",
           "alertTgTestBtn", "alertResetCapBtn")))
    ck("무인 스위치는 체크박스가 아니라 기본값",
       not any(hasattr(_win, a) for a in (
           "alertAutoStartChk", "alertBootChk", "alertCrashChk", "alertNightChk"))
       and _win._alert_setting("autostart") and _win._alert_setting("night")
       and _win._alert_setting("crash_recover"))
    # 등록 경로는 조건표 하나다. 브랜드만 등록해 놓고 조건표가 없으면
    # 모델·가격대와 무관하게 브랜드 전 매물이 알림으로 쏟아진다.
    ck("일괄등록 버튼 제거", not hasattr(_win, "alertBulkAllBtn")
       and not hasattr(_win, "on_alert_bulk_all"))
    ck("등록은 [조건 적용] 하나", callable(getattr(_win, "on_rules_apply", None))
       and _win.rulesApplyBtn.text().startswith("조건 적용")
       and not hasattr(_win, "on_alert_rules_excel"))

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
    # 씨딩은 조건표 브랜드만 인정한다 — 조건표가 진실이고, 없으면 아무것도 안 인정.
    from daangn_ext.alert_rules import AlertRule as _AR, RuleTable as _RT

    class _RulesStub:
        def __init__(self, t): self.t = t
        def get(self): return self.t
    _sv_rules = _win._alert_rules
    _win._alert_rules = _RulesStub(_RT([_AR(keyword="샤넬 클래식", brand="샤넬"),
                                        _AR(keyword="루이비통 네버풀", brand="루이비통")]))
    _win._alert_populate({"user_keywords": [{"keyword": "샤넬", "id": 1},
                                            {"keyword": "루이비통", "id": 2},
                                            {"keyword": "구찌", "id": 9}]})
    _cap = _rS.capacity()
    ck("첫 실행에 서버 등록분 중 조건표 브랜드만 슬롯으로 인식", _cap["used"] == 2, str(_cap))
    ck("조건표에 없는 서버 등록(구찌)은 인정 안 함",
       "구찌" not in [r["keyword"] for r in _rS.routes()], str(_rS.routes()))
    ck("씨딩 사실을 로그에 남긴다",
       "앱 슬롯으로 인식" in _win.alertLog.toPlainText(),
       _win.alertLog.toPlainText().strip()[:100])
    ck("표의 경로가 '-' 가 아니다",
       _win.alertTable.item(0, m.ALERT_COL_ROUTE).text() != "-",
       _win.alertTable.item(0, m.ALERT_COL_ROUTE).text())
    # 두 번째 그리기는 씨딩하지 않는다
    _win.alertLog.clear()
    _win._alert_populate({"user_keywords": [{"keyword": "에르메스", "id": 3}]})
    ck("두 번째 그리기는 씨딩 안 함", _rS.capacity()["used"] == 2,
       str(_rS.capacity()))
    ck("두 번째는 씨딩 로그 없음",
       "앱 슬롯으로 인식" not in _win.alertLog.toPlainText())
    _win._router, _win._sweep_queue = _svr, _svq
    _win._alert_rules = _sv_rules
    _win.alertTable.setRowCount(0)
    _win.alertLog.clear()

    # ── 셀 색이 실제로 그려진다 (스타일시트 함정) ──
    # ::item 에 color/border 를 주면 setForeground/setBackground 가 조용히
    # 무시된다. 아이템 속성이 아니라 픽셀로 확인해야 이 회귀를 잡는다.
    from PyQt6 import QtGui as _QtG
    _rm = _win._routes_map
    _win._router = None
    _win._routes_map = lambda: {"구찌": {"keyword": "구찌", "route": "app", "cond": {}}}
    _win._sweep_queue = _FakeQueue([])
    _win._alert_populate({"user_keywords": []})
    _img = _win.alertTable.grab().toImage()
    _want = _QtG.QColor(m.REG_MISSING_BG)
    _hit = sum(1 for _x in range(0, _img.width(), 3) for _y in range(0, _img.height(), 3)
               if _img.pixelColor(_x, _y) == _want)
    ck("미등록 줄의 붉은 바탕이 픽셀로 보인다", _hit > 50, f"{_hit}px")
    _win._routes_map, _win._sweep_queue = _rm, _svq
    _win.alertTable.setRowCount(0)
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
    # 조건표가 없으면 아무것도 알리지 않는 것이 계약이다 — 여기서 보는 건
    # 중복 제거이므로 조건표에 걸리는 제목을 준다.
    from daangn_ext.alert_rules import AlertRule as _AR2, RuleTable as _RT2

    class _RulesStub2:
        def __init__(self, t): self.t = t
        def get(self): return self.t
    _sv_rules2 = _win._alert_rules
    _win._alert_rules = _RulesStub2(_RT2([_AR2(keyword="샤넬", brand="샤넬")]))
    _win._match_populate([{"article_id": "777", "id": "inbox-1", "title": "샤넬 백"},
                          {"article_id": "888", "id": "inbox-2", "title": "샤넬 지갑"},
                          {"title": "샤넬 — 키 없음"}])
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
    _win._match_populate([{"article_id": "999", "id": "inbox-3", "title": "샤넬 백"}])
    _win._match_populate([{"article_id": "999", "id": "inbox-3", "title": "샤넬 백"}])
    ck("저장소 없어도 한 번만 알린다", len(_notified) == 1, str(_notified))
    _win._alert_rules = _sv_rules2
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
    ck("전국 훑기도 지역 상자 안",
       _win.autoNationwide in _win.areaBox.findChildren(_QW.QWidget))
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
    # 앱 스윕은 기본 꺼짐(설정) — 이 블록은 되살리기 상한 자체를 재는 것이라
    # 켜진 걸로 두고 잰다. _start_search_sweep 의 스위치 검사를 우회한다.
    _win._load_alert_settings = lambda: {"sweep_app_enabled": True}
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
    _win.__dict__.pop("_load_alert_settings", None)
    _win.auto_monitor = None
    (_win._supervisor, _win._sweep_queue, _win.auto_monitor,
     _win._sweep_kws) = _sv3
    _win._sweep_revives = 0
    _win.alertLog.clear()

    print("=== 관측 상한 초기화 — GUI 에선 전체 삭제가 함께 되돌린다 ===")
    ck("별도 초기화 버튼은 없다", not hasattr(_win, "alertResetCapBtn")
       and not hasattr(_win, "on_reset_cap_clicked"))

    class _CapRouter:
        def __init__(self, has):
            self.has = has
            self.calls = 0

        def routes(self):
            return []

        def remove(self, kw):
            pass

        def reset_observed_cap(self, log=None):
            self.calls += 1
            if not self.has:
                return False
            self.has = False
            return True

    _sv4 = (_win._router, m.ask_yes_no)
    _win._router = _CapRouter(True)
    _win.alertLog.clear()
    m.ask_yes_no = lambda *a, **k: True          # 확인창은 '예'
    _sv4_run = _win._alert_run
    _win._alert_run = lambda *a, **k: True       # 서버 삭제는 네트워크 — 건너뛴다
    try:
        _win.on_alert_delete_all()
    finally:
        _win._alert_run = _sv4_run
    ck("전체 삭제가 관측치를 되돌린다", _win._router.calls == 1, str(_win._router.calls))
    ck("되돌림 로그", "초기화" in _win.alertLog.toPlainText(),
       _win.alertLog.toPlainText().strip()[:120])
    _win._router, m.ask_yes_no = _sv4
    _win.alertLog.clear()

    # ── 웹 동 피드 발굴(계정 0) 배선 ──
    ck("피드 설정 위젯", all(hasattr(_win, a) for a in (
        "feedEnabledChk", "feedCat31", "feedCat14", "feedCat5", "feedProxies", "feedRps", "feedRestMin", "sweepAppChk")))
    ck("피드 기본값: 켬·31·14·rps 1·휴식 2·앱 스윕 꺼짐",
       _win.feedEnabledChk.isChecked() and _win.feedCat31.isChecked() and _win.feedCat14.isChecked()
       and not _win.feedCat5.isChecked() and _win.feedRps.value() == 1.0 and _win.feedRestMin.value() == 2
       and not _win.sweepAppChk.isChecked())
    p = _win._feed_settings_patch()
    ck("설정 패치 키", set(p) == {"feed_enabled", "feed_categories", "feed_proxies", "feed_rps", "feed_rest_min", "sweep_app_enabled"}, str(sorted(p)))
    ck("피드 수명 메서드", all(callable(getattr(_win, a, None)) for a in ("_start_feed", "_stop_feed", "_on_feed_found")))
    ck("컨트롤러가 피드를 같이 켜고 끈다",
       _win._supervisor is not None and _win._supervisor._start_feed == _win._start_feed
       and _win._supervisor._stop_feed == _win._stop_feed)
    ck("피드 어댑터 모듈", __import__("daangn.feed_monitor", fromlist=["FeedMonitor"]).FeedMonitor is not None)
    ck("상태줄에 feed 항목", "feed" in _win.STATUS_ORDER)
    _win.feed_monitor = None
    try:
        _win._dispose_feed_monitor()
        _fdm_ok = True
    except Exception:
        _fdm_ok = False
    ck("피드 모니터 폐기(빈 상태에서도 안 죽는다)",
       callable(getattr(_win, "_dispose_feed_monitor", None)) and _fdm_ok)

    # ── 피드·앱스윕 수명: 로그 래치·백오프·종료 ──
    # 폴링 틱마다 같은 안내가 쌓이면 로그를 못 읽는다. 죽은 프록시로 틱마다
    # 재시작하면 로그만 쌓이고 아무것도 안 산다.
    print("=== 피드·앱스윕 수명 ===")
    import inspect as _insp
    import time as _time2
    import types as _types2

    ck("closeEvent 가 피드 스레드도 세운다",
       "feed_monitor" in _insp.getsource(m.MainWindow.closeEvent))

    def _rules_of(n):
        return type("_RC", (), {"get": staticmethod(
            lambda: type("_RT", (), {"rules": [1] * n})())})()

    _sv6 = (_win._alog, _win._alert_rules, _win.feed_monitor,
            _win._supervisor, _win.auto_monitor,
            _win.__dict__.get("_load_alert_settings"))
    _flogs = []
    _win._alog = _flogs.append
    _win._alert_rules = _rules_of(0)
    _win._load_alert_settings = lambda: {}
    _win.feed_monitor = None
    _win._start_feed(); _win._start_feed()
    ck("조건표 비었다는 안내는 한 번만",
       sum(1 for x in _flogs if "조건표" in x) == 1, str(_flogs))
    ck("조건표가 비면 모니터를 안 만든다", _win.feed_monitor is None)
    _flogs.clear()
    _win._load_alert_settings = lambda: {"feed_enabled": False}
    _win._start_feed(); _win._start_feed()
    ck("설정에서 꺼졌다는 안내도 한 번만",
       sum(1 for x in _flogs if "꺼져" in x) == 1, str(_flogs))

    # 프록시 전멸 백오프 — 죽은 엔진을 기억하고 30분 물러선다.
    _flogs.clear()
    _win._load_alert_settings = lambda: {}
    _win._alert_rules = _rules_of(2)
    _win._feed_last_engine = _types2.SimpleNamespace(
        stop_reason="proxies", stopped_at=_time2.monotonic())
    _win._start_feed(); _win._start_feed(); _win._start_feed()
    ck("프록시 전멸 뒤에는 피드를 다시 띄우지 않는다", _win.feed_monitor is None)
    ck("백오프 안내도 한 번만",
       sum(1 for x in _flogs if "프록시" in x) == 1, str(_flogs))
    ck("백오프 판정은 헤드리스와 같은 함수",
       "feed_proxy_backoff_left" in m.MainWindow._start_feed.__code__.co_names)
    _win._feed_last_engine = None

    # 프록시 사망 상태줄은 경고색으로 — 상태 문자열 하나가 두 런타임의 계약이다.
    from daangn.feed_sweep import PROXY_DEAD_STATUS as _PDS
    _win._on_feed_status(_PDS)
    ck("프록시 사망은 warn", _win._status["feed"] == (_PDS, "warn"),
       str(_win._status["feed"]))
    _win._on_feed_status("피드 3/10 · 역삼동")
    ck("보통 진행은 ok", _win._status["feed"][1] == "ok", str(_win._status["feed"]))

    # 앱 스윕이 꺼져 있으면: 전이마다 한 번만 말하고, 시작 판정까지 가지 않는다.
    class _RunAM:
        def __init__(self):
            self.stopped = 0

        def isRunning(self):
            return True

        def stop(self):
            self.stopped += 1

    _flogs.clear()
    _win._supervisor = _FakeSup()
    _win._sweep_queue = _FakeQ2(["샤넬"])
    _win.auto_monitor = None
    _win._sweep_kws = None
    _win._app_sweep_off_logged = False
    _win._load_alert_settings = lambda: {"sweep_app_enabled": False}
    for _ in range(3):
        _win._resync_search_sweep()
    ck("앱 스윕 꺼짐 안내는 한 번만",
       sum(1 for x in _flogs if "앱 스윕 꺼짐" in x) == 1, str(_flogs))
    ck("꺼져 있으면 시작 판정까지 가지 않는다",
       _win.auto_monitor is None and not any("시작" in x for x in _flogs), str(_flogs))
    _win.auto_monitor = _RunAM()
    _win._resync_search_sweep()
    ck("꺼졌는데 돌고 있으면 세운다(헤드리스와 같은 규칙)",
       _win.auto_monitor.stopped == 1, str(_win.auto_monitor.stopped))
    _win.auto_monitor = None
    _flogs.clear()
    ck("다시 켜지면 게이트가 열린다", _win._app_sweep_gate({"sweep_app_enabled": True}) is True)
    ck("켜짐→꺼짐 전이면 다시 한 번 말한다",
       _win._app_sweep_gate({}) is False
       and sum(1 for x in _flogs if "앱 스윕 꺼짐" in x) == 1, str(_flogs))

    # 폴링 틱이 죽은 피드를 되살린다(백오프·래치는 _start_feed 가 본다).
    _tick_src = _insp.getsource(m.MainWindow._auto_poll_tick)
    ck("폴링 틱이 피드도 재동기화한다", "_resync_feed" in _tick_src)
    _flogs.clear()
    _win._alert_rules = _rules_of(0)
    _win.feed_monitor = None
    _win.__dict__["_feed_logged"] = set()
    _win._resync_feed()
    ck("감시 중 피드가 죽어 있으면 다시 띄운다(조건표가 비어 여기서 멈춘다)",
       any("조건표" in x for x in _flogs), str(_flogs))
    _win._supervisor = None
    _flogs.clear()
    _win._resync_feed()
    ck("감시가 꺼져 있으면 손대지 않는다", _flogs == [], str(_flogs))

    (_win._alog, _win._alert_rules, _win.feed_monitor,
     _win._supervisor, _win.auto_monitor, _sv6_ls) = _sv6
    if _sv6_ls is None:
        _win.__dict__.pop("_load_alert_settings", None)
    else:
        _win._load_alert_settings = _sv6_ls

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

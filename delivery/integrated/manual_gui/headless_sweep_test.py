"""헤드리스 런타임의 검색 스윕 배선 확인 — 진짜 스레드도 네트워크도 안 쓴다.

    python headless_sweep_test.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, app_dir)
os.chdir(app_dir)

import main as m

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


# ── 가짜들 ──────────────────────────────────────────────────────────────
class FakeQueue:
    def __init__(self, kws):
        self.set(kws)

    def set(self, kws):
        self._e = [{"keyword": k, "min": None, "max": None, "exclude": []}
                   for k in kws]

    def keywords(self):
        return [e["keyword"] for e in self._e]

    def entries(self):
        return [dict(e) for e in self._e]

    def __len__(self):
        return len(self._e)


class FakeEngine:
    def __init__(self, cfg, on_log=None, on_found=None):
        self.cfg = cfg
        self.on_log = on_log
        self.on_found = on_found
        self.stopped = False

    def run(self):
        pass

    def stop(self):
        self.stopped = True


class FakeThread:
    """살아 있음 여부를 테스트가 조종한다. 엔진이 stop 되면 죽은 것으로 본다
    (진짜 스레드도 stop 플래그를 보고 run 을 빠져나온다)."""
    def __init__(self, target, alive=True, engine=None):
        self.target = target
        self._alive = alive
        self.engine = engine
        self.started = False
        self.joined = None

    def start(self):
        self.started = True

    def is_alive(self):
        if self.engine is not None and self.engine.stopped:
            return False
        return self._alive

    def join(self, t=None):
        self.joined = t


def runner(kws, alive_after_start=True):
    """HeadlessSweepRunner 를 가짜 엔진·스레드로 조립한다."""
    q = FakeQueue(kws)
    logs, found = [], []
    made = {"engines": [], "threads": []}

    def ef(cfg, on_log, on_found):
        e = FakeEngine(cfg, on_log, on_found)
        made["engines"].append(e)
        return e

    def tf(target):
        t = FakeThread(target, alive=alive_after_start,
                       engine=made["engines"][-1] if made["engines"] else None)
        made["threads"].append(t)
        return t

    def cfg():
        return m.headless_sweep_cfg({}, q.entries(), {})

    r = m.HeadlessSweepRunner(q, cfg, logs.append, found.append,
                              engine_factory=ef, thread_factory=tf)
    return r, q, logs, found, made


print("=== A. sweep_resync_action (GUI·헤드리스 공용 판정) ===")
ck("안 떠 있고 큐가 차면 start",
   m.sweep_resync_action({"샤넬"}, None, False) == "start")
ck("안 떠 있고 큐도 비면 무동작",
   m.sweep_resync_action([], None, False) == "")
ck("정지 중(스레드 생존)이면 start 안 함",
   m.sweep_resync_action({"샤넬"}, None, True) == "")
ck("같고 살아 있으면 무동작",
   m.sweep_resync_action({"샤넬"}, {"샤넬"}, True) == "")
ck("같은데 죽었으면 revive",
   m.sweep_resync_action({"샤넬"}, {"샤넬"}, False) == "revive")
ck("빈 집합끼리 같으면 죽었어도 무동작",
   m.sweep_resync_action([], set(), False) == "")
ck("키워드 늘면 restart",
   m.sweep_resync_action({"샤넬", "구찌"}, {"샤넬"}, True) == "restart")
ck("승격으로 줄면 restart",
   m.sweep_resync_action({"샤넬"}, {"샤넬", "구찌"}, True) == "restart")
ck("큐가 비면 restart(정지만)",
   m.sweep_resync_action([], {"샤넬"}, True) == "restart")

print("=== B. sweep_conditions ===")
E = [{"keyword": "샤넬", "min": 100, "max": None, "exclude": ["가품"]},
     {"keyword": "구찌", "min": None, "max": None, "exclude": []}]
c = m.sweep_conditions(E, extra=["빈티지"], exclude=["레플"],
                       min_price=50, max_price=900, days=7)
ck("조건 수", len(c) == 2, str(len(c)))
ck("엔트리 min 우선", c[0]["min"] == 100, str(c[0]))
ck("엔트리에 없으면 기본 min", c[1]["min"] == 50, str(c[1]))
ck("엔트리에 없으면 기본 max", c[0]["max"] == 900, str(c[0]))
ck("엔트리 exclude 우선", c[0]["exclude"] == ["가품"], str(c[0]))
ck("엔트리 exclude 비면 기본", c[1]["exclude"] == ["레플"], str(c[1]))
ck("엔트리에 없으면 기본 extra", all(x["extra"] == ["빈티지"] for x in c))
ck("엔트리에 없으면 기본 days", c[0]["days"] == 7)

# 엑셀 행별 추가키워드·끌올일수는 전역 패널값보다 우선해야 한다.
# exclude·min·max 는 이미 엔트리를 우선하는데 이 둘만 전역값에 덮여,
# 엑셀에 적은 행별 조건이 스윕에서 조용히 무시되고 있었다.
E2 = [{"keyword": "롤렉스", "min": None, "max": None, "exclude": [],
       "extra": ["정품"], "days": 30},
      {"keyword": "구찌", "min": None, "max": None, "exclude": []}]
c2 = m.sweep_conditions(E2, extra=["빈티지"], exclude=["레플"], days=7)
ck("엔트리 extra 우선", c2[0]["extra"] == ["정품"], str(c2[0]))
ck("엔트리 days 우선", c2[0]["days"] == 30, str(c2[0]))
ck("엔트리에 없으면 기본 extra 로 폴백", c2[1]["extra"] == ["빈티지"], str(c2[1]))
ck("엔트리에 없으면 기본 days 로 폴백", c2[1]["days"] == 7, str(c2[1]))
ck("빈 입력 → 빈 목록", m.sweep_conditions([]) == [])
ck("None → 빈 목록", m.sweep_conditions(None) == [])

print("=== C. sweep_keyword_for ===")
ck("제목에 든 키워드 선택",
   m.sweep_keyword_for({"title": "구찌 마몬트 지갑"}, ["샤넬", "구찌"]) == "구찌")
ck("없으면 첫 키워드",
   m.sweep_keyword_for({"title": "루이비통"}, ["샤넬", "구찌"]) == "샤넬")
ck("키워드 없으면 빈 문자열", m.sweep_keyword_for({"title": "x"}, []) == "")
ck("payload 없어도 안 죽음", m.sweep_keyword_for(None, ["샤넬"]) == "샤넬")

print("=== D. headless_sweep_cfg ===")
# 운영 헤드리스는 수확 토큰 경로(앱API)다 — --no-harvest 만 예외. 예산 판정이 이걸 본다.
_TP = lambda: "t"
cfg = m.headless_sweep_cfg({}, E, {}, token_provider=_TP)
ck("conditions 채움", len(cfg["conditions"]) == 2)
ck("기본 휴식 30~90", (cfg["rest_min"], cfg["rest_max"]) == (30, 90), str(cfg["rest_min"]))
ck("기본 지역간격 0.4~1.2",
   (cfg["gap_min"], cfg["gap_max"]) == (0.4, 1.2), str(cfg["gap_min"]))
ck("지역 미지정이어도 전국이 아니다", cfg["scope"] == "regions", cfg["scope"])
ck("지역 미지정 → 기본 지역",
   cfg["regions"] == m.default_sweep_regions("./OUT.json"), str(len(cfg["regions"])))
ck("db/out 경로는 GUI 와 같음",
   cfg["db_path"] == "./auto_seen.db" and cfg["out_json"] == "./OUT.json")
ck("token_provider 없으면 stabilize off",
   m.headless_sweep_cfg({}, E, {})["stabilize"] is False and cfg["stabilize"] is True)
cfg2 = m.headless_sweep_cfg(
    {"sweep_regions": ["6110"], "sweep_rest_min": 40, "sweep_days": 3,
     "sweep_min": 1000, "sweep_exclude": ["레플"]},
    E, {"tg_token": "T", "tg_chat": "C"},
    proxies=["p1"], token_provider=lambda: "tok")
ck("지역 지정 → regions", cfg2["scope"] == "regions" and cfg2["regions"] == ["6110"])
ck("설정 휴식 반영", cfg2["rest_min"] == 40)
ck("텔레그램 전달", (cfg2["tg_token"], cfg2["tg_chat"]) == ("T", "C"))
ck("프록시 전달", cfg2["proxies"] == ["p1"])
ck("token_provider 있으면 stabilize on", cfg2["stabilize"] is True)
ck("설정 min 은 엔트리에 없을 때만", cfg2["conditions"][1]["min"] == 1000)
ck("설정 days", cfg2["conditions"][0]["days"] == 3)
ck("이상한 값은 기본값으로",
   m.headless_sweep_cfg({"sweep_rest_min": "abc"}, E, {})["rest_min"] == 30)

print("=== E. HeadlessSweepRunner 수명 ===")
r, q, logs, found, made = runner(["샤넬", "구찌"])
ck("빈 큐면 시작 안 함", m.HeadlessSweepRunner(
    FakeQueue([]), lambda: m.headless_sweep_cfg({}, [], {}),
    logs.append, found.append,
    engine_factory=lambda *a: FakeEngine({}), thread_factory=FakeThread).start() is False)
ck("빈 큐 로그", "대기열이 비어" in logs[-1], logs[-1])

logs.clear()
ck("큐가 차면 시작", r.start() is True)
ck("스레드 start 호출", made["threads"][0].started is True)
ck("키워드 집합 기억", r.kws == {"샤넬", "구찌"}, str(r.kws))
ck("시작 로그", "시작 — 키워드 2개" in logs[-1], logs[-1])
ck("엔진 cfg 에 conditions", len(made["engines"][0].cfg["conditions"]) == 2)

logs.clear()
ck("이미 돌면 재시작 안 함", r.start() is False)
ck("정지 중 로그", "아직 정지 중" in logs[-1], logs[-1])
ck("엔진 하나뿐", len(made["engines"]) == 1)

print("=== F. resync — 필요할 때만 갈아끼운다 ===")
logs.clear()
r.resync()
ck("같고 살아 있으면 무동작", logs == [] and len(made["engines"]) == 1, str(logs))

q.set(["샤넬"])                      # 승격으로 하나 빠짐
logs.clear()
r.resync()
ck("키워드가 갈리면 재시작", len(made["engines"]) == 2, str(len(made["engines"])))
ck("옛 엔진 stop", made["engines"][0].stopped is True)
ck("재시작 로그", any("키워드 변경" in x for x in logs), str(logs))
ck("새 키워드 집합", r.kws == {"샤넬"}, str(r.kws))

logs.clear()
r.resync()
ck("한 번 맞추면 더 안 건드림", len(made["engines"]) == 2 and logs == [], str(logs))

print("=== G. 죽은 스윕 되살리기 — 상한이 있다 ===")
r2, q2, logs2, found2, made2 = runner(["샤넬"], alive_after_start=False)
r2.start()
ck("죽은 채로 시작됨", r2.running() is False)
logs2.clear()
for _ in range(m.SWEEP_REVIVE_MAX + 4):
    r2.resync()
ck("되살리기는 상한까지만",
   len(made2["engines"]) == 1 + m.SWEEP_REVIVE_MAX, str(len(made2["engines"])))
ck("되살림 로그는 재시작과 구분됨",
   any("죽어 있음" in x for x in logs2) and not any("키워드 변경" in x for x in logs2))
ck("포기 로그는 한 번만",
   sum(1 for x in logs2 if "포기합니다" in x) == 1, str(logs2[-3:]))
before = len(made2["engines"])
q2.set(["샤넬", "구찌"])              # 대기열이 바뀌면 다시 시도한다
r2.resync()
ck("대기열 변경은 상한을 푼다", len(made2["engines"]) == before + 1)

print("=== H. 종료 시 정지 ===")
r3, q3, logs3, _f, made3 = runner(["샤넬"])
r3.start()
logs3.clear()
r3.stop(join=8)
ck("엔진 stop 호출", made3["engines"][0].stopped is True)
ck("스레드 join(8)", made3["threads"][0].joined == 8, str(made3["threads"][0].joined))
ck("정지 로그", any("정지 요청" in x for x in logs3), str(logs3))
ck("키워드 집합 비움", r3.kws is None)
ck("안 떠 있으면 stop 은 무해", m.HeadlessSweepRunner(
    q3, lambda: {}, logs3.append, _f.append).stop() is None)

print("=== I. on_found → watch(source='sweep') ===")
r4, q4, logs4, found4, made4 = runner(["샤넬"])
r4.start()
made4["engines"][0].on_found({"id": "A1", "title": "샤넬 클미", "price": 100})
ck("on_found 가 runner 콜백으로", len(found4) == 1, str(found4))
norm = m.sweep_found_to_match(found4[0], m.sweep_keyword_for(found4[0], q4.keywords()))
ck("정규화 결과 article_id", norm["article_id"] == "A1", str(norm))
ck("정규화 결과 keyword", norm["keyword"] == "샤넬", str(norm))
n_before = len(logs4)
made4["engines"][0].on_log("엔진 한마디")
ck("on_log 가 runner 로그로",
   len(logs4) == n_before + 1 and logs4[-1] == "엔진 한마디", str(logs4[-1:]))

print("=== J. seed_router_from_server ===")


class FakeRouter:
    def __init__(self, routes=None):
        self._r = list(routes or [])
        self.seeded = []

    def routes(self):
        return list(self._r)

    def seed_from_server(self, kws):
        self.seeded.append(list(kws))
        self._r = [{"keyword": k} for k in kws]
        return len(kws)


def listing(kws):
    return lambda: {"user_keywords": [{"keyword": k} for k in kws]}


L = []
st = {}
rt = FakeRouter()
ck("빈 routes 면 씨딩", m.seed_router_from_server(rt, listing(["샤넬"]), L.append, st) == 1)
ck("서버 키워드 전달", rt.seeded == [["샤넬"]], str(rt.seeded))
ck("씨딩 로그", any("앱 슬롯으로 인식" in x for x in L), str(L))
calls = []
ck("routes 차 있으면 조회조차 안 함",
   m.seed_router_from_server(rt, lambda: calls.append(1), L.append, st) == 0
   and calls == [])
ck("router 없으면 0", m.seed_router_from_server(None, listing([]), L.append, {}) == 0)

L2, st2 = [], {}
rt2 = FakeRouter()
for _ in range(m.SEED_ATTEMPT_MAX + 3):
    m.seed_router_from_server(rt2, listing([]), L2.append, st2)
ck("빈 목록이어도 시도는 상한까지만",
   st2["n"] == m.SEED_ATTEMPT_MAX, str(st2))
ck("포기 로그 한 번", sum(1 for x in L2 if "포기합니다" in x) == 1, str(L2))
L3, st3 = [], {}


def boom():
    raise RuntimeError("network down")


ck("조회 실패는 삼키고 0", m.seed_router_from_server(FakeRouter(), boom, L3.append, st3) == 0)
ck("실패 로그", any("인식 실패" in x for x in L3), str(L3))

print("=== K. GUI 폴링 틱도 씨딩을 지난다 ===")
_tick_code = m.MainWindow._auto_poll_tick.__code__
src_tick = set(_tick_code.co_names)
_tick_job = set()
for _c in _tick_code.co_consts:
    if hasattr(_c, "co_names"):
        _tick_job |= set(_c.co_names)
# 씨딩은 HTTP 조회다 — 타이머 콜백(GUI 스레드)이 아니라 폴링 잡 안에서 돌아야 한다.
ck("_auto_poll_tick 의 씨딩은 GUI 스레드 밖(폴링 잡)",
   "seed_router_from_server" in _tick_job
   and "seed_router_from_server" not in src_tick, str(src_tick))
ck("_auto_poll_tick 이 rebalance 호출", "rebalance" in (src_tick | _tick_job))
ck("_auto_poll_tick 이 재동기화 호출", "_resync_search_sweep" in src_tick)
ck("_alert_populate 도 씨딩 유지",
   "seed_from_server" in m.MainWindow._alert_populate.__code__.co_names)
ck("GUI 재동기화가 공용 판정 사용",
   "sweep_resync_action" in m.MainWindow._resync_search_sweep.__code__.co_names)
ck("GUI cfg 가 공용 조건 조립 사용",
   "sweep_conditions" in m.MainWindow._sweep_cfg.__code__.co_names)
ck("GUI 토큰 provider 가 공용 함수 사용",
   "harvest_token_quiet" in m.MainWindow._harvest_token_quiet.__code__.co_names)

print("=== L. 헤드리스 런타임 배선(소스 수준) ===")
names = m._run_headless.__code__.co_names
consts = [c for c in m._run_headless.__code__.co_consts
          if hasattr(c, "co_names")]
inner = set(names)
for c in consts:
    inner |= set(c.co_names)
ck("SweepQueue 구성", "SweepQueue" in inner, "")
ck("KeywordRouter 구성", "KeywordRouter" in inner)
ck("HeadlessSweepRunner 구성", "HeadlessSweepRunner" in inner)
ck("rebalance 호출", "rebalance" in inner)
ck("resync 호출", "resync" in inner)
ck("씨딩 호출", "seed_router_from_server" in inner)
ck("종료 시 stop", "stop" in inner)
ck("--register 가 라우터를 지난다", "add_many" in inner)
ck("--register 가 register_all 을 직접 부르지 않는다", "register_all" not in inner)
ck("add_from_matches 로 워치 등록", "add_from_matches" in inner)
# 스윕 결과 등록은 인계 큐를 통해 폴링 스레드가 한다 — source='sweep' 는
# 그쪽(drain_sweep_finds)에 있다.
_drain_consts = m.drain_sweep_finds.__code__.co_consts
ck("source='sweep' 로 등록", "sweep" in _drain_consts, str(_drain_consts))
ck("헤드리스가 인계 큐를 드레인", "drain_sweep_finds" in inner)

print("=== M. 진짜 스레드로 — Qt 이벤트 루프 없이 돈다 ===")
import time as _t


class LoopEngine:
    """stop 플래그를 보고 빠지는 최소 엔진. 네트워크는 안 쓴다."""
    def __init__(self, cfg, on_log, on_found):
        self.cfg = cfg
        self.on_log = on_log
        self.on_found = on_found
        self._stop = False
        self.entered = False
        self.left = False

    def run(self):
        self.entered = True
        self.on_found({"id": "T1", "title": "샤넬 스레드", "price": 1})
        while not self._stop:
            _t.sleep(0.01)
        self.left = True

    def stop(self):
        self._stop = True


q5 = FakeQueue(["샤넬"])
logs5, found5 = [], []
eng5 = {}


def ef5(cfg, on_log, on_found):
    eng5["e"] = LoopEngine(cfg, on_log, on_found)
    return eng5["e"]


r5 = m.HeadlessSweepRunner(q5, lambda: m.headless_sweep_cfg({}, q5.entries(), {}),
                           logs5.append, found5.append, engine_factory=ef5)
ck("진짜 스레드로 시작", r5.start() is True)
for _ in range(200):
    if eng5["e"].entered:
        break
    _t.sleep(0.01)
ck("엔진 run 진입", eng5["e"].entered is True)
ck("살아 있다고 보고", r5.running() is True)
ck("on_found 가 스레드서 넘어옴", found5 and found5[0]["id"] == "T1", str(found5))
ck("데몬 스레드(프로세스 종료를 안 막음)", r5.thread.daemon is True)
r5.stop(join=5)
ck("join 뒤 스레드 종료", r5.running() is False)
ck("엔진 run 정상 탈출", eng5["e"].left is True)

print("=== N. 기본 스윕 범위 — 새 설치가 전국을 훑지 않는다 ===")
_dflt = m.default_sweep_regions("./OUT.json")
ck("기본 지역이 비어 있지 않다", len(_dflt) > 0, str(len(_dflt)))
ck("기본 지역은 동 코드(이름-ID)", all("-" in r for r in _dflt), str(_dflt[:2]))
ck("기본 지역에 중복 없음", len(set(_dflt)) == len(_dflt))
try:
    from daangn_ext.adaptive import load_dong_regions as _ldr
    _nation = len(_ldr("./OUT.json"))
except Exception:
    _nation = 0
ck("전국 동 수를 읽었다", _nation > 1000, str(_nation))
# 기본값은 서울·경기다(명품 물량이 몰린 곳). 전국을 통째로 도는 일은 없어야
# 하고, 조건 몇 개까지는 한 사이클 예산 안에 들어와야 한다.
ck("기본 지역은 전국보다 훨씬 작다",
   _nation and len(_dflt) < _nation / 2, f"{len(_dflt)} vs {_nation}")
ck("기본 범위는 서울·경기",
   set(m.DEFAULT_SWEEP_SIDO) == {"서울특별시", "경기도"}, str(m.DEFAULT_SWEEP_SIDO))
ck("브랜드 하나는 예산 안에 넉넉히 들어온다",
   len(_dflt) * 1 <= m.SWEEP_BUDGET, f"{len(_dflt)} / {m.SWEEP_BUDGET}")
ck("OUT.json 이 없으면 빈 목록(전국 아님)",
   m.default_sweep_regions("./__없는파일__.json") == [])

ck("고른 지역이 있으면 그 지역",
   m.sweep_scope_for(["가-1"], False) == {"scope": "regions", "regions": ["가-1"]})
ck("전국은 명시적으로 켤 때만",
   m.sweep_scope_for([], True) == {"scope": "nationwide"})
ck("고른 지역이 전국 플래그를 이긴다",
   m.sweep_scope_for(["가-1"], True)["scope"] == "regions")
_sc = m.sweep_scope_for([], False)
ck("둘 다 아니면 기본 지역", _sc["scope"] == "regions" and _sc["regions"] == _dflt,
   _sc["scope"])
_scl = []
m.sweep_scope_for([], False, log=_scl.append)
ck("기본으로 떨어지면 로그로 알린다",
   _scl and "기본 범위" in _scl[0], str(_scl))
ck("OUT.json 도 없으면 빈 지역(전국으로 안 떨어짐)",
   m.sweep_scope_for([], False, out_json="./__없는파일__.json")
   == {"scope": "regions", "regions": []})
ck("빈 문자열 지역은 무시", m.sweep_scope_for(["", None], True)["scope"] == "nationwide")

ck("헤드리스: 전국 키를 켜면 전국",
   m.headless_sweep_cfg({m.SWEEP_NATIONWIDE_KEY: True}, E, {})["scope"] == "nationwide")
ck("헤드리스: 전국 키가 꺼져 있으면 기본 지역",
   m.headless_sweep_cfg({m.SWEEP_NATIONWIDE_KEY: False}, E, {}, token_provider=_TP)["regions"] == _dflt)
ck("헤드리스: 지역 지정이 전국 키를 이긴다",
   m.headless_sweep_cfg({"sweep_regions": ["가-1"], m.SWEEP_NATIONWIDE_KEY: True},
                        E, {})["regions"] == ["가-1"])
ck("전국 설정 키 이름", m.SWEEP_NATIONWIDE_KEY == "sweep_nationwide")
_cfgl = []
m.headless_sweep_cfg({}, E, {}, log=_cfgl.append, token_provider=_TP)
ck("헤드리스도 기본 범위를 로그로 알린다", any("기본 범위" in x for x in _cfgl),
   str(_cfgl))
# 조건이 늘면 같은 지역 수라도 사이클이 길어진다 — 예산을 넘으면 구·시 단위로 내린다.
_coarse = m.default_sweep_regions_coarse("./OUT.json")
ck("구·시 단위 목록이 동 단위보다 훨씬 성기다",
   0 < len(_coarse) < len(_dflt) / 5, f"{len(_coarse)} vs {len(_dflt)}")
_fitl = []
_kept, _low = m.sweep_fit_budget(_dflt, 1, _coarse, log=_fitl.append)
ck("예산 안이면 그대로", _kept is _dflt and _low is False and not _fitl)
_over = (m.SWEEP_BUDGET // len(_dflt)) + 1
_kept2, _low2 = m.sweep_fit_budget(_dflt, _over, _coarse, log=_fitl.append)
ck("예산 넘으면 구·시 단위로 내린다", _kept2 == _coarse and _low2 is True)
ck("낮췄다는 사실을 로그로 알린다",
   any("한 사이클 예산" in x for x in _fitl), str(_fitl))
ck("조건 수가 범위 판정까지 간다",
   len(m.headless_sweep_cfg({}, E, {}, token_provider=_TP)["regions"]) == len(_dflt),
   "조건 2개 = 예산 안")
# 범위 판정은 GUI 와 한 함수여야 한다 — 갈라지면 서버가 다른 범위를 돈다.
ck("GUI cfg 가 공용 범위 판정 사용",
   "sweep_scope_for" in m.MainWindow._auto_cfg_base.__code__.co_names)
ck("헤드리스 cfg 가 공용 범위 판정 사용",
   "sweep_scope_for" in m.headless_sweep_cfg.__code__.co_names)
ck("헤드리스에 '미선택=전국' 분기가 남아 있지 않다",
   "nationwide" not in (m.headless_sweep_cfg.__code__.co_consts or ()),
   str(m.headless_sweep_cfg.__code__.co_consts))

print("=== O. 되살리기 상한은 두 런타임이 같은 함수로 센다 ===")
_ok, _n, _msg = m.sweep_revive_step(0, 3)
ck("첫 되살림 허용", _ok is True and _n == 1, f"{_ok} {_n}")
ck("되살림 로그에 진행도", f"(1/{m.SWEEP_REVIVE_MAX})" in _msg, _msg)
ck("되살림 로그에 키워드 수", "키워드 3개" in _msg, _msg)
_ok, _n, _msg = m.sweep_revive_step(m.SWEEP_REVIVE_MAX - 1, 1)
ck("마지막 한 번은 허용", _ok is True and _n == m.SWEEP_REVIVE_MAX)
_ok, _n, _msg = m.sweep_revive_step(m.SWEEP_REVIVE_MAX, 1)
ck("상한에 닿으면 거절", _ok is False)
ck("포기 로그는 상한에서 한 번", "포기합니다" in _msg, _msg)
ck("포기 뒤 카운터는 상한+1", _n == m.SWEEP_REVIVE_MAX + 1, str(_n))
_ok, _n, _msg = m.sweep_revive_step(m.SWEEP_REVIVE_MAX + 1, 1)
ck("그 뒤로는 조용히 거절", _ok is False and _msg == "" and _n == m.SWEEP_REVIVE_MAX + 1)
ck("헤드리스 resync 가 공용 카운터 사용",
   "sweep_revive_step" in m.HeadlessSweepRunner.resync.__code__.co_names)
ck("GUI resync 도 공용 카운터 사용",
   "sweep_revive_step" in m.MainWindow._resync_search_sweep.__code__.co_names)

print("=== P. 스윕 결과 인계 — sqlite 는 폴링 스레드 하나만 만진다 ===")
import queue as _pyq
import threading as _th
import tempfile as _tf
import shutil as _sh
from daangn_ext import article_watch as _aw

ck("인계 큐 상한 정의", isinstance(m.SWEEP_FIND_QUEUE_MAX, int)
   and m.SWEEP_FIND_QUEUE_MAX > 0, str(m.SWEEP_FIND_QUEUE_MAX))
# 헤드리스의 on_found 는 스윕 스레드에서 불린다 — 거기서 저장소를 만지면 안 된다.
_hsrc = _inspect.getsource(m._run_headless) if "_inspect" in dir() else ""
if not _hsrc:
    import inspect as _inspect
    _hsrc = _inspect.getsource(m._run_headless)
_found_src = _hsrc.split("def _sweep_found(")[1].split("def _sweep_cfg_builder")[0]
ck("_sweep_found 는 큐에 넣기만 한다", "put_nowait" in _found_src, _found_src[:80])
ck("_sweep_found 는 저장소를 안 만진다",
   "add_from_matches" not in _found_src and "watch_tracker" not in _found_src,
   _found_src[:120])
ck("인계 큐는 상한이 있다", "maxsize=SWEEP_FIND_QUEUE_MAX" in _hsrc)


class ThreadWitness:
    """WatchStore 를 감싸 '어느 스레드가 만졌는지' 기록한다."""

    def __init__(self, inner):
        self._inner = inner
        self.idents = set()

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def wrapped(*a, **k):
            self.idents.add(_th.get_ident())
            return attr(*a, **k)
        return wrapped


_tmpdir = _tf.mkdtemp(prefix="sweepq_")
_store7 = _aw.WatchStore(os.path.join(_tmpdir, "watch.db"))
_wit = ThreadWitness(_store7)
_tracker7 = _aw.WatchTracker(_wit)
_q7 = _pyq.Queue(maxsize=m.SWEEP_FIND_QUEUE_MAX)
_drop7 = [0]
_logs7 = []
_sweep_ident = {}
N_FIND = 400


def _on_found7(payload):
    """스윕 스레드에서 불리는 그 콜백과 같은 모양."""
    try:
        _q7.put_nowait(payload)
    except _pyq.Full:
        _drop7[0] += 1


def _sweep_body():
    _sweep_ident["id"] = _th.get_ident()
    for i in range(N_FIND):
        _on_found7({"id": f"S{i}", "title": "샤넬 가방", "price": "100,000원"})


_thr7 = _th.Thread(target=_sweep_body, name="sweep-test")
_polling_ident = _th.get_ident()
_thr7.start()
_added7 = 0
for _ in range(4000):
    # 폴링 스레드가 하는 일: 드레인 + 상한 강제 + 카운트(읽기-수정-쓰기 3종)
    _added7 += m.drain_sweep_finds(_q7, _tracker7, lambda: ["샤넬"], _logs7.append)
    _tracker7.enforce_cap()
    _wit.active_count()
    if not _thr7.is_alive() and _q7.empty():
        break
_thr7.join(10)
_added7 += m.drain_sweep_finds(_q7, _tracker7, lambda: ["샤넬"], _logs7.append)
ck("스윕 스레드가 실제로 돌았다", _sweep_ident.get("id") not in (None, _polling_ident),
   str(_sweep_ident))
ck("인계된 매물이 전부 등록됐다", _added7 == N_FIND, f"{_added7}/{N_FIND}")
ck("큐 상한에 안 걸렸다(버린 것 없음)", _drop7[0] == 0, str(_drop7[0]))
ck("저장소를 만진 스레드는 하나뿐", _wit.idents == {_polling_ident}, str(_wit.idents))
ck("만진 스레드에 스윕 스레드가 없다", _sweep_ident.get("id") not in _wit.idents)
ck("상한 강제가 실제로 돌았다(활성 <= ACTIVE_CAP)",
   _store7.active_count() <= _aw.ACTIVE_CAP, str(_store7.active_count()))
ck("등록 로그는 폴링 스레드가 남긴다", any("신규 매물 추적" in x for x in _logs7),
   str(_logs7[:2]))
ck("source 는 sweep",
   (_store7.get("S0") or {}).get("source") == "sweep", str(_store7.get("S0")))

# 큐가 차면 막히는 대신 버린다 — 스윕 스레드는 절대 폴링에 붙잡히지 않는다.
_qsmall = _pyq.Queue(maxsize=2)
_dropped_small = 0
for i in range(5):
    try:
        _qsmall.put_nowait({"id": str(i)})
    except _pyq.Full:
        _dropped_small += 1
ck("큐가 차면 put_nowait 이 버린다(블록 아님)", _dropped_small == 3,
   str(_dropped_small))

ck("tracker 가 없으면 큐만 비운다",
   m.drain_sweep_finds(_q7, None, lambda: [], _logs7.append) == 0)
ck("빈 큐 드레인은 0", m.drain_sweep_finds(_q7, _tracker7, lambda: [], _logs7.append) == 0)
ck("큐가 None 이어도 안 죽음",
   m.drain_sweep_finds(None, _tracker7, lambda: [], _logs7.append) == 0)
_store7.close()
_sh.rmtree(_tmpdir, ignore_errors=True)

print("=== Q. 관측 상한 탈출구가 두 런타임에서 닿는다 ===")
ck("헤드리스에 --reset-cap 이 있다", "--reset-cap" in _hsrc)
ck("--reset-cap 이 reset_observed_cap 을 부른다",
   "reset_observed_cap" in inner)
ck("GUI 는 전체 삭제가 reset_observed_cap 을 부른다",
   "reset_observed_cap" in m.MainWindow.on_alert_delete_all.__code__.co_names)
from daangn_ext import keyword_router as _kr
_capsrc = _inspect.getsource(_kr.KeywordRouter._observe_cap_full)
ck("하향 로그가 실제 조작법을 알려준다",
   "전체 삭제" in _capsrc and "--reset-cap" in _capsrc, _capsrc[-160:])


print("\n=== 예산은 레인 수에서 유도된다 ===")
ck("기본 예산 = 8레인 예산", m.SWEEP_BUDGET == m.sweep_budget(8) == m.sweep_budget(0)
   == m.sweep_budget(None), str(m.SWEEP_BUDGET))
ck("8레인 ≈ 실측 17,900(1380s × 13 req/s)", 17000 <= m.SWEEP_BUDGET <= 18000)
ck("1레인 예산은 8분의 1", m.sweep_budget(1) * 8 == m.SWEEP_BUDGET, str(m.sweep_budget(1)))
_fitl2 = []
_k1, _l1 = m.sweep_fit_budget(_dflt, 2, _coarse, log=_fitl2.append, budget=m.sweep_budget(1))
ck("1레인이면 서울·경기 × 조건 2 도 구·시 단위로 내린다", _k1 == _coarse and _l1 is True)
ck("로그에 그 예산이 찍힌다", any(f"{m.sweep_budget(1):,}" in x for x in _fitl2), str(_fitl2))
_k8, _l8 = m.sweep_fit_budget(_dflt, 2, _coarse, budget=m.sweep_budget(8))
ck("8레인이면 그대로", _k8 is _dflt and _l8 is False)
ck("scope 판정이 lanes 를 받는다",
   len(m.sweep_scope_for([], False, n_conditions=2, lanes=1)["regions"]) == len(_coarse)
   and len(m.sweep_scope_for([], False, n_conditions=2, lanes=0)["regions"]) == len(_dflt))
ck("헤드리스 cfg 가 lanes 를 범위 판정에 넘긴다",
   len(m.headless_sweep_cfg({"sweep_lanes": 1}, E, {}, token_provider=_TP)["regions"]) == len(_coarse)
   and len(m.headless_sweep_cfg({}, E, {}, token_provider=_TP)["regions"]) == len(_dflt))
ck("GUI cfg 도 실제 레인 수를 넘긴다(토큰 경로 고정)",
   'lanes=sweep_lanes_effective(cfg["lanes"], True, 0)'
   in open("main.py", encoding="utf-8").read().split("def _auto_cfg_base", 1)[1][:6000])
ck("daily_cap 기본 0(상한 없음)", m.headless_sweep_cfg({}, E, {})["daily_cap"] == 0)
# 예산의 레인 수는 엔진이 실제로 돌릴 수와 같아야 한다.
ck("토큰 있으면 8 (지정 0·99 모두 상한 8)",
   m.sweep_lanes_effective(0, True, 0) == 8 and m.sweep_lanes_effective(99, True, 1) == 8
   and m.sweep_lanes_effective(3, True, 0) == 3)
ck("토큰 없으면 프록시 ÷ 3 (웹크롤 규칙)",
   m.sweep_lanes_effective(0, False, 3) == 1 and m.sweep_lanes_effective(0, False, 9) == 3
   and m.sweep_lanes_effective(0, False, 0) == 1 and m.sweep_lanes_effective(8, False, 3) == 1)
_web3 = m.headless_sweep_cfg({}, E, {}, proxies=["a", "b", "c"], token_provider=None)
_app3 = m.headless_sweep_cfg({}, E, {}, proxies=["a", "b", "c"], token_provider=lambda: "t")
ck("헤드리스 웹크롤 경로(프록시 3, 토큰 없음)는 1레인 예산 → 구·시 단위",
   len(_web3["regions"]) == len(_coarse), str(len(_web3["regions"])))
ck("같은 프록시라도 토큰 있으면 8레인 예산 → 동 단위",
   len(_app3["regions"]) == len(_dflt), str(len(_app3["regions"])))
ck("페이지폭은 엔진 상수 한 곳", not hasattr(m, "SWEEP_PAGE_WINDOW_SEC")
   and m.sweep_budget(8) == int(m.sweep_capacity(1.6 * 8)))

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

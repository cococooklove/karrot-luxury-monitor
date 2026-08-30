"""키워드 라우터 테스트 (네트워크 불필요).

    python keyword_router_test.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from daangn_ext.keyword_router import KeywordRouter, DEFAULT_SLOT_CAP, _CAP_META_KEY
from daangn_ext.sweep_queue import SweepQueue

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


class FakeAlerts:
    """register_all 호출을 기록한다. banned 에 든 키워드는 실패로 돌린다."""

    def __init__(self, banned=()):
        self.calls = []
        self.banned = set(banned)

    def register_all(self, keywords, min_price=None, max_price=None,
                     exclude_keywords=None, log=None, core_only=False):
        self.calls.append({"keywords": list(keywords), "min": min_price,
                           "max": max_price, "exclude": exclude_keywords,
                           "core_only": core_only})
        bad = [k for k in keywords if k in self.banned]
        return {"added": len(keywords) - len(bad), "skipped": 0,
                "failed": len(bad)}


def mk(slot_cap=DEFAULT_SLOT_CAP, banned=()):
    d = tempfile.mkdtemp()
    alerts = FakeAlerts(banned)
    q = SweepQueue(os.path.join(d, "q.json"))
    r = KeywordRouter(alerts, q, slot_cap=slot_cap,
                      routes_fp=os.path.join(d, "routes.json"))
    return alerts, q, r


# ── A. 여유가 있으면 앱으로 ──
alerts, q, r = mk(slot_cap=3)
res = r.add("샤넬")
ck("여유 있으면 app", res["route"] == "app", str(res))
ck("register_all 호출됨", len(alerts.calls) == 1, str(alerts.calls))
ck("호출 키워드", alerts.calls[0]["keywords"] == ["샤넬"])
ck("큐 비어 있음", len(q) == 0)
cap = r.capacity()
ck("capacity used 1", cap["used"] == 1, str(cap))
ck("capacity free 2", cap["free"] == 2, str(cap))

# ── B. 만원이면 스윕으로 ──
r.add("루이비통"); r.add("에르메스")
ck("슬롯 소진", r.capacity()["free"] == 0, str(r.capacity()))
n_before = len(alerts.calls)
res = r.add("구찌")
ck("만원이면 sweep", res["route"] == "sweep", str(res))
ck("만원이면 register_all 안 부름", len(alerts.calls) == n_before)
ck("사유 기록", "슬롯" in res["reason"], res["reason"])
ck("큐에 들어감", q.keywords() == ["구찌"], str(q.keywords()))

# ── C. 밴 키워드는 스윕 폴백 ──
alerts2, q2, r2 = mk(slot_cap=5, banned={"짝퉁"})
res = r2.add("짝퉁")
ck("밴이면 sweep", res["route"] == "sweep", str(res))
ck("밴 사유", "등록 실패" in res["reason"] or "차단" in res["reason"], res["reason"])
ck("밴이면 큐로", q2.keywords() == ["짝퉁"])
ck("밴은 슬롯 안 먹음", r2.capacity()["used"] == 0, str(r2.capacity()))

# ── D. 승격 ──
alerts3, q3, r3 = mk(slot_cap=2)
r3.add("A"); r3.add("B")            # 슬롯 만원
r3.add("C"); r3.add("D")            # 큐로
ck("큐 2건", q3.keywords() == ["C", "D"], str(q3.keywords()))
ck("슬롯 없으면 rebalance 무동작", r3.rebalance() == [])
r3.remove("A")
ck("삭제 후 여유 1", r3.capacity()["free"] == 1, str(r3.capacity()))
promoted = r3.rebalance()
ck("한 건 승격", len(promoted) == 1, str(promoted))
ck("오래된 것부터", promoted[0]["keyword"] == "C", str(promoted))
ck("승격은 app", promoted[0]["route"] == "app")
ck("승격분 큐에서 빠짐", q3.keywords() == ["D"], str(q3.keywords()))

# ── E. routes 목록 ──
rows = {x["keyword"]: x for x in r3.routes()}
ck("routes 에 B", rows.get("B", {}).get("route") == "app", str(rows))
ck("routes 에 D 는 sweep", rows.get("D", {}).get("route") == "sweep", str(rows))
ck("삭제된 A 는 없음", "A" not in rows, str(rows))

# ── F. 영속 ──
d6 = tempfile.mkdtemp()
a6 = FakeAlerts()
q6 = SweepQueue(os.path.join(d6, "q.json"))
fp6 = os.path.join(d6, "routes.json")
r6 = KeywordRouter(a6, q6, slot_cap=2, routes_fp=fp6)
r6.add("X")
r6b = KeywordRouter(FakeAlerts(), SweepQueue(os.path.join(d6, "q.json")),
                    slot_cap=2, routes_fp=fp6)
ck("재시작 후 라우트 유지", r6b.capacity()["used"] == 1, str(r6b.capacity()))

# ── G. add_many ──
alerts7, q7, r7 = mk(slot_cap=2)
out = r7.add_many(["P", "Q", "R"])
ck("add_many 3건 결과", len(out) == 3, str(out))
ck("앞의 둘은 app", [o["route"] for o in out[:2]] == ["app", "app"], str(out))
ck("셋째는 sweep", out[2]["route"] == "sweep", str(out))

# ── H. 등록 결과가 전부 0 이면 스윕으로 (유효 계정 없음) ──
class EmptyFleet:
    def register_all(self, keywords, min_price=None, max_price=None,
                     exclude_keywords=None, log=None, core_only=False):
        return {"added": 0, "skipped": 0, "failed": 0}


d8 = tempfile.mkdtemp()
q8 = SweepQueue(os.path.join(d8, "q.json"))
r8 = KeywordRouter(EmptyFleet(), q8, slot_cap=5,
                   routes_fp=os.path.join(d8, "routes.json"))
res = r8.add("샤넬")
ck("유효 계정 0 이면 sweep", res["route"] == "sweep", str(res))
ck("유효 계정 0 이면 슬롯 안 먹음", r8.capacity()["used"] == 0, str(r8.capacity()))
ck("유효 계정 0 이면 큐로", q8.keywords() == ["샤넬"], str(q8.keywords()))

# 이미 등록된 키워드(skipped)는 성공이다
class AllSkipped:
    def register_all(self, keywords, min_price=None, max_price=None,
                     exclude_keywords=None, log=None, core_only=False):
        return {"added": 0, "skipped": len(keywords), "failed": 0}


d8b = tempfile.mkdtemp()
q8b = SweepQueue(os.path.join(d8b, "q.json"))
r8b = KeywordRouter(AllSkipped(), q8b, slot_cap=5,
                    routes_fp=os.path.join(d8b, "routes.json"))
ck("이미 등록됨(skipped)은 app", r8b.add("루이비통")["route"] == "app")
ck("skipped 도 슬롯 차지", r8b.capacity()["used"] == 1, str(r8b.capacity()))

# ── I. register_all 이 예외를 던져도 스윕으로 폴백 ──
class Exploding:
    def register_all(self, *a, **k):
        raise RuntimeError("네트워크 끊김")


d9 = tempfile.mkdtemp()
q9 = SweepQueue(os.path.join(d9, "q.json"))
r9 = KeywordRouter(Exploding(), q9, slot_cap=5,
                   routes_fp=os.path.join(d9, "routes.json"))
res = r9.add("에르메스")
ck("예외는 전파되지 않음", res["route"] == "sweep", str(res))
ck("예외 사유 기록", "네트워크 끊김" in res["reason"], res["reason"])
ck("예외여도 큐로", q9.keywords() == ["에르메스"])

# ── J. 깨진 routes 파일은 빈 라우트로 ──
fp10 = os.path.join(d9, "broken.json")
with open(fp10, "w", encoding="utf-8") as f:
    f.write("{깨진 json")
r10 = KeywordRouter(FakeAlerts(), SweepQueue(os.path.join(d9, "q10.json")),
                    slot_cap=3, routes_fp=fp10)
ck("깨진 routes 는 빈 상태", r10.capacity()["used"] == 0, str(r10.capacity()))
ck("깨진 뒤에도 등록 가능", r10.add("구찌")["route"] == "app")

# ── K. 빈 키워드는 아무 경로도 아니다 ──
alertsE, qE, rE = mk(slot_cap=3)
resE = rE.add("")
ck("빈 키워드는 route 없음", resE["route"] is None, str(resE))
ck("빈 키워드는 큐로 안 감", len(qE) == 0)
ck("빈 키워드는 슬롯 안 먹음", rE.capacity()["used"] == 0, str(rE.capacity()))
ck("빈 키워드는 register_all 안 부름", len(alertsE.calls) == 0)

# ── L. 승격 실패는 백오프로 묶고, 뒤의 키워드를 막지 않는다 ──
import json as _json
import time as _time


class PickyFleet:
    """banned 키워드만 실패시킨다. 호출 수로 실제 요청 횟수를 본다."""

    def __init__(self, banned=()):
        self.banned = set(banned)
        self.calls = []

    def register_all(self, keywords, min_price=None, max_price=None,
                     exclude_keywords=None, log=None, core_only=False):
        self.calls.append(list(keywords))
        bad = [k for k in keywords if k in self.banned]
        if bad:
            return {"added": 0, "skipped": 0, "failed": len(bad)}
        return {"added": len(keywords), "skipped": 0, "failed": 0}


dL = tempfile.mkdtemp()
qLp = os.path.join(dL, "q.json")
rLp = os.path.join(dL, "routes.json")
qL = SweepQueue(qLp)
qL.add("짝퉁", at=1000)          # 절대 등록 안 되는 것이 큐 머리
qL.add("구찌", at=2000)
qL.add("에르메스", at=3000)
fL = PickyFleet({"짝퉁"})
rL = KeywordRouter(fL, qL, slot_cap=1, routes_fp=rLp)

t0 = int(_time.time())
promoted = rL.rebalance()
ck("실패한 머리를 건너뛰고 뒤를 승격", [p["keyword"] for p in promoted] == ["구찌"],
   str(promoted))
ck("실패 1회 + 성공 1회만 요청", len(fL.calls) == 2, str(fL.calls))
ck("실패분은 큐 맨 뒤로", qL.keywords() == ["에르메스", "짝퉁"], str(qL.keywords()))
ck("실패분에 백오프 기록", rL.retry_after("짝퉁") >= t0 + 3600,
   str(rL.retry_after("짝퉁")))
ck("첫 백오프는 한 시간대", rL.retry_after("짝퉁") <= t0 + 3600 + 5,
   str(rL.retry_after("짝퉁") - t0))

# 백오프 중에는 아예 시도하지 않는다 (요청 0)
rL.remove("구찌"); rL.remove("에르메스")     # 큐엔 짝퉁만, 슬롯은 빈다
n_before = len(fL.calls)
ck("백오프 중 승격 없음", rL.rebalance() == [])
ck("백오프 중 요청 0", len(fL.calls) == n_before, str(fL.calls))

# 재시작해도 백오프가 살아 있다
fL2 = PickyFleet({"짝퉁"})
rL2 = KeywordRouter(fL2, SweepQueue(qLp), slot_cap=1, routes_fp=rLp)
ck("재시작 후 백오프 유지", rL2.retry_after("짝퉁") >= t0 + 3600,
   str(rL2.retry_after("짝퉁")))
ck("재시작 후에도 승격 안 함", rL2.rebalance() == [])
ck("재시작 후에도 요청 0", len(fL2.calls) == 0, str(fL2.calls))

# 백오프가 지나면 딱 한 번 더 시도하고, 다음 백오프는 두 배로 늘어난다
with open(rLp, encoding="utf-8") as f:
    _rt = _json.load(f)
_rt["짝퉁"]["retry_after"] = t0 - 1
with open(rLp, "w", encoding="utf-8") as f:
    _json.dump(_rt, f, ensure_ascii=False)
fL3 = PickyFleet({"짝퉁"})
rL3 = KeywordRouter(fL3, SweepQueue(qLp), slot_cap=1, routes_fp=rLp)
t1 = int(_time.time())
ck("백오프 만료 후 승격 시도", rL3.rebalance() == [])
ck("만료 후엔 딱 한 번 요청", len(fL3.calls) == 1, str(fL3.calls))
ck("백오프가 두 배로", t1 + 7200 <= rL3.retry_after("짝퉁") <= t1 + 7200 + 5,
   str(rL3.retry_after("짝퉁") - t1))

# 슬롯 만원으로 밀린 것은 실패가 아니다 — 백오프를 물리지 않는다
dL4 = tempfile.mkdtemp()
qL4 = SweepQueue(os.path.join(dL4, "q.json"))
rL4 = KeywordRouter(PickyFleet(), qL4, slot_cap=1,
                    routes_fp=os.path.join(dL4, "routes.json"))
rL4.add("A"); rL4.add("B")
ck("만원 폴백엔 백오프 없음", rL4.retry_after("B") == 0, str(rL4.retry_after("B")))
rL4.remove("A")
ck("만원 폴백은 곧바로 승격", [p["keyword"] for p in rL4.rebalance()] == ["B"])

# 등록에 성공하면 백오프 기록은 사라진다
dL5 = tempfile.mkdtemp()
qL5 = SweepQueue(os.path.join(dL5, "q.json"))
fL5 = PickyFleet({"흔들"})
rL5 = KeywordRouter(fL5, qL5, slot_cap=2, routes_fp=os.path.join(dL5, "routes.json"))
rL5.add("흔들")
ck("실패 시 백오프 생김", rL5.retry_after("흔들") > 0)
fL5.banned.clear()
rL5.add("흔들")
ck("성공하면 app", rL5.capacity()["used"] == 1, str(rL5.capacity()))
ck("성공하면 백오프 소멸", rL5.retry_after("흔들") == 0, str(rL5.retry_after("흔들")))

# ── M. 서버에 이미 있는 키워드 씨딩 ──
dM = tempfile.mkdtemp()
fpM = os.path.join(dM, "routes.json")
qM = SweepQueue(os.path.join(dM, "q.json"))
aM = FakeAlerts()
rM = KeywordRouter(aM, qM, slot_cap=3, routes_fp=fpM)
ck("씨딩 전엔 빈 함대", rM.capacity()["used"] == 0, str(rM.capacity()))
ck("씨딩 건수", rM.seed_from_server(["샤넬", "루이비통", "샤넬", "", None]) == 2)
ck("씨딩은 app 으로", rM.capacity()["used"] == 2, str(rM.capacity()))
ck("씨딩은 네트워크 안 씀", len(aM.calls) == 0, str(aM.calls))
_rowsM = {x["keyword"]: x for x in rM.routes()}
ck("씨딩 사유 기록", "서버" in _rowsM["샤넬"]["reason"], str(_rowsM["샤넬"]))
ck("두 번째 씨딩은 무동작", rM.seed_from_server(["에르메스"]) == 0)
ck("두 번째 씨딩이 덮지 않음", "에르메스" not in {x["keyword"] for x in rM.routes()})
ck("씨딩 결과 영속",
   KeywordRouter(FakeAlerts(), SweepQueue(os.path.join(dM, "q.json")),
                 slot_cap=3, routes_fp=fpM).capacity()["used"] == 2)

# routes 가 이미 있으면 씨딩하지 않는다 — 스윕으로 밀린 기록을 app 으로 뒤집으면 안 된다
dM2 = tempfile.mkdtemp()
qM2 = SweepQueue(os.path.join(dM2, "q.json"))
rM2 = KeywordRouter(FakeAlerts(banned={"짝퉁"}), qM2, slot_cap=3,
                    routes_fp=os.path.join(dM2, "routes.json"))
rM2.add("짝퉁")
ck("기존 라우트가 있으면 씨딩 0", rM2.seed_from_server(["짝퉁", "샤넬"]) == 0)
ck("스윕 기록이 뒤집히지 않음",
   {x["keyword"]: x["route"] for x in rM2.routes()} == {"짝퉁": "sweep"},
   str(rM2.routes()))
ck("빈 목록 씨딩은 0", KeywordRouter(
    FakeAlerts(), SweepQueue(os.path.join(dM2, "q2.json")), slot_cap=3,
    routes_fp=os.path.join(dM2, "r2.json")).seed_from_server([]) == 0)

# ── N. 상한 관측(observed cap) ──
class CapAwareFleet:
    """fleet_full 신호를 명시적으로 보내는 가짜 alerts.
    banned: 신호 없이 그냥 실패(예: 차단 키워드) — 상한과 무관해야 한다.
    limited: 실패하되 fleet_full=True(서버가 함대 한도 도달을 알려줌)."""

    def __init__(self, banned=(), limited=()):
        self.banned = set(banned)
        self.limited = set(limited)
        self.calls = []

    def register_all(self, keywords, min_price=None, max_price=None,
                     exclude_keywords=None, log=None, core_only=False):
        self.calls.append(list(keywords))
        kw = keywords[0]
        if kw in self.limited:
            return {"added": 0, "skipped": 0, "failed": 1, "fleet_full": True}
        if kw in self.banned:
            return {"added": 0, "skipped": 0, "failed": 1}
        return {"added": 1, "skipped": 0, "failed": 0}


dN = tempfile.mkdtemp()
fpN = os.path.join(dN, "routes.json")
qN = SweepQueue(os.path.join(dN, "q.json"))
fN = CapAwareFleet(limited={"신상1"})
rN = KeywordRouter(fN, qN, slot_cap=5, routes_fp=fpN)
rN.add("A"); rN.add("B")               # used=2, 둘 다 app 성공
res = rN.add("신상1")                   # fleet_full 신호 → 관측
ck("fleet_full 신호로 sweep", res["route"] == "sweep", str(res))
ck("관측 상한이 used(2) 로 낮아짐", rN.capacity()["cap"] == 2, str(rN.capacity()))
ck("capacity free 도 관측치 반영", rN.capacity()["free"] == 0, str(rN.capacity()))

# 밴 키워드(신호 없음)는 상한을 낮추지 않는다 — 오탐 방지가 핵심
dN2 = tempfile.mkdtemp()
qN2 = SweepQueue(os.path.join(dN2, "q.json"))
fN2 = CapAwareFleet(banned={"짝퉁2"})
rN2 = KeywordRouter(fN2, qN2, slot_cap=5, routes_fp=os.path.join(dN2, "routes.json"))
rN2.add("A")                            # used=1
rN2.add("짝퉁2")                        # 신호 없는 실패
ck("밴 실패는 관측 안 함(cap 그대로)", rN2.capacity()["cap"] == 5, str(rN2.capacity()))

# failed=0(유효 계정 없음) 이면 fleet_full 이 켜져 있어도 관측 안 함
class WeirdFleet:
    def register_all(self, keywords, min_price=None, max_price=None,
                     exclude_keywords=None, log=None, core_only=False):
        return {"added": 0, "skipped": 0, "failed": 0, "fleet_full": True}


dQ = tempfile.mkdtemp()
rQ = KeywordRouter(WeirdFleet(), SweepQueue(os.path.join(dQ, "q.json")),
                   slot_cap=6, routes_fp=os.path.join(dQ, "routes.json"))
rQ.add("샤넬")
ck("failed=0 이면 fleet_full 있어도 관측 안 함",
   rQ.capacity()["cap"] == 6, str(rQ.capacity()))

# 관측은 재시작해도 유지된다
rN3 = KeywordRouter(CapAwareFleet(limited={"신상2"}),
                    SweepQueue(os.path.join(dN, "q3.json")),
                    slot_cap=5, routes_fp=fpN)
ck("재시작 후에도 관측 상한 유지", rN3.capacity()["cap"] == 2, str(rN3.capacity()))

# 상한은 스스로 오르지 않는다: used 가 줄어도 cap 은 그대로다
rN3.remove("A")
ck("used 가 줄어도 관측 상한은 그대로(오직 하강만)",
   rN3.capacity()["cap"] == 2, str(rN3.capacity()))

# 더 낮은 used 에서 다시 fleet_full 신호가 오면 추가 하강은 허용된다
rN3.add("신상2")
ck("더 낮은 used 로 재관측 가능(추가 하강)", rN3.capacity()["cap"] == 1, str(rN3.capacity()))

# ── O. 관측치가 깨져도 기본 상한으로 안전하게 저하 ──
dO = tempfile.mkdtemp()
fpO = os.path.join(dO, "routes.json")
with open(fpO, "w", encoding="utf-8") as f:
    _json.dump({"A": {"route": "app", "reason": "x", "at": 1},
               _CAP_META_KEY: "이것도 저것도 아님"}, f, ensure_ascii=False)
rO = KeywordRouter(FakeAlerts(), SweepQueue(os.path.join(dO, "q.json")),
                   slot_cap=7, routes_fp=fpO)
ck("깨진 관측치는 기본 상한으로", rO.capacity()["cap"] == 7, str(rO.capacity()))
ck("깨진 관측치여도 라우트는 정상 로드", rO.capacity()["used"] == 1, str(rO.capacity()))

dO2 = tempfile.mkdtemp()
fpO2 = os.path.join(dO2, "routes.json")
with open(fpO2, "w", encoding="utf-8") as f:
    _json.dump({_CAP_META_KEY: {"observed": "abc"}}, f, ensure_ascii=False)
rO2 = KeywordRouter(FakeAlerts(), SweepQueue(os.path.join(dO2, "q.json")),
                    slot_cap=9, routes_fp=fpO2)
ck("observed 가 숫자 아니면 기본 상한", rO2.capacity()["cap"] == 9, str(rO2.capacity()))

# ── P. 관측치를 되돌리는 두 경로: 명시적 reset, seed_from_server ──
dP = tempfile.mkdtemp()
fpP = os.path.join(dP, "routes.json")
qP = SweepQueue(os.path.join(dP, "q.json"))
fP = CapAwareFleet(limited={"한도"})
rP = KeywordRouter(fP, qP, slot_cap=4, routes_fp=fpP)
rP.add("X")                  # used=1
rP.add("한도")               # fleet_full → 관측 1
ck("사전조건: 관측됨", rP.capacity()["cap"] == 1, str(rP.capacity()))
ck("reset 은 True 반환", rP.reset_observed_cap() is True)
ck("reset 후 기본 상한으로", rP.capacity()["cap"] == 4, str(rP.capacity()))
ck("이미 초기화된 상태에서 reset 은 False", rP.reset_observed_cap() is False)
rP2 = KeywordRouter(CapAwareFleet(), SweepQueue(os.path.join(dP, "q2.json")),
                    slot_cap=4, routes_fp=fpP)
ck("reset 은 영속됨(재시작 후에도 기본 상한)", rP2.capacity()["cap"] == 4, str(rP2.capacity()))

dP3 = tempfile.mkdtemp()
fpP3 = os.path.join(dP3, "routes.json")
qP3 = SweepQueue(os.path.join(dP3, "q.json"))
fP3 = CapAwareFleet(limited={"한도3"})
rP3 = KeywordRouter(fP3, qP3, slot_cap=4, routes_fp=fpP3)
rP3.add("Y")                 # used=1
rP3.add("한도3")             # fleet_full at used=1 → 관측 1
ck("사전조건: 관측됨(seed 케이스)", rP3.capacity()["cap"] == 1, str(rP3.capacity()))
rP3.remove("Y"); rP3.remove("한도3")
ck("routes 다 지워짐", rP3.routes() == [])
ck("routes 지운다고 관측치가 저절로 안 지워짐",
   rP3.capacity()["cap"] == 1, str(rP3.capacity()))
n = rP3.seed_from_server(["Z"])
ck("씨딩 성공", n == 1)
ck("씨딩이 관측치를 씻어냄", rP3.capacity()["cap"] == 4, str(rP3.capacity()))

# ── Q. 실측 상한(observed_count) — "측정, 추론 아님" ──
class CountAwareFleet:
    """register_all 이 keyword_alert_api 의 실제 모양(added/skipped/failed +
    실패 시 observed_count)을 흉내낸다. ok 는 성공, 그 외는 실패하며
    fail_counts 에 있으면 그 계정 실측 보유수를 함께 보낸다."""

    def __init__(self, ok=(), fail_counts=None):
        self.ok = set(ok)
        self.fail_counts = dict(fail_counts or {})
        self.calls = []

    def register_all(self, keywords, min_price=None, max_price=None,
                     exclude_keywords=None, log=None, core_only=False):
        self.calls.append(list(keywords))
        kw = keywords[0]
        if kw in self.ok:
            return {"added": 1, "skipped": 0, "failed": 0}
        out = {"added": 0, "skipped": 0, "failed": 1}
        if kw in self.fail_counts:
            out["observed_count"] = self.fail_counts[kw]
        return out


def _fill(router, kws):
    for kw in kws:
        router.add(kw)


# used 이상인 실측값 → 만원. 상한은 실측값이 아니라 used 로 내려간다
# (실측값에는 라우터가 모르는 키워드가 섞여 있어 그대로 쓰면 수렴하지 않는다)
dQ1 = tempfile.mkdtemp()
fQ1 = CountAwareFleet(ok={"A", "B", "C", "D", "E"}, fail_counts={"F": 12})
rQ1 = KeywordRouter(fQ1, SweepQueue(os.path.join(dQ1, "q.json")), slot_cap=30,
                    routes_fp=os.path.join(dQ1, "routes.json"))
_fill(rQ1, ["A", "B", "C", "D", "E"])
ck("사전조건: used=5", rQ1.capacity()["used"] == 5, str(rQ1.capacity()))
res = rQ1.add("F")
ck("실측 실패는 sweep", res["route"] == "sweep", str(res))
ck("count>=used 면 만원 — 상한은 used 로", rQ1.capacity()["cap"] == 5,
   str(rQ1.capacity()))
ck("만원이면 free 는 0(수렴)", rQ1.capacity()["free"] == 0, str(rQ1.capacity()))

# used 보다 낮은 실측값(뒤처진 계정) → 상한의 증거 아님, 낮추지 않는다
dQ2 = tempfile.mkdtemp()
fQ2 = CountAwareFleet(ok={"A", "B", "C", "D", "E"}, fail_counts={"G": 2})
rQ2 = KeywordRouter(fQ2, SweepQueue(os.path.join(dQ2, "q.json")), slot_cap=30,
                    routes_fp=os.path.join(dQ2, "routes.json"))
_fill(rQ2, ["A", "B", "C", "D", "E"])
rQ2.add("G")
ck("count < used 는 무시(뒤처짐, 상한 증거 아님)",
   rQ2.capacity()["cap"] == 30, str(rQ2.capacity()))

# 실측값이 지금 믿는 상한 이상이어도(그 계정이 이미 꽉 참) 거부는 거부다 —
# 남은 슬롯 0. 라우터가 쓸 수 있는 슬롯은 자기가 넣은 것뿐이므로 used 로.
dQ3 = tempfile.mkdtemp()
fQ3 = CountAwareFleet(ok={"A"}, fail_counts={"H": 30})
rQ3 = KeywordRouter(fQ3, SweepQueue(os.path.join(dQ3, "q.json")), slot_cap=30,
                    routes_fp=os.path.join(dQ3, "routes.json"))
_fill(rQ3, ["A"])
rQ3.add("H")
ck("count >= 현재 상한이어도 만원으로 수렴", rQ3.capacity()["cap"] == 1,
   str(rQ3.capacity()))
ck("그래서 더 시도하지 않는다", rQ3.capacity()["free"] == 0, str(rQ3.capacity()))

# used=0(성공 이력 없음)일 때는 비교 기준이 없어 건너뛴다
dQ4 = tempfile.mkdtemp()
fQ4 = CountAwareFleet(fail_counts={"I": 5})
rQ4 = KeywordRouter(fQ4, SweepQueue(os.path.join(dQ4, "q.json")), slot_cap=30,
                    routes_fp=os.path.join(dQ4, "routes.json"))
rQ4.add("I")
ck("used=0 이면 실측값 무시", rQ4.capacity()["cap"] == 30, str(rQ4.capacity()))

# 상한은 실측으로도 스스로 오르지 않는다 — 더 낮은 값만 반영
dQ5 = tempfile.mkdtemp()
fQ5 = CountAwareFleet(ok={"A", "B", "C"}, fail_counts={"X": 3, "Y": 1})
rQ5 = KeywordRouter(fQ5, SweepQueue(os.path.join(dQ5, "q.json")), slot_cap=10,
                    routes_fp=os.path.join(dQ5, "routes.json"))
_fill(rQ5, ["A", "B", "C"])
rQ5.add("X")
ck("1차 실측 하향", rQ5.capacity()["cap"] == 3, str(rQ5.capacity()))
fQ5.ok = set(); fQ5.fail_counts = {"X": 9}
rQ5.add("X")
ck("더 높은 재측정으로는 오르지 않음", rQ5.capacity()["cap"] == 3, str(rQ5.capacity()))

# 재시작해도 실측 하향은 유지된다
rQ1b = KeywordRouter(CountAwareFleet(), SweepQueue(os.path.join(dQ1, "q2.json")),
                     slot_cap=30, routes_fp=os.path.join(dQ1, "routes.json"))
ck("재시작 후에도 실측 상한 유지", rQ1b.capacity()["cap"] == 5, str(rQ1b.capacity()))

# reset_observed_cap 은 실측으로 낮아진 것도 되돌린다
ck("reset 은 실측 관측치도 지움", rQ1b.reset_observed_cap() is True)
ck("reset 후 기본 상한으로", rQ1b.capacity()["cap"] == 30, str(rQ1b.capacity()))

# ── R. 리뷰어 재현: 관측 상한이 실제로 수렴한다 ──
class ServerCapFleet:
    """진짜 서버 상한(cap)이 있는 함대.

    이 브랜치 이전의 일괄등록 경로로 pre 개가 이미 들어 있는데 routes 파일은
    비어 있지 않아 seed_from_server 가 열리지 않은 상태 — 라우터의 used 는
    서버 실보유수보다 pre 만큼 적다. 한도에 걸리면 keyword_alert_api.
    register_all 과 같은 모양(실패 + 그 계정 실측 보유수)으로 돌려준다."""

    def __init__(self, cap=20, pre=5):
        self.cap = cap
        self.held = pre
        self.calls = []

    def register_all(self, keywords, min_price=None, max_price=None,
                     exclude_keywords=None, log=None, core_only=False):
        self.calls.append(list(keywords))
        added = 0
        for _ in keywords:
            if self.held >= self.cap:
                break
            self.held += 1
            added += 1
        if added == len(keywords):
            return {"added": added, "skipped": 0, "failed": 0}
        return {"added": added, "skipped": 0, "failed": len(keywords) - added,
                "observed_count": self.held}


dR = tempfile.mkdtemp()
qR = SweepQueue(os.path.join(dR, "q.json"))
fR = ServerCapFleet(cap=20, pre=5)
rR = KeywordRouter(fR, qR, slot_cap=30, routes_fp=os.path.join(dR, "routes.json"))
for i in range(15):
    rR.add(f"K{i}")
ck("재현 사전조건: used=15", rR.capacity()["used"] == 15, str(rR.capacity()))
ck("재현 사전조건: 서버는 20개로 만원", fR.held == 20, str(fR.held))

res = rR.add("초과1")                     # 첫 거부 — observed_count=20
ck("첫 거부는 sweep", res["route"] == "sweep", str(res))
ck("첫 거부 뒤 free 는 0 (수렴)", rR.capacity()["free"] == 0, str(rR.capacity()))
ck("관측 상한은 라우터가 쓸 수 있는 슬롯수(used)로 수렴",
   rR.capacity()["cap"] == 15, str(rR.capacity()))

# 만원을 알게 된 뒤로는 새 키워드에 요청을 전혀 태우지 않는다
n_before = len(fR.calls)
for i in range(5):
    rR.add(f"초과추가{i}")
ck("수렴 뒤 새 키워드는 요청 0", len(fR.calls) == n_before, str(len(fR.calls)))

# rebalance 가 큐 전체를 훑지 않는다
for i in range(25):
    qR.add(f"대기{i}", at=5000 + i)
n_before = len(fR.calls)
ck("만원이면 rebalance 무동작", rR.rebalance() == [])
ck("만원이면 rebalance 요청 0", len(fR.calls) == n_before, str(len(fR.calls)))

# 틱 도중에 만원을 알게 되면 그 자리에서 멈춘다(큐 25개를 다 훑지 않는다)
dR2 = tempfile.mkdtemp()
qR2 = SweepQueue(os.path.join(dR2, "q.json"))
fR2 = ServerCapFleet(cap=20, pre=20)      # 이미 꽉 참
rR2 = KeywordRouter(fR2, qR2, slot_cap=30,
                    routes_fp=os.path.join(dR2, "routes.json"))
rR2._routes["기존"] = {"route": "app", "reason": "이전 등록", "at": 1}
for i in range(25):
    qR2.add(f"대기{i}", at=6000 + i)
ck("사전조건: 라우터는 아직 여유가 있다고 믿는다",
   rR2.capacity()["free"] == 29, str(rR2.capacity()))
ck("틱 도중 만원이면 승격 없음", rR2.rebalance() == [])
ck("틱 도중 만원을 알면 즉시 멈춘다(큐 전체를 훑지 않음)",
   len(fR2.calls) == 1, str(len(fR2.calls)))

# ── S. add_many 는 들어갈 만큼을 한 번에 묶는다 ──
dS = tempfile.mkdtemp()
aS = FakeAlerts()
qS = SweepQueue(os.path.join(dS, "q.json"))
rS = KeywordRouter(aS, qS, slot_cap=10, routes_fp=os.path.join(dS, "routes.json"))
outS = rS.add_many(["A", "B", "C", "D"])
ck("배치는 register_all 을 한 번만 부른다", len(aS.calls) == 1, str(aS.calls))
ck("한 번에 다 실린다", aS.calls[0]["keywords"] == ["A", "B", "C", "D"],
   str(aS.calls))
ck("결과는 키워드별", [o["keyword"] for o in outS] == ["A", "B", "C", "D"],
   str(outS))
ck("전부 app", [o["route"] for o in outS] == ["app"] * 4, str(outS))
ck("배치 등록도 슬롯을 먹는다", rS.capacity()["used"] == 4, str(rS.capacity()))

# 슬롯에 들어갈 만큼만 묶고, 넘치는 몫엔 요청을 쓰지 않는다
aS2, qS2, rS2 = mk(slot_cap=2)
outS2 = rS2.add_many(["P", "Q", "R"])
ck("들어갈 만큼만 배치", aS2.calls[0]["keywords"] == ["P", "Q"], str(aS2.calls))
ck("넘치는 몫엔 요청 없음", len(aS2.calls) == 1, str(aS2.calls))
ck("넘치는 몫은 sweep", outS2[2]["route"] == "sweep", str(outS2))

# 부분 실패는 배치로 귀속할 수 없다 → 키워드별로 다시 태워 사유·백오프를 남긴다
dS3 = tempfile.mkdtemp()
aS3 = FakeAlerts(banned={"짝퉁"})
qS3 = SweepQueue(os.path.join(dS3, "q.json"))
rS3 = KeywordRouter(aS3, qS3, slot_cap=10,
                    routes_fp=os.path.join(dS3, "routes.json"))
outS3 = rS3.add_many(["A", "짝퉁", "B"])
ck("부분 실패는 키워드별 결과로 귀속",
   [o["route"] for o in outS3] == ["app", "sweep", "app"], str(outS3))
ck("부분 실패분에 백오프 기록", rS3.retry_after("짝퉁") > 0,
   str(rS3.retry_after("짝퉁")))
ck("성공분만 슬롯 차지", rS3.capacity()["used"] == 2, str(rS3.capacity()))

# 배치가 통째로 거부되면 개별 재시도 전에 상한을 관측해 요청을 더 안 쓴다
dS4 = tempfile.mkdtemp()
qS4 = SweepQueue(os.path.join(dS4, "q.json"))
fS4 = ServerCapFleet(cap=5, pre=5)          # 서버는 이미 만원
rS4 = KeywordRouter(fS4, qS4, slot_cap=30,
                    routes_fp=os.path.join(dS4, "routes.json"))
rS4.seed_from_server(["가", "나", "다"])     # used=3 (서버엔 우리가 모르는 2개 더)
outS4 = rS4.add_many(["X", "Y", "Z"])
ck("배치 통째 거부는 요청 1회로 끝난다", len(fS4.calls) == 1, str(fS4.calls))
ck("배치 통째 거부 뒤엔 전부 sweep",
   [o["route"] for o in outS4] == ["sweep"] * 3, str(outS4))
ck("배치 거부에서도 상한이 수렴", rS4.capacity()["cap"] == 3, str(rS4.capacity()))

# 결과 모양은 입력 그대로(빈 키워드·중복 포함)
aS5, qS5, rS5 = mk(slot_cap=10)
outS5 = rS5.add_many(["A", "", "A", "B"])
ck("결과 개수는 입력과 같다", len(outS5) == 4, str(outS5))
ck("빈 키워드는 route 없음", outS5[1]["route"] is None, str(outS5))
ck("중복은 배치에 한 번만", aS5.calls[0]["keywords"] == ["A", "B"], str(aS5.calls))
ck("중복도 app 결과", outS5[2]["route"] == "app", str(outS5))
ck("중복·빈 값에 추가 요청 없음", len(aS5.calls) == 1, str(aS5.calls))

# ── T. 생산자 쪽(keyword_alert_api) — 라우터가 읽는 값을 실제로 만드는 코드 ──
from daangn_ext import keyword_alert_api as _kapi


class _StubAPI(_kapi.KeywordAlertAPI):
    """네트워크 없는 KeywordAlertAPI. __init__ 을 건너뛰어 httpx 클라이언트를
    만들지 않고, 목록/차단/등록만 흉내낸다. list_calls 로 목록 조회 횟수를
    센다 — 실패 경로에서 조회가 늘어나는 회귀를 잡는 게 목적."""

    def __init__(self, held=(), banned=(), cap=None):
        self.held = [str(k) for k in held]
        self.banned = set(banned)
        self.cap = cap
        self.list_calls = 0

    def keywords(self):
        self.list_calls += 1
        return [{"keyword": k, "id": str(i)} for i, k in enumerate(self.held)]

    def is_banned(self, keyword):
        return keyword in self.banned

    def register(self, keyword, min_price=None, max_price=None,
                 exclude_keywords=None, category_ids=None):
        if self.cap is not None and len(self.held) >= self.cap:
            raise RuntimeError("400 keyword limit exceeded")
        self.held.append(keyword)
        return {"keyword": keyword}


_orig_sleep = _kapi.time.sleep
_kapi.time.sleep = lambda *a, **k: None      # 등록 간 0.6초 대기는 테스트에 불필요

# 차단 키워드 실패: 보유수를 이미 받아온 목록에서 계산한다(추가 조회 없음)
tA = _StubAPI(held=["a", "b", "c"], banned={"짝퉁"})
outT = tA.register_many(["짝퉁"])
ck("실패 시 account_count 를 보고한다", "account_count" in outT, str(outT))
ck("보고값이 실제 보유수", outT["account_count"] == len(tA.held) == 3, str(outT))
ck("실패해도 목록 조회는 1회뿐", tA.list_calls == 1, str(tA.list_calls))

# 일부 성공 + 한도 초과 실패: existing + added 가 지금 보유수다
tB = _StubAPI(held=["a", "b", "c"], cap=4)
outTB = tB.register_many(["새1", "새2"])
ck("일부 성공 시 보고값 = 기존+추가", outTB["account_count"] == 4, str(outTB))
ck("보고값이 서버 실제와 일치", outTB["account_count"] == len(tB.held), str(tB.held))
ck("일부 성공에도 목록 조회 1회", tB.list_calls == 1, str(tB.list_calls))
ck("added/failed 는 그대로", (outTB["added"], len(outTB["failed"])) == (["새1"], 1),
   str(outTB))

# 성공만 하면 보고할 게 없다(라우터도 안 본다) — 요청도 그대로
tC = _StubAPI(held=["a"])
outTC = tC.register_many(["새"])
ck("성공 경로엔 account_count 없음", "account_count" not in outTC, str(outTC))
ck("성공 경로 목록 조회 1회", tC.list_calls == 1, str(tC.list_calls))

# skip_existing=False 면 세어둔 목록이 없으니 그때만 실측한다
tD = _StubAPI(held=["a", "b"], banned={"짝퉁"})
outTD = tD.register_many(["짝퉁"], skip_existing=False)
ck("skip_existing=False 는 실측으로 보고", outTD["account_count"] == 2, str(outTD))
ck("skip_existing=False 의 조회는 폴백 1회뿐", tD.list_calls == 1, str(tD.list_calls))


class _StubMulti(_kapi.MultiAccountAlerts):
    """계정 목록만 가짜인 MultiAccountAlerts — register_all 본체를 그대로 탄다."""

    def __init__(self, apis):
        super().__init__()
        self._apis = list(apis)

    def _valid(self, core_only=False):
        return [(f"acct{i}", "tok", None) for i in range(len(self._apis))]


def _with_stub_apis(apis, fn):
    box = {"i": 0}

    def make(access, config_path=None, proxy=None):
        api = apis[box["i"] % len(apis)]
        box["i"] += 1
        return api

    orig = _kapi.KeywordAlertAPI
    _kapi.KeywordAlertAPI = make
    try:
        return fn()
    finally:
        _kapi.KeywordAlertAPI = orig


# 실패한 계정들의 실측 보유수 중 최댓값이 observed_count 로 올라온다
tE1 = _StubAPI(held=[f"k{i}" for i in range(12)], banned={"짝퉁"})
tE2 = _StubAPI(held=[f"k{i}" for i in range(30)], banned={"짝퉁"})
mE = _StubMulti([tE1, tE2])
totalE = _with_stub_apis([tE1, tE2], lambda: mE.register_all(["짝퉁"]))
ck("register_all 이 observed_count 를 보고한다", "observed_count" in totalE,
   str(totalE))
ck("observed_count 는 실패 계정 실측의 최댓값", totalE["observed_count"] == 30,
   str(totalE))
ck("실패 합계는 계정 수만큼", totalE["failed"] == 2, str(totalE))

# 전부 성공하면 observed_count 는 없다
tF1 = _StubAPI(held=["a"])
tF2 = _StubAPI(held=["a"])
mF = _StubMulti([tF1, tF2])
totalF = _with_stub_apis([tF1, tF2], lambda: mF.register_all(["새"]))
ck("성공만 하면 observed_count 없음", "observed_count" not in totalF, str(totalF))
ck("added 는 계정 수만큼", totalF["added"] == 2, str(totalF))

# 생산자→소비자 한 바퀴: 진짜 register_all 반환으로 라우터가 수렴한다
tG = _StubAPI(held=[f"기존{i}" for i in range(20)], cap=20)   # 서버 상한 20, 만원
mG = _StubMulti([tG])
dT = tempfile.mkdtemp()
rT = KeywordRouter(mG, SweepQueue(os.path.join(dT, "q.json")), slot_cap=30,
                   routes_fp=os.path.join(dT, "routes.json"))
rT.seed_from_server([f"기존{i}" for i in range(15)])    # 라우터는 15개만 안다
ck("사전조건: used=15, 서버 실보유 20", rT.capacity()["used"] == 15 and len(tG.held) == 20,
   str(rT.capacity()))
resT = _with_stub_apis([tG], lambda: rT.add("초과"))
ck("진짜 반환값으로도 sweep", resT["route"] == "sweep", str(resT))
ck("진짜 반환값으로도 free 가 0 으로 수렴", rT.capacity()["free"] == 0,
   str(rT.capacity()))

_kapi.time.sleep = _orig_sleep

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

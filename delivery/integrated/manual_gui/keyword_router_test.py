"""키워드 라우터 테스트 (네트워크 불필요).

    python keyword_router_test.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from daangn_ext.keyword_router import KeywordRouter, DEFAULT_SLOT_CAP
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

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

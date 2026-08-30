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

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

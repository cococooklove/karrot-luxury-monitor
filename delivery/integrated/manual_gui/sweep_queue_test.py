"""스윕 대기열 테스트 (네트워크 불필요).

    python sweep_queue_test.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json

from daangn_ext.sweep_queue import SweepQueue

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


d = tempfile.mkdtemp()
p = os.path.join(d, "q.json")

q = SweepQueue(p)
ck("빈 큐 길이 0", len(q) == 0)
ck("빈 큐 keywords", q.keywords() == [])

ck("추가 성공", q.add("샤넬", min_price=100, at=10) is True)
ck("중복 추가는 False", q.add("샤넬", at=11) is False)
ck("길이 1", len(q) == 1)
ck("keywords", q.keywords() == ["샤넬"])
e = q.entries()[0]
ck("entry min", e["min"] == 100, str(e))
ck("entry at", e["at"] == 10, str(e))
ck("entry exclude 기본 빈 리스트", e["exclude"] == [], str(e))

q.add("루이비통", at=20)
q.add("에르메스", at=30)
ck("오래된 순", q.keywords() == ["샤넬", "루이비통", "에르메스"])
ck("oldest(2)", [x["keyword"] for x in q.oldest(2)] == ["샤넬", "루이비통"])

ck("삭제 성공", q.remove("루이비통") is True)
ck("없는 것 삭제는 False", q.remove("없음") is False)
ck("삭제 반영", q.keywords() == ["샤넬", "에르메스"])

# 영속 — 다시 열면 그대로다
q2 = SweepQueue(p)
ck("재시작 후 유지", q2.keywords() == ["샤넬", "에르메스"], str(q2.keywords()))

# 파일이 깨져도 빈 큐로 시작한다(예외를 올리지 않는다)
with open(p, "w", encoding="utf-8") as f:
    f.write("{깨진 json")
q3 = SweepQueue(p)
ck("깨진 파일은 빈 큐", q3.keywords() == [])
ck("깨진 뒤에도 추가 가능", q3.add("구찌", at=40) is True)

# 없는 디렉토리도 만들어 준다
p4 = os.path.join(d, "sub", "deep", "q.json")
q4 = SweepQueue(p4)
q4.add("프라다", at=50)
ck("디렉토리 자동 생성", os.path.exists(p4))

# ── 반환값은 내부 상태를 공유하지 않는다 ──
qm = SweepQueue(os.path.join(d, "mut.json"))
qm.add("발렌시아가", exclude=["가품"], at=60)
got = qm.entries()[0]
got["exclude"].append("오염")
ck("entries 의 exclude 변이가 큐에 안 샘",
   qm.entries()[0]["exclude"] == ["가품"], str(qm.entries()[0]["exclude"]))
got2 = qm.oldest(1)[0]
got2["exclude"].append("오염2")
ck("oldest 의 exclude 변이가 큐에 안 샘",
   qm.oldest(1)[0]["exclude"] == ["가품"], str(qm.oldest(1)[0]["exclude"]))

# ── touch: 승격 실패한 키워드를 맨 뒤로 보낸다 ──
import time as _time

pt = os.path.join(d, "touch.json")
qt = SweepQueue(pt)
qt.add("짝퉁", at=1000)
qt.add("구찌", at=2000)
qt.add("에르메스", at=3000)
ck("touch 전 순서", qt.keywords() == ["짝퉁", "구찌", "에르메스"], str(qt.keywords()))
ck("touch 는 True", qt.touch("짝퉁") is True)
ck("touch 하면 맨 뒤", qt.keywords() == ["구찌", "에르메스", "짝퉁"], str(qt.keywords()))
ck("touch 가 at 을 지금으로", qt.entries()[-1]["at"] >= int(_time.time()) - 5,
   str(qt.entries()[-1]))
ck("없는 키워드 touch 는 False", qt.touch("없음") is False)
ck("touch 는 항목을 늘리지 않음", len(qt) == 3)
qt.touch("구찌", at=9999)
ck("touch(at=) 명시값 적용",
   qt.keywords() == ["에르메스", "구찌", "짝퉁"], str(qt.keywords()))
ck("touch 가 파일에 남음",
   SweepQueue(pt).keywords() == qt.keywords(), str(SweepQueue(pt).keywords()))

pt2 = os.path.join(d, "touch2.json")
qt2 = SweepQueue(pt2)
qt2.add("샤넬", 100, 200, ["가품"], at=10)
qt2.touch("샤넬", at=77)
e = qt2.entries()[0]
ck("touch 가 조건을 안 지움",
   (e["min"], e["max"], e["exclude"], e["at"]) == (100, 200, ["가품"], 77), str(e))

# ── 추가키워드·끌올일수가 재시작을 견딘다 ──
# _load / _copy / add 세 곳이 각자 키를 나열하고 있어, 하나만 고치면 나머지가
# 조용히 걷어냈다. 파일에 썼다가 새 인스턴스로 다시 읽는 왕복으로 확인한다.
dp = os.path.join(tempfile.mkdtemp(), "persist.json")
qp = SweepQueue(dp)
qp.add("샤넬", 100, 200, ["가품"], at=10, extra=["정품"], days=30)
reopened = SweepQueue(dp).entries()[0]
ck("재시작 후 추가키워드 유지", reopened.get("extra") == ["정품"], str(reopened))
ck("재시작 후 끌올일수 유지", reopened.get("days") == 30, str(reopened))
ck("재시작 후 가격·제외도 유지",
   (reopened["min"], reopened["max"], reopened["exclude"]) == (100, 200, ["가품"]),
   str(reopened))
with open(dp, encoding="utf-8") as f:
    raw = json.load(f)[0]
ck("파일에 실제로 적힌다", (raw.get("extra"), raw.get("days")) == (["정품"], 30),
   str(raw))

# ── 같은 키워드를 다시 넣으면 조건이 갱신된다 ──
# 엑셀을 고쳐 다시 불러오는 것은 정상 흐름이다. 갱신을 안 하면 표는 새 값을,
# 스윕은 옛 값을 쓴다.
qu = SweepQueue(os.path.join(tempfile.mkdtemp(), "upd.json"))
qu.add("구찌", 1, 2, ["가품"], at=5, extra=["정품"], days=7)
qu.add("구찌", 10, 20, ["레플"], at=9, extra=["빈티지"], days=30)
ck("중복 키워드는 한 건", len(qu) == 1, str(qu.entries()))
u = qu.entries()[0]
ck("갱신된 추가키워드", u.get("extra") == ["빈티지"], str(u))
ck("갱신된 끌올일수", u.get("days") == 30, str(u))
ck("갱신된 가격·제외", (u["min"], u["max"], u["exclude"]) == (10, 20, ["레플"]), str(u))
ck("대기 시각은 처음 것을 지킨다", u["at"] == 5, str(u))

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

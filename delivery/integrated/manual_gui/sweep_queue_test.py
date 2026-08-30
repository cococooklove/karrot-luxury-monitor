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

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

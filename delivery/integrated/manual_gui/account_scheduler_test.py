"""계정 안정화 스케줄러 — 캡 0 = 무제한, 캡 >0 은 종전대로, 격리는 캡과 무관.

    python account_scheduler_test.py
"""
import os
import sys
import json
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from daangn_ext.account_scheduler import AccountScheduler

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


def _mk(daily_cap, n=2):
    d = tempfile.mkdtemp()
    fp = os.path.join(d, "accounts.json")
    json.dump([{"code": f"{i}00000000", "access": "t", "proxy": f"http://p{i}"}
               for i in range(n)], open(fp, "w"))
    return AccountScheduler(accounts_fp=fp, state_fp=os.path.join(d, "state.json"),
                            daily_cap=daily_cap, warmup_days=3, cooldown_sec=60)


print("=== 캡 0 = 상한 없음 ===")
s = _mk(0)
ck("기본 daily_cap 은 0", AccountScheduler.__init__.__defaults__[2] == 0,
   str(AccountScheduler.__init__.__defaults__))
p = s.pick()
ck("잔여가 None(무제한)", p and p["remaining"] is None, str(p))
s.note(p["code"], 20000)          # 서울·경기 1,857동 × 조건 10 규모
p2 = s.pick(); p3 = s.pick()
ck("2만 방문 뒤에도 그 계정이 다시 뽑힌다(라운드로빈만)",
   p2 and p3 and {p2["code"], p3["code"]} == {"000000000", "100000000"},
   f"{p2 and p2['code']} {p3 and p3['code']}")
ck("상태 문자열에 ∞", "∞" in s.status(), s.status())
s.note_block(p["code"])
q = [s.pick()["code"] for _ in range(4)]
ck("격리는 캡과 무관하게 동작(격리된 계정은 안 뽑힘)", p["code"] not in q, str(q))

print("\n=== 캡 >0 은 종전 동작 ===")
s = _mk(30)
p = s.pick()
ck("첫날 워밍업 캡 = 30/3 = 10", p["remaining"] == 10, str(p))
s.note(p["code"], 10)
codes = {s.pick()["code"] for _ in range(3)}
ck("캡 찬 계정은 건너뛴다", p["code"] not in codes, str(codes))
s.note("100000000", 10)
ck("전부 차면 None", s.pick() is None)

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

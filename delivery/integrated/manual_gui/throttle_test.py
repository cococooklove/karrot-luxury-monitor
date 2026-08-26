"""자동감속·쿨다운 일원화·워커 클램프 테스트 (네트워크 불필요).

    python throttle_test.py
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from daangn_ext import proxy_budget, throttle
from daangn.proxy_manager import ProxyManager
import daangn.proxy_manager as pmmod

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


print("=== A. 자동감속 AIMD ===")
throttle.reset()
ck("초기 배속 1.0", throttle.factor() == 1.0)
throttle.observe("RATELIMIT")
ck("429 1회 → x1.5", abs(throttle.factor() - 1.5) < 1e-9, throttle.factor())
throttle.observe("BLOCKED")
ck("403 추가 → x2.25", abs(throttle.factor() - 2.25) < 1e-9, throttle.factor())
for _ in range(30):
    throttle.observe("EMPTY")
ck("빈응답은 감속 사유 아님", abs(throttle.factor() - 2.25) < 1e-9, throttle.factor())
for _ in range(19):
    throttle.observe("OK")
ck("성공 19회는 회복 전", abs(throttle.factor() - 2.25) < 1e-9, throttle.factor())
throttle.observe("OK")
ck("성공 20회 → x0.9 회복", abs(throttle.factor() - 2.025) < 1e-9, throttle.factor())
for _ in range(50):
    throttle.observe("RATELIMIT")
ck("상한 x8 클램프", throttle.factor() == 8.0, throttle.factor())
ck("대기시간에 배수 적용", throttle.scale(1000) == 8000)
ck("휴식구간에 배수 적용", throttle.scale_range((0.4, 1.2)) == (3.2, 9.6))
throttle.reset()
for _ in range(200):
    throttle.observe("OK")
ck("하한 x1 클램프", throttle.factor() == 1.0, throttle.factor())

print("=== B. 무사고 시간 기반 회복 ===")
throttle.reset()
calm, throttle.CALM_SEC = throttle.CALM_SEC, 0.3
throttle.observe("RATELIMIT")
throttle.observe("RATELIMIT")
ck("2회 감속 x2.25", abs(throttle.factor() - 2.25) < 1e-9, throttle.factor())
throttle.observe("EMPTY")
ck("무사고 시간 전엔 유지", abs(throttle.factor() - 2.25) < 1e-9, throttle.factor())
time.sleep(0.35)
throttle.observe("EMPTY")
ck("무사고 경과 → 성공 없이도 회복", abs(throttle.factor() - 2.025) < 1e-9, throttle.factor())
throttle.CALM_SEC = calm
throttle.reset()

print("=== C. 쿨다운 일원화 (ProxyManager ↔ proxy_budget) ===")
proxy_budget.reset()
POOL = ["p1", "p2", "p3"]
pm = ProxyManager(POOL, min_delay_ms=0)
ev = threading.Event()
proxy_budget.mark_exhausted("p1", 600)
got = {pm.acquire(ev) for _ in range(30)}
ck("429 쿨다운 IP 는 배정 안 됨", "p1" not in got, sorted(got))
ck("나머지 IP 는 정상 배정", got == {"p2", "p3"}, sorted(got))
ck("status 가 쿨다운 반영",
   pm.status() == {"total": 3, "cooling": 1, "alive": 2}, pm.status())

proxy_budget.reset()
for p in POOL:
    proxy_budget.mark_exhausted(p, 1800)
stall, pmmod.MAX_STALL_SEC = pmmod.MAX_STALL_SEC, 0.2
pm2 = ProxyManager(POOL, min_delay_ms=0)
t0 = time.time()
picked = pm2.acquire(ev)
elapsed = time.time() - t0
pmmod.MAX_STALL_SEC = stall
ck("풀 전체 쿨다운이면 멈추지 않고 진행",
   picked in POOL and elapsed < 2.0, f"{picked}, {elapsed:.2f}s")
proxy_budget.reset()

print("=== D. 감속이 프록시 간격에 반영 ===")
throttle.reset()
pm3 = ProxyManager(["a"], min_delay_ms=100)
ck("배속 x1 → 0.1s", abs(pm3._min_delay_sec - 0.1) < 1e-9, pm3._min_delay_sec)
throttle.observe("RATELIMIT")
ck("배속 x1.5 → 0.15s", abs(pm3._min_delay_sec - 0.15) < 1e-9, pm3._min_delay_sec)
throttle.reset()

print("=== E. 동시요청 수 클램프 ===")


def clamp(proxies, workers):
    return max(1, min(workers, len(proxies))) if proxies else workers


ck("프록시 3 < 워커 16 → 3", clamp(["a", "b", "c"], 16) == 3)
ck("프록시 20 > 워커 16 → 16", clamp(["a"] * 20, 16) == 16)
ck("프록시 없음 → 설정값 유지", clamp([], 16) == 16)

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

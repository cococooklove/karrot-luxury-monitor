"""감시 컨트롤러 테스트 (네트워크 불필요).

    python supervisor_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from daangn_ext.supervisor import SupervisorController, SupervisorPolicy

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


class FakeTimer:
    def __init__(self):
        self.active = False
        self._interval = 0
        self.starts = []

    def start(self, ms):
        self.active = True
        self._interval = int(ms)
        self.starts.append(int(ms))

    def stop(self):
        self.active = False

    def isActive(self):
        return self.active

    def setInterval(self, ms):
        self._interval = int(ms)

    def interval(self):
        return self._interval


class FakeQueue:
    def __init__(self, n=0):
        self.n = n

    def __len__(self):
        return self.n


def mk(queue_n=0, poll=120, night=1):
    pt, stt = FakeTimer(), FakeTimer()
    calls = {"start": 0, "stop": 0}
    pol = SupervisorPolicy(lambda: poll, lambda: night, sweep_interval=600)
    c = SupervisorController(
        pol, pt, stt, FakeQueue(queue_n),
        start_search_sweep=lambda: calls.__setitem__("start", calls["start"] + 1),
        stop_search_sweep=lambda: calls.__setitem__("stop", calls["stop"] + 1))
    return c, pt, stt, calls


# ── A. 정책 ──
pol = SupervisorPolicy(lambda: 120, lambda: 3, sweep_interval=600)
ck("폴링 ms", pol.poll_ms() == 120 * 3 * 1000, str(pol.poll_ms()))
ck("스윕 ms", pol.sweep_ms() == 600 * 3 * 1000, str(pol.sweep_ms()))
pol2 = SupervisorPolicy(lambda: 120, lambda: 1, sweep_interval=600)
ck("배수 1이면 그대로", pol2.poll_ms() == 120000, str(pol2.poll_ms()))

# ── B. start 는 두 타이머를 켠다 ──
c, pt, stt, calls = mk()
ck("시작 전 안 돎", c.is_running() is False)
c.start()
ck("실행 중", c.is_running() is True)
ck("폴링 타이머 켜짐", pt.isActive() is True)
ck("스윕 타이머 켜짐", stt.isActive() is True)
ck("폴링 간격", pt.interval() == 120000, str(pt.interval()))
ck("스윕 간격", stt.interval() == 600000, str(stt.interval()))

# ── C. 큐가 비면 검색 스윕은 안 띄운다 ──
ck("빈 큐면 검색스윕 미기동", calls["start"] == 0, str(calls))

c2, pt2, stt2, calls2 = mk(queue_n=3)
c2.start()
ck("큐 있으면 검색스윕 기동", calls2["start"] == 1, str(calls2))

# ── D. stop ──
c2.stop()
ck("정지 후 안 돎", c2.is_running() is False)
ck("폴링 타이머 꺼짐", pt2.isActive() is False)
ck("스윕 타이머 꺼짐", stt2.isActive() is False)
ck("검색스윕 정지 호출", calls2["stop"] == 1, str(calls2))

# ── E. 중복 start 는 무해하다 ──
c3, pt3, stt3, calls3 = mk(queue_n=1)
c3.start(); c3.start()
ck("중복 start 는 한 번만 기동", calls3["start"] == 1, str(calls3))
ck("타이머 재시작 안 함", len(pt3.starts) == 1, str(pt3.starts))

# ── F. 야간 배수 변경 반영 ──
factor = {"v": 1}
pol4 = SupervisorPolicy(lambda: 120, lambda: factor["v"], sweep_interval=600)
pt4, stt4 = FakeTimer(), FakeTimer()
c4 = SupervisorController(pol4, pt4, stt4, FakeQueue(0),
                          start_search_sweep=lambda: None,
                          stop_search_sweep=lambda: None)
c4.start()
factor["v"] = 3
c4.retune()
ck("retune 이 폴링 간격 갱신", pt4.interval() == 360000, str(pt4.interval()))
ck("retune 이 스윕 간격 갱신", stt4.interval() == 1800000, str(stt4.interval()))
c4.stop()
factor["v"] = 1
c4.retune()
ck("정지 중 retune 은 무동작", pt4.isActive() is False)

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

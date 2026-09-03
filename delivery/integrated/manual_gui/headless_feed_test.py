"""헤드리스 피드 러너 수명 — 가짜 엔진·스레드 (네트워크·Qt 없음)."""
import os, sys
app_dir = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, app_dir); os.chdir(app_dir)
R = []
def ck(name, cond, extra=""):
    R.append((name, bool(cond))); print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")
import main as m

class FakeEngine:
    def __init__(self, cfg, log, found): self.cfg, self.stopped = cfg, False
    def run(self): pass
    def stop(self): self.stopped = True
class FakeThread:
    def __init__(self, target): self.target, self.alive = target, False
    def start(self): self.alive = True
    def is_alive(self): return self.alive
    def join(self, t=None): self.alive = False
logs, found = [], []
r = m.HeadlessFeedRunner(lambda: {"regions": ["역삼동-6035"], "categories": [31]}, logs.append, found.append,
                         engine_factory=lambda cfg, log, on_found: FakeEngine(cfg, log, on_found),
                         thread_factory=lambda target: FakeThread(target))
ck("시작", r.start() is True and r.running())
ck("시작 로그", any("[피드]" in x for x in logs))
ck("중복 시작 거절", r.start() is False)
r.stop(join=1)
ck("정지 → 엔진 stop + 스레드 종료", r.engine.stopped and not r.running())
r2 = m.HeadlessFeedRunner(lambda: {"regions": [], "categories": [31]}, logs.append, found.append,
                          engine_factory=lambda *a: FakeEngine(*a), thread_factory=lambda t: FakeThread(t))
ck("지역 없으면 시작 안 함", r2.start() is False)
n_ok = sum(1 for _, c in R if c); print(f"\n{n_ok}/{len(R)} PASS"); sys.exit(0 if n_ok == len(R) else 1)

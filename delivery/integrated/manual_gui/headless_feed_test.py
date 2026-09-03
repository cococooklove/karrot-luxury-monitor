"""헤드리스 피드 러너 수명 — 가짜 엔진·스레드 (네트워크·Qt 없음)."""
import os, sys
app_dir = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, app_dir); os.chdir(app_dir)
R = []
def ck(name, cond, extra=""):
    R.append((name, bool(cond))); print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")
import main as m

class FakeEngine:
    def __init__(self, cfg, log, found):
        self.cfg, self.stopped = cfg, False
        self.stop_reason, self.stopped_at = None, 0.0
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

# ── 프록시 전멸 백오프 ──
# 죽은 프록시로는 몇 번을 다시 띄워도 첫 요청에서 같은 자리에 눕는다.
# 30분 물러서고, 그 사이 로그는 한 번만 남긴다(틱마다 쌓이면 로그가 못 쓰게 된다).
import time as _t
from daangn.feed_sweep import FeedSweep as _FS
blogs = []
r3 = m.HeadlessFeedRunner(lambda: {"regions": ["역삼동-6035"], "categories": [31]},
                          blogs.append, found.append,
                          engine_factory=lambda cfg, log, on_found: FakeEngine(cfg, log, on_found),
                          thread_factory=lambda target: FakeThread(target))
ck("첫 시작은 된다", r3.start() is True)
r3.thread.alive = False                       # 엔진이 프록시 전멸로 죽었다
r3.engine.stop_reason, r3.engine.stopped_at = "proxies", _t.monotonic()
blogs.clear()
ck("백오프 중에는 시작을 거절한다",
   [r3.start() for _ in range(3)] == [False, False, False])
ck("백오프 로그는 한 번만", sum(1 for x in blogs if "프록시" in x) == 1, str(blogs))
r3.engine.stopped_at = _t.monotonic() - _FS.PROXY_BACKOFF_SEC - 1
ck("백오프가 지나면 다시 뜬다", r3.start() is True)
r4 = m.HeadlessFeedRunner(lambda: {"regions": ["역삼동-6035"], "categories": [31]},
                          blogs.append, found.append,
                          engine_factory=lambda cfg, log, on_found: FakeEngine(cfg, log, on_found),
                          thread_factory=lambda target: FakeThread(target))
r4.start(); r4.thread.alive = False
r4.engine.stop_reason, r4.engine.stopped_at = "stopped", _t.monotonic()
ck("손으로 세운 것은 백오프가 아니다", r4.start() is True)

# ── --once 는 앞 10동만 ──
# 배포 직후 '살아 있나' 확인이 목적이다. 1,857동을 다 돌면 배포가 한 시간 멎는다.
_once_logs = []
_big = {"regions": [f"동{i}-{i}" for i in range(50)], "categories": [31]}
_cut = m.feed_once_cfg(_big, _once_logs.append)
ck("--once 는 앞 10동만", _cut["regions"] == _big["regions"][:10], str(len(_cut["regions"])))
ck("--once 안내 로그", any("앞 10동만" in x for x in _once_logs), str(_once_logs))
ck("원본 cfg 는 안 건드린다", len(_big["regions"]) == 50)
_small = {"regions": ["역삼동-6035"], "categories": [31]}
_once_logs.clear()
ck("10동 이하면 그대로·로그 없음",
   m.feed_once_cfg(_small, _once_logs.append) is _small and not _once_logs)
ck("--once 경로가 이 함수를 쓴다", "feed_once_cfg" in m._run_headless.__code__.co_names)

# drain_sweep_finds — 피드/스윕 payload 를 라벨·source 로 갈라 넣는다.
import queue as _queue
class FakeTracker:
    def __init__(self): self.calls = []
    def add_from_matches(self, norms, source="app"):
        self.calls.append((source, [n["keyword"] for n in norms]))
        return len(norms)
q = _queue.Queue()
q.put({"id": "https://d/x", "title": "t", "price": 1000, "region": "r", "url": "https://d/x",
       "boostedAt": "", "keyword": "루이비통 오버 더 문", "verdict": "hit", "status": "신규"})
q.put({"id": "123", "title": "샤넬 백", "price": 1, "region": "r", "url": "u", "boostedAt": ""})
tracker = FakeTracker()
n_added = m.drain_sweep_finds(q, tracker, lambda: ["샤넬"], logs.append)
ck("드레인 합계 2건", n_added == 2)
ck("피드 호출 — 라벨 그대로", ("feed", ["루이비통 오버 더 문"]) in tracker.calls)
ck("스윕 호출 — 대기열 키워드로 라벨링", ("sweep", ["샤넬"]) in tracker.calls)
ck("SOURCE_NAMES 에 feed 있음", m.SOURCE_NAMES.get("feed"))

n_ok = sum(1 for _, c in R if c); print(f"\n{n_ok}/{len(R)} PASS"); sys.exit(0 if n_ok == len(R) else 1)

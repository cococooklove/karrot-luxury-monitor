"""함대 전체 기동 보장 — ensure_ldplayer / _harvest_all_locked.

지키는 것:
  A. 기기가 하나라도 있으면 끝내지 않는다. list2 의 인스턴스별 androidStarted 로
     미기동분을 전부 골라 켠다(오늘 클라 서버: 6대 중 1대만 살아 5대 방치).
  B. adb devices 목록은 증거가 아니다 — 대답(shell echo)해야 살아있는 것으로 센다.
  C. 순차 기동(동시 launch 는 게스트 커널이 안 뜨는 하드 실패) + gap 유지.
  D. 예산 상한 — 6대 × 180s 로 호출자를 물리지 않는다. 남은 건 다음 틱이 잇는다.
  E. 고장난 인스턴스가 나머지를 막지 않는다 + 사이클당 재기동 횟수 상한 +
     연속 실패는 다음 사이클 후순위(예산 선점 방지).
  F. ldconsole 없음 / 인스턴스 0 이면 예전과 같이 행동한다.
  G. _harvest_all_locked 이 함대 보장을 거쳐 수확한다. 프로세스 락은 그대로.

이 기계엔 adb/ldconsole 이 없다 — 콘솔/adb 호출을 전부 가짜로 주입한다.
가짜 serial 문자열("dev-3" 등)은 일부러 포트 산술과 무관하게 지었다: 코드가
인덱스→serial 매핑을 가정하지 않는다는 것 자체를 이 테스트가 함께 보장한다.
"""
import os
import sys
import types
import threading

os.chdir(os.path.dirname(os.path.abspath(__file__)))

R = []


def ck(name, cond, extra=""):
    R.append(bool(cond))
    print(("  ok  " if cond else "  FAIL") + f" {name}" + (f"  | {extra}" if extra and not cond else ""))


import ld_autoharvest as ld


# ── 가짜 시계: 실제로 자지 않고 가상시간만 흘린다 ────────────────────────────
class Clock:
    def __init__(self, t0=1000.0):
        self.t = float(t0)

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += float(s)


# ── 가짜 함대 ────────────────────────────────────────────────────────────────
class Fleet:
    """states: 'up'(부팅+응답), 'hung'(adb 기기로 보이지만 무응답), 'down'(없음)."""

    def __init__(self, clock, n=6, up=(), hung=(), broken=(), boot_delay=20):
        self.clock = clock
        self.n = n
        self.broken = set(broken)
        self.boot_delay = boot_delay
        self.state = {}
        for i in range(n):
            self.state[i] = "up" if i in up else ("hung" if i in hung else "down")
        self.ready_at = {}          # idx -> 부팅 완료 시각
        self.calls = []             # ("launch"|"quit", idx) 순서
        self.probes = []            # 응답 확인이 실제로 나갔는지

    def serial(self, i):
        return f"dev-{i}"

    def _settle(self):
        for i, t in list(self.ready_at.items()):
            if self.clock.t >= t:
                self.state[i] = "up"
                del self.ready_at[i]

    # -- 주입 대상 --
    def list_instances(self, adb_bin):
        self._settle()
        return [self.serial(i) for i in range(self.n) if self.state[i] in ("up", "hung")]

    def responsive(self, adb_bin, serial, timeout=None):
        self._settle()
        self.probes.append(serial)
        for i in range(self.n):
            if self.serial(i) == serial:
                return self.state[i] == "up"
        return False

    def ld_list(self, console):
        self._settle()
        # ldconsole list2 → (index, name, androidStarted)
        return [(str(i), f"LD-{i}", self.state[i] in ("up", "hung")) for i in range(self.n)]

    def ld_launch(self, console, idx):
        i = int(idx)
        self.calls.append(("launch", i))
        if i not in self.broken and self.state[i] != "up":
            self.ready_at[i] = self.clock.t + self.boot_delay
        return True

    def ld_quit(self, console, idx):
        i = int(idx)
        self.calls.append(("quit", i))
        self.state[i] = "down"
        self.ready_at.pop(i, None)
        return True

    def launches(self):
        return [i for k, i in self.calls if k == "launch"]


def run(fleet, clock, console="C:/fake/ldconsole.exe", **kw):
    """ensure_ldplayer 를 가짜 함대 위에서 돌린다. 로그 줄 리스트도 돌려준다."""
    logs = []
    saved = (ld.time, ld.list_instances, ld._responsive, ld.ld_list,
             ld.ld_launch, ld.ld_quit, ld.find_ldconsole)
    ld.time = types.SimpleNamespace(time=clock.time, sleep=clock.sleep)
    ld.list_instances = fleet.list_instances
    ld._responsive = fleet.responsive
    ld.ld_list = fleet.ld_list
    ld.ld_launch = fleet.ld_launch
    ld.ld_quit = fleet.ld_quit
    ld.find_ldconsole = lambda a=None: console
    try:
        out = ld.ensure_ldplayer("adb", log=logs.append, **kw)
    finally:
        (ld.time, ld.list_instances, ld._responsive, ld.ld_list,
         ld.ld_launch, ld.ld_quit, ld.find_ldconsole) = saved
    return out, logs


def reset_fails():
    ld._BOOT_FAILS.clear()


print("=== A. 미기동 인스턴스를 전부 켠다(부분 결손이 오늘의 결함) ===")
reset_fails()
c = Clock()
f = Fleet(c, n=6, up=(0,))
out, logs = run(f, c)
ck("살아있던 idx0 은 다시 안 켠다", 0 not in f.launches(), str(f.calls))
ck("나머지 5개를 전부 켠다", sorted(f.launches()) == [1, 2, 3, 4, 5], str(f.launches()))
ck("6개 serial 을 돌려준다", sorted(out) == [f"dev-{i}" for i in range(6)], str(out))
ck("예전처럼 '기기 있음'으로 조기 반환하지 않는다", len(f.launches()) == 5)

print("=== A2. 전부 떠 있으면 아무것도 켜지 않는다 ===")
reset_fails()
c = Clock()
f = Fleet(c, n=6, up=tuple(range(6)))
out, logs = run(f, c)
ck("launch 0회", f.calls == [], str(f.calls))
ck("quit 0회", not any(k == "quit" for k, _ in f.calls))
ck("전원 반환", len(out) == 6, str(out))
ck("추가 기동 불필요를 남긴다", any("추가 기동 불필요" in x for x in logs), str(logs))

print("=== B. 응답 확인 — adb devices 목록은 증거가 아니다 ===")
reset_fails()
c = Clock()
# idx0 은 기기로 보이지만 hang, 나머지는 down → 응답기기 0 → 전부 재기동 대상
f = Fleet(c, n=3, hung=(0,))
out, logs = run(f, c)
ck("hang 인스턴스를 살아있는 것으로 세지 않는다", "dev-0" not in out or f.state[0] == "up", str(out))
ck("hang 이라도 기동 대상이 된다", 0 in f.launches(), str(f.calls))
ck("hang 은 quit 먼저", ("quit", 0) in f.calls and
   f.calls.index(("quit", 0)) < f.calls.index(("launch", 0)), str(f.calls))
ck("전원 무응답을 크게 남긴다", any("모두 무응답" in x for x in logs), str(logs))
ck("응답 확인이 실제로 나갔다", "dev-0" in f.probes, str(f.probes))

print("=== B2. 부분 무응답은 지목하지 않는다(멀쩡한 걸 죽이지 않는다) ===")
reset_fails()
c = Clock()
f = Fleet(c, n=4, up=(0,), hung=(1,))
out, logs = run(f, c)
ck("무응답 idx1 을 quit 하지 않는다", ("quit", 1) not in f.calls, str(f.calls))
ck("idx1 을 켜려 들지도 않는다", 1 not in f.launches(), str(f.calls))
ck("androidStarted=0 인 2,3 만 켠다", sorted(f.launches()) == [2, 3], str(f.launches()))
ck("부분 결손을 크게 남긴다", any("특정할 수 없어" in x for x in logs), str(logs))

print("=== B3. _responsive 는 타임아웃 있는 shell echo 를 쓴다 ===")
_seen = []


def _fake_adb(adb_bin, serial, *args, timeout=30):
    _seen.append((serial, args, timeout))
    if serial == "hang":
        raise RuntimeError("timeout")
    return "ok\r\n"


_sv = ld._adb
ld._adb = _fake_adb
try:
    ck("응답하면 True", ld._responsive("adb", "good") is True)
    ck("무응답이면 False", ld._responsive("adb", "hang") is False)
finally:
    ld._adb = _sv
ck("shell echo 로 확인", _seen and _seen[0][1] == ("shell", "echo", "ok"), str(_seen[:1]))
ck("타임아웃을 건다", _seen and _seen[0][2] == ld.PROBE_TIMEOUT, str(_seen[:1]))
ck("PROBE_TIMEOUT 은 짧다", 0 < ld.PROBE_TIMEOUT <= 15, str(ld.PROBE_TIMEOUT))

print("=== C. 순차 기동 + gap 유지 ===")
reset_fails()
c = Clock()
f = Fleet(c, n=4, boot_delay=20)


class _SeqFleet(Fleet):
    """launch 시각을 같이 기록해 '앞 인스턴스가 뜨기 전에 다음을 켜지 않음'을 본다."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.launch_t = []

    def ld_launch(self, console, idx):
        self.launch_t.append((int(idx), self.clock.t))
        return super().ld_launch(console, idx)


c = Clock()
f = _SeqFleet(c, n=4, boot_delay=20)
out, logs = run(f, c, gap=35, boot_wait=180)
ck("인덱스 순서대로 켠다", f.launches() == [0, 1, 2, 3], str(f.launches()))
_gaps = [f.launch_t[i + 1][1] - f.launch_t[i][1] for i in range(len(f.launch_t) - 1)]
ck("launch 사이 간격 >= boot+gap", all(g >= 35 for g in _gaps), str(_gaps))
ck("동시 기동 없음(각 launch 전에 이전 것이 응답)", all(g >= 20 + 35 for g in _gaps), str(_gaps))

print("=== D. 예산 상한 ===")
reset_fails()
c = Clock()
f = Fleet(c, n=6, boot_delay=20)
out, logs = run(f, c, gap=35, boot_wait=180, budget=50)
ck("예산이 끊기면 남은 인스턴스는 다음 틱으로", len(f.launches()) == 1, str(f.launches()))
ck("예산 소진을 크게 남긴다", any("예산" in x and "소진" in x for x in logs), str(logs))
ck("예산 안에 뜬 건 반환된다", out == ["dev-0"], str(out))
ck("FLEET_BOOT_BUDGET 기본 600초", ld.FLEET_BOOT_BUDGET == 600.0, str(ld.FLEET_BOOT_BUDGET))
ck("예산 < 20분 폴링주기", ld.FLEET_BOOT_BUDGET < 1200, str(ld.FLEET_BOOT_BUDGET))

reset_fails()
c = Clock()
f = Fleet(c, n=6, boot_delay=20)
_t0 = c.t
out, logs = run(f, c, gap=35, boot_wait=180, budget=600)
ck("예산 안이면 전원 기동", len(out) == 6, str(out))
ck("총 소요가 예산 부근을 넘지 않는다", c.t - _t0 <= 600 + 180, str(c.t - _t0))

print("=== E. 고장 인스턴스가 나머지를 막지 않는다 ===")
reset_fails()
c = Clock()
f = Fleet(c, n=4, broken=(1,), boot_delay=20)
out, logs = run(f, c, gap=5, boot_wait=30, budget=10000)
ck("고장난 1을 건너뛰고 2,3 을 켠다", 2 in f.launches() and 3 in f.launches(), str(f.launches()))
ck("고장난 것도 결국 살아난 것들은 반환", sorted(out) == ["dev-0", "dev-2", "dev-3"], str(out))
ck("기동 실패를 남긴다", any("기동 실패" in x and "건너뜁니다" in x for x in logs), str(logs))

print("=== E2. 사이클당 재기동 횟수 상한(adb 폭주 방지) ===")
ck("고장난 인스턴스 launch 는 retry+1 회", f.launches().count(1) == ld.BOOT_RETRY + 1,
   str(f.launches()))
ck("BOOT_RETRY 는 1", ld.BOOT_RETRY == 1, str(ld.BOOT_RETRY))
ck("재기동 전에 quit 1회", [k for k, i in f.calls if i == 1].count("quit") == ld.BOOT_RETRY,
   str(f.calls))

print("=== E3. 연속 실패는 다음 사이클 후순위 ===")
reset_fails()
c = Clock()
f = Fleet(c, n=3, broken=(0,), boot_delay=20)
run(f, c, gap=5, boot_wait=30, budget=10000)
ck("1사이클: 고장 0 이 먼저 시도된다", f.launches()[0] == 0, str(f.launches()))
ck("실패 카운트가 남는다", ld._BOOT_FAILS.get("0", 0) >= 1, str(ld._BOOT_FAILS))
ck("성공한 인스턴스는 카운트 없음", "1" not in ld._BOOT_FAILS, str(ld._BOOT_FAILS))
c2 = Clock()
f2 = Fleet(c2, n=3, broken=(0,), boot_delay=20)
run(f2, c2, gap=5, boot_wait=30, budget=10000)
ck("2사이클: 고장 0 은 맨 뒤로 밀린다", f2.launches()[-1] == 0, str(f2.launches()))
ck("멀쩡한 것들이 먼저 예산을 쓴다", f2.launches()[:2] == [1, 2], str(f2.launches()))
reset_fails()

print("=== F. ldconsole 없음 / 인스턴스 0 — 예전과 같은 행동 ===")
c = Clock()
f = Fleet(c, n=2, up=(0, 1))
out, logs = run(f, c, console=None)
ck("콘솔 없으면 켜지 않는다", f.calls == [], str(f.calls))
ck("콘솔 없어도 응답기기는 반환", sorted(out) == ["dev-0", "dev-1"], str(out))

c = Clock()
f = Fleet(c, n=0)
out, logs = run(f, c)
ck("기기·인스턴스 0 이면 빈 리스트", out == [], str(out))
ck("복원 필요를 남긴다", any(".ldbk" in x for x in logs), str(logs))

c = Clock()
f = Fleet(c, n=2)
out, logs = run(f, c, console=None)
ck("콘솔 없고 기기도 없으면 안내를 남긴다",
   any("ldconsole" in x for x in logs) and out == [], str(logs))

print("=== G. _harvest_all_locked 이 함대를 보장하고 수확한다 ===")
_ens = []
_sv_ens, _sv_li, _sv_h1, _sv_fa = (ld.ensure_ldplayer, ld.list_instances,
                                   ld.harvest_one, ld.find_adb)
ld.find_adb = lambda x=None: "adb"
ld.list_instances = lambda a: ["dev-0"]          # 예전 코드라면 여기서 끝났다
ld.ensure_ldplayer = lambda a, **k: (_ens.append(1), ["dev-0", "dev-1"])[1]
ld.harvest_one = lambda a, s, **k: None          # 수확 결과 없음 → 병합 안 함
try:
    _res = ld._harvest_all_locked("./nope.json", None, None, True, lambda m: None)
    ck("기기가 보여도 함대 보장을 부른다", _ens == [1], str(_ens))
    ck("수확 0이면 (0,0,0,0)", _res == (0, 0, 0, 0), str(_res))

    _ens.clear()
    _res = ld._harvest_all_locked("./nope.json", None, ["given-1"], True, lambda m: None)
    ck("serial 을 명시하면 함대 보장을 건너뛴다", _ens == [], str(_ens))
finally:
    (ld.ensure_ldplayer, ld.list_instances, ld.harvest_one, ld.find_adb) = (
        _sv_ens, _sv_li, _sv_h1, _sv_fa)

ck("_harvest_all_locked 소스가 ensure_ldplayer 를 쓴다",
   "ensure_ldplayer" in ld._harvest_all_locked.__code__.co_names)
ck("함대 기동 전에 조기반환하는 list_instances 경로가 없다",
   "list_instances" not in ld._harvest_all_locked.__code__.co_names,
   str(ld._harvest_all_locked.__code__.co_names))

print("=== G2. 프로세스 락 의미가 그대로다 ===")
_order = []
_sv_inner = ld._harvest_all_locked


def _slow(*a, **k):
    _order.append("in")
    import time as _t
    _t.sleep(0.15)
    _order.append("out")
    return (0, 0, 0, 0)


ld._harvest_all_locked = _slow
try:
    ts = [threading.Thread(target=lambda: ld.harvest_all("./nope.json")) for _ in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
finally:
    ld._harvest_all_locked = _sv_inner
ck("harvest_all 은 프로세스 안에서 직렬화된다",
   _order == ["in", "out"] * 3, str(_order))
ck("_HARVEST_LOCK 유지", isinstance(ld._HARVEST_LOCK, type(threading.Lock())))
ck("merge_accounts 가 _MERGE_LOCK + 파일락을 모두 잡는다",
   "_MERGE_LOCK" in ld.merge_accounts.__code__.co_names and
   "_file_lock" in ld.merge_accounts.__code__.co_names,
   str(ld.merge_accounts.__code__.co_names))

passed = sum(1 for x in R if x)
print(f"===== {passed}/{len(R)} PASS =====")
sys.exit(0 if passed == len(R) else 1)

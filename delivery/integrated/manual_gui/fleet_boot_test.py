"""함대 전체 기동 보장 — ensure_ldplayer / _harvest_all_locked.

지키는 것:
  A. 기기가 하나라도 있으면 끝내지 않는다. list2 의 인스턴스별 상태로 미기동분을
     전부 골라 켠다(오늘 클라 서버: 6대 중 1대만 살아 5대 방치).
  B. 판정은 **인덱스별 프로브**다: `ldconsole adb --index N --command
     "shell echo PROBE_OK"`. ldconsole 이 serial 을 스스로 풀어주므로 포트 산술을
     지어낼 필요가 없고, 집계가 아니라 인스턴스 단위로 조치할 수 있다.
     androidStarted=1 인데 무응답인 인스턴스(= 클라 서버 현재 상태)도 지목된다.
  C. 무응답 인스턴스 처리: 프로세스가 남아 있으면 quit → 소멸 확인 → launch,
     아무것도 없으면 그냥 launch.
     프로세스가 살아 있으면 LDPlayer 는 launch 를 조용히 무시한다 — 가짜 함대가
     그 동작을 그대로 흉내내므로, quit 을 빠뜨리면 이 스위트가 실패한다.
  D. 순차 기동(동시 launch 는 게스트 커널이 안 뜨는 하드 실패) + gap 유지.
  E. 예산 상한 — 6대 × 180s 로 호출자를 물리지 않는다. 남은 건 다음 틱이 잇는다.
  F. 고장난 인스턴스가 나머지를 막지 않는다 + 사이클당 재기동 횟수 상한 +
     연속 실패는 다음 사이클 후순위(예산 선점 방지).
  G. quit 이 안 먹으면 pid 강제 종료로 승격하고, 그래도 안 죽으면 건너뛴다
     (안 죽은 채로 launch 하면 no-op 이라 아무 의미가 없다). 어느 경우도 무한대기 없음.
  H. ldconsole 없음 / 인스턴스 0 이면 예전과 같이 행동한다.
  I. _harvest_all_locked 이 함대 보장을 거쳐 수확한다. 프로세스 락은 그대로.

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
# 상태:
#   'up'      : androidStarted=1 · pid 있음 · adb 기기 응답
#   'zombie'  : androidStarted=0 · pid 있음 · adb 기기 **없음**  ← 클라 서버 실상태
#   'ghost'   : androidStarted=1 · pid 있음 · adb 기기는 있는데 무응답
#   'down'    : 아무것도 없음
_PROC = ("up", "zombie", "ghost")
_DEV = ("up", "ghost")


class Fleet:
    def __init__(self, clock, n=6, up=(), zombie=(), ghost=(), broken=(),
                 boot_delay=20, quit_fails=(), kill_fails=()):
        self.clock = clock
        self.n = n
        self.broken = set(broken)              # launch 해도 안드로이드가 안 뜬다
        self.quit_fails = set(quit_fails)      # ldconsole quit 이 안 먹는다
        self.kill_fails = set(kill_fails)      # taskkill 도 안 먹는다
        self.boot_delay = boot_delay
        self.state = {}
        for i in range(n):
            self.state[i] = ("up" if i in up else "zombie" if i in zombie
                             else "ghost" if i in ghost else "down")
        self.ready_at = {}
        self.calls = []          # ("launch"|"quit"|"kill", idx)
        self.probes = []
        self.noop_launches = []  # 프로세스가 살아 있는 채로 들어온 launch(= 무시됨)

    def serial(self, i):
        return f"dev-{i}"

    def pid(self, i):
        return 9000 + i

    def _settle(self):
        for i, t in list(self.ready_at.items()):
            if self.clock.t >= t:
                self.state[i] = "zombie" if i in self.broken else "up"
                del self.ready_at[i]

    # -- 주입 대상 --
    def list_instances(self, adb_bin):
        self._settle()
        return [self.serial(i) for i in range(self.n) if self.state[i] in _DEV]

    def responsive(self, adb_bin, serial, timeout=None):
        """serial 기준 응답 — 반환값(수확기에 넘길 목록) 생성에만 쓰인다."""
        self._settle()
        for i in range(self.n):
            if self.serial(i) == serial:
                return self.state[i] == "up"
        return False

    def ld_probe(self, console, index, token=None, timeout=None):
        """`ldconsole adb --index N` — 인덱스로 직접 묻는다. 켜고 죽일 대상은
        전부 이 결과가 정한다."""
        self._settle()
        i = int(index)
        self.probes.append(i)
        return self.state.get(i) == "up"

    def ld_rows(self, console):
        self._settle()
        out = []
        for i in range(self.n):
            st = self.state[i]
            booting = i in self.ready_at
            out.append({"index": str(i), "name": f"LD-{i}",
                        "started": st in ("up", "ghost"),
                        "pids": [self.pid(i)] if (st in _PROC or booting) else []})
        return out

    def ld_launch(self, console, idx):
        i = int(idx)
        self.calls.append(("launch", i))
        self._settle()
        if self.state[i] in _PROC or i in self.ready_at:
            # LDPlayer 실동작: 프로세스가 살아 있으면 '이미 실행중'으로 보고
            # 아무것도 하지 않은 채 성공을 반환한다.
            self.noop_launches.append(i)
            return True
        self.ready_at[i] = self.clock.t + self.boot_delay
        return True

    def ld_quit(self, console, idx):
        i = int(idx)
        self.calls.append(("quit", i))
        if i in self.quit_fails:
            return True                  # 성공을 반환하지만 실제로는 안 죽는다
        self.state[i] = "down"
        self.ready_at.pop(i, None)
        return True

    def kill_pid(self, pid):
        i = int(pid) - 9000
        self.calls.append(("kill", i))
        if i in self.kill_fails:
            return True
        self.state[i] = "down"
        self.ready_at.pop(i, None)
        return True

    def launches(self):
        return [i for k, i in self.calls if k == "launch"]

    def first(self, kind, i):
        try:
            return self.calls.index((kind, i))
        except ValueError:
            return -1


def run(fleet, clock, console="C:/fake/ldconsole.exe", **kw):
    logs = []
    names = ("time", "list_instances", "_responsive", "ld_probe", "ld_rows",
             "ld_launch", "ld_quit", "ld_kill_pid", "find_ldconsole")
    saved = {n: getattr(ld, n) for n in names}
    ld.time = types.SimpleNamespace(time=clock.time, sleep=clock.sleep)
    ld.list_instances = fleet.list_instances
    ld._responsive = fleet.responsive
    ld.ld_probe = fleet.ld_probe
    ld.ld_rows = fleet.ld_rows
    ld.ld_launch = fleet.ld_launch
    ld.ld_quit = fleet.ld_quit
    ld.ld_kill_pid = fleet.kill_pid
    ld.find_ldconsole = lambda a=None: console
    try:
        out = ld.ensure_ldplayer("adb", log=logs.append, **kw)
    finally:
        for n, v in saved.items():
            setattr(ld, n, v)
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

print("=== C. 3상태 분류 — 클라 서버 실상태(1대 정상 · 5대 프로세스만 살아있음) ===")
reset_fails()
c = Clock()
f = Fleet(c, n=6, up=(0,), zombie=(1, 2, 3, 4, 5))
out, logs = run(f, c, budget=100000)
ck("응답중인 idx0 은 quit 도 launch 도 안 한다",
   f.first("quit", 0) == -1 and f.first("launch", 0) == -1, str(f.calls))
for i in (1, 2, 3, 4, 5):
    ck(f"idx{i}: quit 이 launch 보다 먼저",
       f.first("quit", i) >= 0 and f.first("quit", i) < f.first("launch", i), str(f.calls))
ck("무시되는(프로세스 살아있는) launch 는 한 번도 없었다",
   f.noop_launches == [], str(f.noop_launches))
ck("6대 전부 응답 상태가 된다", sorted(out) == [f"dev-{i}" for i in range(6)], str(out))
ck("종료부터 한다는 걸 남긴다",
   any("종료부터" in x for x in logs), str(logs))

print("=== C2. 프로세스 없는 인스턴스는 quit 없이 바로 launch ===")
reset_fails()
c = Clock()
f = Fleet(c, n=3, up=(0,))
out, logs = run(f, c)
ck("down 상태엔 quit 을 보내지 않는다",
   not any(k == "quit" for k, _ in f.calls), str(f.calls))
ck("바로 launch", sorted(f.launches()) == [1, 2], str(f.calls))

print("=== B. started 인데 무응답(ghost) — 클라 서버가 지금 갇힌 상태 ===")
# 6대 전부 androidStarted=1 인데 5대는 대답을 안 한다. 집계로는 '5/6 무응답'까지만
# 알 수 있어 예전엔 로그만 남기고 방치했다. 인덱스 프로브가 있으니 지목이 된다.
reset_fails()
c = Clock()
f = Fleet(c, n=6, up=(0,), ghost=(1, 2, 3, 4, 5))
out, logs = run(f, c, budget=100000)
ck("응답하는 idx0 은 quit 도 launch 도 안 한다",
   f.first("quit", 0) == -1 and f.first("launch", 0) == -1, str(f.calls))
for i in (1, 2, 3, 4, 5):
    ck(f"무응답 idx{i}: quit → launch (같은 인덱스)",
       0 <= f.first("quit", i) < f.first("launch", i), str(f.calls))
ck("무시되는 launch 없음", f.noop_launches == [], str(f.noop_launches))
ck("6대 전부 살아난다", sorted(out) == [f"dev-{i}" for i in range(6)], str(out))
ck("인덱스마다 프로브가 나갔다", set(f.probes) >= set(range(6)), str(f.probes))
ck("이제는 방치 문구를 남기지 않는다",
   not any("특정할 수 없어" in x for x in logs), str(logs))

print("=== B2. 응답하는 인스턴스는 절대 건드리지 않는다 ===")
reset_fails()
c = Clock()
f = Fleet(c, n=4, up=(0, 2), ghost=(1,))
out, logs = run(f, c, budget=100000)
ck("응답하는 0,2 는 quit/launch 없음",
   all(f.first(k, i) == -1 for k in ("quit", "launch") for i in (0, 2)), str(f.calls))
ck("무응답 1(ghost)·3(down)만 켠다", sorted(f.launches()) == [1, 3], str(f.calls))
ck("ghost 1 은 quit 먼저", 0 <= f.first("quit", 1) < f.first("launch", 1), str(f.calls))
ck("down 3 은 quit 없이", f.first("quit", 3) == -1, str(f.calls))

print("=== B3. ld_probe — ldconsole 이 인덱스로 직접 adb 를 태운다 ===")
_pcalls = []


class _PR:
    def __init__(self, rc, out):
        self.returncode, self.stdout = rc, out.encode("utf-8")


def _probe_sub(reply):
    def _run(cmd, **kw):
        _pcalls.append((list(cmd), kw.get("timeout")))
        return reply
    return types.SimpleNamespace(run=_run)


_svsub = ld.subprocess
try:
    ld.subprocess = _probe_sub(_PR(0, "PROBE_OK\r\n"))
    ck("토큰 단독 줄이면 응답", ld.ld_probe("C:/ld.exe", 1) is True)
    _cmd, _to = _pcalls[-1]
    ck("ldconsole adb --index N --command 형태",
       _cmd[1:] == ["adb", "--index", "1", "--command", "shell echo PROBE_OK"], str(_cmd))
    ck("PROBE_TIMEOUT 을 건다", _to == ld.PROBE_TIMEOUT, str(_to))

    # 실서버 실측 실패 출력
    ld.subprocess = _probe_sub(_PR(1, "adb.exe: device 'emulator-5560' not found\r\n"))
    ck("device not found 는 무응답", ld.ld_probe("C:/ld.exe", 3) is False)
    ld.subprocess = _probe_sub(_PR(0, "adb.exe: device 'emulator-5560' not found\r\n"))
    ck("종료코드 0 이어도 토큰 없으면 무응답", ld.ld_probe("C:/ld.exe", 3) is False)
    # ldconsole 이 명령줄을 되울리는 버전 — 부분일치였다면 오독한다
    ld.subprocess = _probe_sub(
        _PR(0, "adb --index 3 --command shell echo PROBE_OK\r\nerror: no devices\r\n"))
    ck("명령줄 되울림을 응답으로 오독하지 않는다", ld.ld_probe("C:/ld.exe", 3) is False)

    def _boom(*a, **k):
        raise RuntimeError("timeout")
    ld.subprocess = types.SimpleNamespace(run=_boom)
    ck("타임아웃/예외는 무응답", ld.ld_probe("C:/ld.exe", 3) is False)
finally:
    ld.subprocess = _svsub

print("=== B4. live_instances — 반환 serial 목록에서 hang 기기를 거른다 ===")
_seen = []


def _fake_adb(adb_bin, serial, *args, timeout=30):
    _seen.append((serial, args, timeout))
    if serial == "hang":
        raise RuntimeError("timeout")
    return "ok\r\n"


_sv = ld._adb
_svli = ld.list_instances
ld._adb = _fake_adb
ld.list_instances = lambda a: ["good", "hang"]
try:
    ck("응답하면 True", ld._responsive("adb", "good") is True)
    ck("무응답이면 False", ld._responsive("adb", "hang") is False)
    ck("hang serial 은 수확 목록에서 빠진다", ld.live_instances("adb") == ["good"],
       str(ld.live_instances("adb")))
finally:
    ld._adb = _sv
    ld.list_instances = _svli
ck("shell echo 로 확인", _seen and _seen[0][1] == ("shell", "echo", "ok"), str(_seen[:1]))
ck("타임아웃을 건다", _seen and _seen[0][2] == ld.PROBE_TIMEOUT, str(_seen[:1]))
ck("PROBE_TIMEOUT 은 짧다", 0 < ld.PROBE_TIMEOUT <= 15, str(ld.PROBE_TIMEOUT))
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

print("=== G. quit 이 안 먹으면 pid 강제 종료로 승격 ===")
reset_fails()
c = Clock()
f = Fleet(c, n=2, up=(0,), zombie=(1,), quit_fails=(1,))
out, logs = run(f, c, budget=100000)
ck("quit → kill 순서", 0 <= f.first("quit", 1) < f.first("kill", 1), str(f.calls))
ck("kill 후에 launch", f.first("kill", 1) < f.first("launch", 1), str(f.calls))
ck("결국 뜬다", "dev-1" in out, str(out))
ck("강제 종료를 남긴다", any("강제 종료" in x for x in logs), str(logs))
ck("무시된 launch 없음", f.noop_launches == [], str(f.noop_launches))

print("=== G2. quit 도 kill 도 안 먹으면 건너뛴다(무의미한 launch 금지·무한대기 금지) ===")
reset_fails()
c = Clock()
f = Fleet(c, n=4, zombie=(1,), quit_fails=(1,), kill_fails=(1,))
_t0 = c.t
out, logs = run(f, c, budget=100000)
ck("안 죽는 인스턴스엔 launch 를 보내지 않는다", 1 not in f.launches(), str(f.calls))
ck("나머지는 정상 기동", sorted(f.launches()) == [0, 2, 3], str(f.launches()))
ck("사라짐 확인은 유한하다", c.t - _t0 < 10000, str(c.t - _t0))
ck("안 내려간다고 남긴다", any("안 내려갑니다" in x for x in logs), str(logs))
ck("QUIT_WAIT/KILL_WAIT 은 유한", 0 < ld.QUIT_WAIT <= 120 and 0 < ld.KILL_WAIT <= 60,
   f"{ld.QUIT_WAIT}/{ld.KILL_WAIT}")

print("=== D. 순차 기동 + gap 유지 ===")


class _SeqFleet(Fleet):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.launch_t = []

    def ld_launch(self, console, idx):
        self.launch_t.append((int(idx), self.clock.t))
        return super().ld_launch(console, idx)


reset_fails()
c = Clock()
f = _SeqFleet(c, n=4, boot_delay=20)
out, logs = run(f, c, gap=35, boot_wait=180)
ck("인덱스 순서대로 켠다", f.launches() == [0, 1, 2, 3], str(f.launches()))
_gaps = [f.launch_t[i + 1][1] - f.launch_t[i][1] for i in range(len(f.launch_t) - 1)]
ck("launch 사이 간격 >= gap", all(g >= 35 for g in _gaps), str(_gaps))
ck("동시 기동 없음(각 launch 전에 이전 것이 응답)", all(g >= 20 + 35 for g in _gaps), str(_gaps))

print("=== E. 예산 상한 ===")
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

print("=== F. 고장 인스턴스가 나머지를 막지 않는다 ===")
reset_fails()
c = Clock()
f = Fleet(c, n=4, broken=(1,), boot_delay=20)
out, logs = run(f, c, gap=5, boot_wait=30, budget=100000)
ck("고장난 1을 건너뛰고 2,3 을 켠다", 2 in f.launches() and 3 in f.launches(), str(f.launches()))
ck("살아난 것들은 반환", sorted(out) == ["dev-0", "dev-2", "dev-3"], str(out))
ck("기동 실패를 남긴다", any("기동 실패" in x and "건너뜁니다" in x for x in logs), str(logs))
ck("재시도 전에 프로세스를 내린다(no-op launch 방지)",
   f.noop_launches == [], str(f.noop_launches))

print("=== F2. 사이클당 재기동 횟수 상한(adb 폭주 방지) ===")
ck("고장난 인스턴스 launch 는 retry+1 회", f.launches().count(1) == ld.BOOT_RETRY + 1,
   str(f.launches()))
ck("BOOT_RETRY 는 1", ld.BOOT_RETRY == 1, str(ld.BOOT_RETRY))
ck("재기동 전에 quit 1회", [k for k, i in f.calls if i == 1].count("quit") == ld.BOOT_RETRY,
   str(f.calls))

print("=== F3. 연속 실패는 다음 사이클 후순위 ===")
reset_fails()
c = Clock()
f = Fleet(c, n=3, broken=(0,), boot_delay=20)
run(f, c, gap=5, boot_wait=30, budget=100000)
ck("1사이클: 고장 0 이 먼저 시도된다", f.launches()[0] == 0, str(f.launches()))
ck("실패 카운트가 남는다", ld._BOOT_FAILS.get("0", 0) >= 1, str(ld._BOOT_FAILS))
ck("성공한 인스턴스는 카운트 없음", "1" not in ld._BOOT_FAILS, str(ld._BOOT_FAILS))
c2 = Clock()
f2 = Fleet(c2, n=3, broken=(0,), boot_delay=20)
run(f2, c2, gap=5, boot_wait=30, budget=100000)
ck("2사이클: 고장 0 은 맨 뒤로 밀린다", f2.launches()[-1] == 0, str(f2.launches()))
ck("멀쩡한 것들이 먼저 예산을 쓴다", f2.launches()[:2] == [1, 2], str(f2.launches()))
reset_fails()

print("=== H. ldconsole 없음 / 인스턴스 0 — 예전과 같은 행동 ===")
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

print("=== H2. ld_rows 파싱 — started 와 pid 를 따로 읽는다 ===")
_sv_run = ld.subprocess.run


class _P:
    def __init__(self, s):
        self.stdout = s.encode("utf-8")


_txt = ("0,LD-0,131072,262144,1,4444,5555,540,960,240\n"
        "1,LD-1,0,0,0,7777,8888,540,960,240\n"
        "2,LD-2,0,0,0,0,0,540,960,240\n"
        "쓰레기줄\n")
ld.subprocess = types.SimpleNamespace(run=lambda *a, **k: _P(_txt))
try:
    _rows = ld.ld_rows("x")
    _compat = ld.ld_list("x")
finally:
    ld.subprocess = sys.modules["subprocess"]
ck("행 3개(쓰레기 무시)", len(_rows) == 3, str(_rows))
ck("started=1 · pid 읽음", _rows[0]["started"] is True and _rows[0]["pids"] == [4444, 5555],
   str(_rows[0]))
ck("started=0 인데 pid 있음(= hang) 을 구분한다",
   _rows[1]["started"] is False and _rows[1]["pids"] == [7777, 8888], str(_rows[1]))
ck("started=0 · pid 0 은 프로세스 없음",
   _rows[2]["started"] is False and _rows[2]["pids"] == [], str(_rows[2]))
ck("ld_list 3튜플 호환 유지",
   _compat == [("0", "LD-0", True), ("1", "LD-1", False), ("2", "LD-2", False)],
   str(_compat))

print("=== I. _harvest_all_locked 이 함대를 보장하고 수확한다 ===")
_ens = []
_sv_ens, _sv_li, _sv_h1, _sv_fa = (ld.ensure_ldplayer, ld.list_instances,
                                   ld.harvest_one, ld.find_adb)
ld.find_adb = lambda x=None: "adb"
ld.list_instances = lambda a: ["dev-0"]          # 예전 코드라면 여기서 끝났다
ld.ensure_ldplayer = lambda a, **k: (_ens.append(1), ["dev-0", "dev-1"])[1]
ld.harvest_one = lambda a, s, **k: None
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

print("=== I2. 프로세스 락 의미가 그대로다 ===")
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

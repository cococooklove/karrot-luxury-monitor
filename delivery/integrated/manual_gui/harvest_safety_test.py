"""수확 소유권 · accounts.json 동시쓰기 안전성.

accounts.json 은 이 기계에서 재발급할 수 없는 세션 토큰의 유일한 사본이다.
이 스위트가 지키는 것:
  A. merge_accounts 동시호출이 깨진 파일을 승격하지 못한다(고유 임시파일 + 직렬화).
  B. harvest_all 이 프로세스 안에서 직렬화된다.
  C. 스윕의 token_provider 가 함대 수확을 트리거하지 않는다(헤드리스·GUI 양쪽).
  D. GUI 폴링 틱의 씨딩이 수확도, GUI 스레드 네트워크 호출도 하지 않는다.
  E. 프로세스 **두 개**가 겹쳐도 lost update 가 없다(accounts.json.lock 파일락)
     + 락 대기 상한 초과 시 멎지 않고 크게 남기고 진행한다 + 프로세스가 죽으면
     커널이 락을 놓는다.
"""
import os
import sys
import json
import time
import types
import shutil
import tempfile
import threading
import subprocess

os.chdir(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

R = []


def ck(name, cond, extra=""):
    R.append(bool(cond))
    print(("  ok  " if cond else "  FAIL") + f" {name}" + (f"  | {extra}" if extra and not cond else ""))


import ld_autoharvest as ld
import main as m


print("=== A. merge_accounts 동시쓰기 ===")


class _SlowJson:
    """dump 를 잘게 쪼개 쓰는 느린 writer — 직렬화가 없으면 뒤섞임이 드러난다."""

    def __init__(self, real, delay=0.002, chunk=16):
        self._real, self._delay, self._chunk = real, delay, chunk

    def load(self, *a, **k):
        return self._real.load(*a, **k)

    def loads(self, *a, **k):
        return self._real.loads(*a, **k)

    def dumps(self, *a, **k):
        return self._real.dumps(*a, **k)

    def dump(self, obj, fp, **kw):
        s = self._real.dumps(obj, **kw)
        for i in range(0, len(s), self._chunk):
            fp.write(s[i:i + self._chunk])
            time.sleep(self._delay)


_d = tempfile.mkdtemp(prefix="harvsafe_")
_fp = os.path.join(_d, "accounts.json")
with open(_fp, "w", encoding="utf-8") as f:
    json.dump([], f)

_real_json = ld.json
ld.json = _SlowJson(_real_json)
_errs = []


def _writer(code):
    try:
        ld.merge_accounts(_fp, [{"code": code, "refresh": "r-" + code,
                                 "access": "a-" + code}])
    except Exception as e:                     # noqa: BLE001
        _errs.append(f"{code}: {e}")


_ts = [threading.Thread(target=_writer, args=(c,)) for c in ("AAA111", "BBB222")]
for t in _ts:
    t.start()
for t in _ts:
    t.join(30)
ld.json = _real_json

ck("동시 병합에 예외 없음", not _errs, str(_errs))
_parsed = None
try:
    with open(_fp, encoding="utf-8") as f:
        _parsed = json.load(f)
except Exception as e:                         # noqa: BLE001
    _parsed = None
    ck("승격된 파일이 파싱됨", False, str(e))
else:
    ck("승격된 파일이 파싱됨", True)
_codes = {a.get("code") for a in (_parsed or [])}
ck("두 writer 의 계정이 모두 남음", _codes == {"AAA111", "BBB222"}, str(_codes))
ck("토큰이 짝을 잃지 않음",
   all(a.get("access") == "a-" + a["code"] and a.get("refresh") == "r-" + a["code"]
       for a in (_parsed or [])), str(_parsed))
_IGNORE = ("accounts.json", "accounts.json.lock")   # .lock 은 병합락 사이드카
_left = [n for n in os.listdir(_d) if n not in _IGNORE]
ck("임시파일이 남지 않음", _left == [], str(_left))
ck("고정 임시경로(accounts.json.tmp)를 쓰지 않음",
   "accounts.json.tmp" not in json.dumps(sorted(os.listdir(_d))))

# 쓰기 실패 시 원본은 그대로 — 반쯤 쓴 파일을 승격하지 않는다.
_before = open(_fp, encoding="utf-8").read()


class _BoomJson(_SlowJson):
    def dump(self, obj, fp, **kw):
        raise RuntimeError("disk full")


ld.json = _BoomJson(_real_json)
try:
    ld.merge_accounts(_fp, [{"code": "CCC333", "refresh": "r", "access": "a"}])
    _raised = False
except Exception:                              # noqa: BLE001
    _raised = True
ld.json = _real_json
ck("쓰기 실패는 삼키지 않음", _raised)
ck("쓰기 실패 후 원본 보존", open(_fp, encoding="utf-8").read() == _before)
_left2 = [n for n in os.listdir(_d) if n not in _IGNORE]
ck("쓰기 실패 후 임시파일 청소", _left2 == [], str(_left2))
shutil.rmtree(_d, ignore_errors=True)


print("=== B. harvest_all 직렬화 ===")
_active = []
_peak = []
_real_inner = ld._harvest_all_locked


def _fake_inner(*a, **k):
    _active.append(1)
    _peak.append(len(_active))
    time.sleep(0.05)
    _active.pop()
    return (0, 0, 0, 0)


ld._harvest_all_locked = _fake_inner
_hts = [threading.Thread(target=lambda: ld.harvest_all("./nope.json"))
        for _ in range(4)]
_t0 = time.time()
for t in _hts:
    t.start()
for t in _hts:
    t.join(30)
_elapsed = time.time() - _t0
ld._harvest_all_locked = _real_inner
ck("동시 수확이 겹치지 않음", _peak and max(_peak) == 1, str(_peak))
ck("네 번 다 실행됨", len(_peak) == 4, str(_peak))
ck("직렬화된 만큼 시간이 듦(병렬 아님)", _elapsed >= 0.15, f"{_elapsed:.3f}s")
ck("락이 모듈 전역(프로세스 공용)",
   isinstance(ld._HARVEST_LOCK, type(threading.Lock()))
   and isinstance(ld._MERGE_LOCK, type(threading.Lock())))


print("=== C. 스윕 token_provider 는 수확하지 않는다 ===")
_harv = []
_real_harvest = ld.harvest_all
ld.harvest_all = lambda *a, **k: (_harv.append((a, k)), (0, 0, 0, 0))[1]

_d2 = tempfile.mkdtemp(prefix="harvsafe2_")
_fp2 = os.path.join(_d2, "accounts.json")
_tok_a = m.__dict__.get("_x")  # placeholder to keep names tidy


def _jwt(exp):
    import base64 as _b64
    body = _b64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return "h." + body + ".s"


_now = int(time.time())
with open(_fp2, "w", encoding="utf-8") as f:
    json.dump([{"code": "c1", "access": _jwt(_now + 600), "refresh": "r1"},
               {"code": "c2", "access": _jwt(_now + 9000), "refresh": "r2"}], f)

_best = m.read_token_quiet(_fp2)
ck("read_token_quiet 가 수확을 부르지 않음", _harv == [], str(_harv))
ck("read_token_quiet 가 가장 늦게 만료되는 access 반환",
   _best == _jwt(_now + 9000), str(_best)[:40])
ck("read_token_quiet 소스에 harvest_all 없음",
   "harvest_all" not in m.read_token_quiet.__code__.co_names,
   str(m.read_token_quiet.__code__.co_names))
ck("파일이 없어도 조용히 None", m.read_token_quiet(os.path.join(_d2, "nope.json")) is None)

# 수확 소유자(harvest_token_quiet)는 여전히 수확한다 — 소유권을 옮겼을 뿐 없앤 게 아니다.
_harv.clear()
ck("harvest_token_quiet 는 수확 유지", m.harvest_token_quiet(_fp2) == _jwt(_now + 9000)
   and len(_harv) == 1, str(_harv))
ld.harvest_all = _real_harvest
shutil.rmtree(_d2, ignore_errors=True)

_hl = m._run_headless.__code__
_hl_names = set(_hl.co_names)
for _c in _hl.co_consts:
    if hasattr(_c, "co_names"):
        _hl_names |= set(_c.co_names)
ck("헤드리스 스윕 provider = read_token_quiet", "read_token_quiet" in _hl_names)
ck("헤드리스 스윕 provider 가 harvest_token_quiet 아님",
   "harvest_token_quiet" not in _hl_names, str(sorted(_hl_names))[:200])
ck("헤드리스 폴링 루프가 수확 소유자로 남음", "harvest_all" in _hl_names)
_cfg_ro = m.headless_sweep_cfg({}, [], {}, token_provider=m.read_token_quiet)
ck("읽기전용 provider 여도 stabilize 유지", _cfg_ro["stabilize"] is True)
ck("--no-harvest 는 provider 없음(기존 동작)",
   m.headless_sweep_cfg({}, [], {})["token_provider"] is None)

print("--- GUI 스윕도 같은 대접: provider 는 읽기만, 수확은 _HarvestThread ---")
_base_names = set(m.MainWindow._auto_cfg_base.__code__.co_names)
ck("GUI 스윕 provider = _read_token_quiet", "_read_token_quiet" in _base_names)
ck("GUI 스윕 provider 가 _harvest_token_quiet 아님",
   "_harvest_token_quiet" not in _base_names, str(sorted(_base_names))[:200])
ck("GUI _read_token_quiet 는 공용 읽기함수 사용",
   "read_token_quiet" in m.MainWindow._read_token_quiet.__code__.co_names)
_rtq_calls = []
_real_rtq = m.read_token_quiet
m.read_token_quiet = lambda p="./accounts.json": _rtq_calls.append(p) or "tok"
_harv.clear()
ld.harvest_all = lambda *a, **k: (_harv.append((a, k)), (0, 0, 0, 0))[1]
_got = m.MainWindow._read_token_quiet(object())
ld.harvest_all = _real_harvest
m.read_token_quiet = _real_rtq
ck("GUI provider 가 수확을 부르지 않음", _harv == [], str(_harv))
ck("GUI provider 가 accounts.json 을 읽음",
   _got == "tok" and _rtq_calls == ["./accounts.json"], str(_rtq_calls))

# GUI 의 수확 소유자는 _HarvestThread 다 — 없애지 않았음을 못박는다.
import inspect as _insp
ck("_HarvestThread 가 __init__ 에서 기동",
   "_HarvestThread" in m.MainWindow.__init__.__code__.co_names)
ck("_HarvestThread 가 harvest_all 소유",
   "harvest_all" in m._HarvestThread.run.__code__.co_names)
_ht_sig = _insp.signature(m._HarvestThread.__init__).parameters
# 주기의 소유자는 ld_autoharvest 다. 예전에는 GUI·헤드리스가 각자 1200 을 적어
# 두고 "둘이 같은가"만 봤는데, 그 숫자는 토큰 신선도 임계와 부등식으로 묶여 있어
# 한쪽만 바뀌면 토큰이 틱 사이에 죽는다(실서버 4계정 만료). 이제는 양쪽이 같은
# 함수를 거치는지를 잠근다 — 값이 아니라 출처를 고정한다.
import ld_autoharvest as _LA
ck("_HarvestThread 주기 기본값은 위임(None)",
   _ht_sig["interval"].default is None
   and _ht_sig["accounts"].default == "./accounts.json", str(_ht_sig))
ck("_HarvestThread 가 harvest_interval() 로 주기를 받는다",
   "harvest_interval" in m._HarvestThread.__init__.__code__.co_names)
ck("harvest_interval() = ld_autoharvest.HARVEST_INTERVAL",
   m.harvest_interval() == _LA.HARVEST_INTERVAL,
   f"{m.harvest_interval()} vs {_LA.HARVEST_INTERVAL}")
ck("GUI __init__ 에 리터럴 주기가 없다",
   1200 not in m.MainWindow.__init__.__code__.co_consts,
   str([c for c in m.MainWindow.__init__.__code__.co_consts if isinstance(c, int)]))
ck("_alert_api(사용자 조작 경로)는 수확 유지",
   "_harvest_token_quiet" in m.MainWindow._alert_api.__code__.co_names)


print("=== D. GUI 폴링 틱 씨딩 — 수확·GUI스레드 네트워크 금지 ===")


class _Router:
    def __init__(self):
        self.seeded = []
        self.rebalanced = []

    def routes(self):
        return [{"keyword": k} for k in (self.seeded[0] if self.seeded else [])]

    def seed_from_server(self, kws):
        self.seeded.append(list(kws))
        return len(kws)

    def rebalance(self, core_only=False, log=None):
        self.rebalanced.append(core_only)
        return []


class _Tick:
    """MainWindow 없이 _auto_poll_tick 만 돌리는 최소 self."""

    def __init__(self):
        self._supervisor = None
        self._alert_worker = None
        self._router = _Router()
        self.calls = []
        self.jobs = []
        _self = self
        self.alertLog = types.SimpleNamespace(
            append=lambda s: _self.calls.append(("log", s)))
        # 운영 로그는 이제 _alog 중앙 헬퍼를 거친다(화면 + karrot_monitor.log).
        # 페이크도 같은 이름을 가져야 _auto_poll_tick 이 그대로 돈다.
        self._alog = lambda s: _self.calls.append(("log", s))

    def _resync_search_sweep(self):
        self.calls.append(("resync", threading.get_ident()))

    def _core_only(self):
        return False

    def _alert_run(self, fn, on_done=None):
        self.jobs.append((fn, on_done))

    def _quiet_keyword_list(self, core_only=False):
        self.calls.append(("list", threading.get_ident()))
        return {"user_keywords": [{"keyword": "샤넬"}]}

    def _safe_alert_list(self, log):
        raise AssertionError("씨딩이 수확 경로(_safe_alert_list)를 탔다")

    def _alert_fleet(self):
        self.calls.append(("fleet", threading.get_ident()))
        return types.SimpleNamespace(
            poll_all=lambda log=None, core_only=False: ["match"])

    def _match_populate(self, data):
        pass


_harv2 = []
ld.harvest_all = lambda *a, **k: (_harv2.append(1), (0, 0, 0, 0))[1]
_tk = _Tick()
_gui_tid = threading.get_ident()
m.MainWindow._auto_poll_tick(_tk)
ck("틱이 GUI 스레드서 목록 조회를 하지 않음",
   not [c for c in _tk.calls if c[0] == "list"], str(_tk.calls))
ck("틱이 GUI 스레드서 승격(등록)을 하지 않음", _tk._router.rebalanced == [])
ck("틱이 폴링 잡을 워커로 넘김", len(_tk.jobs) == 1, str(_tk.jobs))
ck("재동기화만 GUI 스레드에 남음",
   [c[0] for c in _tk.calls] == ["resync"], str(_tk.calls))

_res = {}
_logs = []


def _run_job():
    _res["tid"] = threading.get_ident()
    _res["out"] = _tk.jobs[0][0](_logs.append)


_th = threading.Thread(target=_run_job)
_th.start()
_th.join(30)
ck("잡이 GUI 스레드가 아닌 곳에서 돎", _res.get("tid") not in (None, _gui_tid))
_list_calls = [c for c in _tk.calls if c[0] == "list"]
ck("씨딩이 잡 안에서 일어남", len(_list_calls) == 1, str(_tk.calls))
ck("씨딩이 워커 스레드에서 일어남", _list_calls and _list_calls[0][1] == _res.get("tid"))
ck("씨딩이 함대 수확을 부르지 않음", _harv2 == [], str(_harv2))
ck("서버 키워드가 라우터에 인정됨", _tk._router.seeded == [["샤넬"]], str(_tk._router.seeded))
ck("승격은 씨딩 뒤에 워커에서", _tk._router.rebalanced == [False])
ck("잡이 폴링 결과 반환", _res.get("out") == ["match"], str(_res.get("out")))
ck("잡 로그는 GUI 위젯이 아니라 log 콜백으로", not [c for c in _tk.calls if c[0] == "log"],
   str(_tk.calls))

# 이전 폴링이 진행 중이면 틱은 잡을 새로 띄우지 않는다(라우터 동시 변경 방지).
_tk2 = _Tick()
_tk2._alert_worker = types.SimpleNamespace(isRunning=lambda: True)
m.MainWindow._auto_poll_tick(_tk2)
ck("진행 중이면 잡을 새로 안 띄움", _tk2.jobs == [], str(_tk2.jobs))
ck("스킵 로그", any("이번 틱 스킵" in c[1] for c in _tk2.calls if c[0] == "log"),
   str(_tk2.calls))
ld.harvest_all = _real_harvest

print("--- _quiet_keyword_list 자체가 수확하지 않는다 ---")
import daangn_ext.keyword_alert_api as _kapi
_real_api = _kapi.KeywordAlertAPI
_api_made = []
_closed = []


class _FakeAPI:
    def __init__(self, access, config_path=None, proxy=None):
        _api_made.append((access, config_path, proxy))

    def list(self):
        return {"user_keywords": [{"keyword": "구찌"}]}

    def close(self):
        _closed.append(1)


class _QL:
    def __init__(self, valid):
        self._valid_rows = valid
        self.multi_args = []

    def _multi(self, *a, **k):
        self.multi_args.append((a, k))
        return types.SimpleNamespace(_valid=lambda core_only=False: self._valid_rows)


_kapi.KeywordAlertAPI = _FakeAPI
try:
    _q = _QL([("c1", "tok1", "http://p")])
    _out = m.MainWindow._quiet_keyword_list(_q, False)
    ck("_quiet_keyword_list 가 서버 목록 반환",
       _out == {"user_keywords": [{"keyword": "구찌"}]}, str(_out))
    ck("수확 없는 _multi() 호출", _q.multi_args == [((), {})], str(_q.multi_args))
    ck("첫 유효계정 토큰·프록시 사용",
       _api_made == [("tok1", "./data/config.json", "http://p")], str(_api_made))
    ck("api 를 닫음", _closed == [1])
    _q2 = _QL([])
    ck("유효계정 없으면 조회 없이 {}",
       m.MainWindow._quiet_keyword_list(_q2, False) == {} and len(_api_made) == 1)
finally:
    _kapi.KeywordAlertAPI = _real_api

_names = set(m.MainWindow._quiet_keyword_list.__code__.co_names)
ck("_quiet_keyword_list 가 _alert_api(수확경로)를 안 씀", "_alert_api" not in _names, str(_names))
ck("_quiet_keyword_list 가 harvest 를 안 씀",
   not [n for n in _names if "harvest" in n], str(_names))

print("=== E. 프로세스 간 병합락 (accounts.json.lock) ===")
_HERE = os.path.dirname(os.path.abspath(__file__))
_pd = tempfile.mkdtemp(prefix="harvsafe_proc_")

# 자식 1: 느린 읽기-병합-쓰기. go 파일이 생길 때까지 기다렸다 동시에 들어간다.
_MERGER = r'''
import sys, os, json, time
sys.path.insert(0, %r)
import ld_autoharvest as ld
fp, code, ready, go, rd = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], float(sys.argv[5])


class SlowJson:
    def __init__(self, real, rd):
        self._r, self._rd = real, rd

    def load(self, *a, **k):
        time.sleep(self._rd)                  # 읽기-쓰기 창을 벌린다
        return self._r.load(*a, **k)

    def dumps(self, *a, **k):
        return self._r.dumps(*a, **k)

    def dump(self, obj, f, **kw):
        s = self._r.dumps(obj, **kw)
        for i in range(0, len(s), 16):
            f.write(s[i:i + 16])
            time.sleep(0.002)


ld.json = SlowJson(ld.json, rd)
open(ready, "w").close()
while not os.path.exists(go):
    time.sleep(0.01)
ld.merge_accounts(fp, [{"code": code, "refresh": "r-" + code, "access": "a-" + code}])
''' % (_HERE,)

# 자식 2: 락을 잡고 지정 시간 동안 쥐고 있는다(경합·타임아웃·죽음 테스트용).
_HOLDER = r'''
import sys, os, time
sys.path.insert(0, %r)
import ld_autoharvest as ld
fp, ready, hold = sys.argv[1], sys.argv[2], float(sys.argv[3])
with ld._file_lock(fp, timeout=10) as got:
    with open(ready, "w") as f:
        f.write("1" if got else "0")
    time.sleep(hold)
''' % (_HERE,)

_merger_py = os.path.join(_pd, "merger.py")
_holder_py = os.path.join(_pd, "holder.py")
open(_merger_py, "w").write(_MERGER)
open(_holder_py, "w").write(_HOLDER)

ck("이 플랫폼에 파일락 수단이 있음(테스트가 실효)",
   ld._fcntl is not None or ld._msvcrt is not None)

# ── E1. 프로세스 두 개가 겹쳐 병합해도 lost update 없음 ──
_pfp = os.path.join(_pd, "accounts.json")
with open(_pfp, "w", encoding="utf-8") as f:
    json.dump([], f)
_go = os.path.join(_pd, "GO")
_procs = []
for _c in ("PA1111", "PB2222"):
    _procs.append(subprocess.Popen(
        [sys.executable, _merger_py, _pfp, _c,
         os.path.join(_pd, _c + ".ready"), _go, "0.4"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
_t_ready = time.time()
while (time.time() - _t_ready < 60
       and not all(os.path.exists(os.path.join(_pd, c + ".ready"))
                   for c in ("PA1111", "PB2222"))):
    time.sleep(0.02)
ck("두 프로세스가 준비됨",
   all(os.path.exists(os.path.join(_pd, c + ".ready"))
       for c in ("PA1111", "PB2222")))
open(_go, "w").close()                      # 동시에 출발
_outs = [p.communicate(timeout=120) for p in _procs]
ck("두 프로세스 모두 정상 종료",
   all(p.returncode == 0 for p in _procs),
   str([(p.returncode, o[1][-200:]) for p, o in zip(_procs, _outs)]))
_pp = None
try:
    with open(_pfp, encoding="utf-8") as f:
        _pp = json.load(f)
    ck("프로세스 경합 후에도 파일이 파싱됨", True)
except Exception as e:                         # noqa: BLE001
    ck("프로세스 경합 후에도 파일이 파싱됨", False, str(e))
_pcodes = {a.get("code") for a in (_pp or [])}
ck("프로세스 간 lost update 없음(두 수확분 모두 남음)",
   _pcodes == {"PA1111", "PB2222"}, str(_pcodes))
ck("프로세스 경합 후 토큰 짝 유지",
   all(a.get("access") == "a-" + a["code"] for a in (_pp or [])), str(_pp))
ck("사이드카가 대상 파일이 아니라 별도 파일",
   os.path.exists(ld.lock_path(_pfp)) and ld.lock_path(_pfp) != _pfp)

# ── E2. 다른 프로세스가 쥐면 실제로 못 잡는다 ──
_hfp = os.path.join(_pd, "hold.json")
with open(_hfp, "w", encoding="utf-8") as f:
    json.dump([], f)
_hready = os.path.join(_pd, "hold.ready")
_holder = subprocess.Popen([sys.executable, _holder_py, _hfp, _hready, "6"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
_t0h = time.time()
while time.time() - _t0h < 60 and not os.path.exists(_hready):
    time.sleep(0.02)
_held = os.path.exists(_hready) and open(_hready).read().strip() == "1"
ck("홀더 프로세스가 락을 잡음", _held)

_fd = os.open(ld.lock_path(_hfp), os.O_RDWR | os.O_CREAT, 0o600)
_mine = ld._try_lock(_fd)
if _mine:
    ld._unlock(_fd)
os.close(_fd)
ck("남이 쥔 락은 못 잡는다(진짜 OS 락)", _mine is False)

# ── E3. 상한을 넘겨도 멎지 않는다 — 크게 남기고 진행 ──
_lg = []
_t0 = time.time()
_ran = []
with ld._file_lock(_hfp, timeout=0.3, log=_lg.append) as _got:
    _ran.append(_got)
_el = time.time() - _t0
ck("대기 상한에서 예외 없이 빠져나옴", _ran == [False], str(_ran))
ck("상한만큼만 기다린다(무한 대기 아님)", 0.25 <= _el < 3.0, f"{_el:.3f}s")
ck("상한 초과를 크게 남긴다",
   any("대기 초과" in x and "락 없이 진행" in x for x in _lg), str(_lg))
ck("상한 기본값 20초", ld.LOCK_TIMEOUT == 20.0, str(ld.LOCK_TIMEOUT))

# ── E4. 스테일 락 정책: 프로세스가 죽으면 커널이 놓는다 ──
_holder.kill()          # SIGKILL(윈도우는 TerminateProcess) — 정리 코드 없이 즉사
_holder.wait(timeout=30)
_t0k = time.time()
_reacq = False
while time.time() - _t0k < 10:
    _fd2 = os.open(ld.lock_path(_hfp), os.O_RDWR | os.O_CREAT, 0o600)
    _reacq = ld._try_lock(_fd2)
    if _reacq:
        ld._unlock(_fd2)
    os.close(_fd2)
    if _reacq:
        break
    time.sleep(0.05)
ck("홀더가 죽으면 락이 풀린다(영구 스테일 없음)", _reacq)

shutil.rmtree(_pd, ignore_errors=True)

passed = sum(1 for x in R if x)
print(f"===== {passed}/{len(R)} PASS =====")
sys.exit(0 if passed == len(R) else 1)

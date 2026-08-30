"""수확 소유권 · accounts.json 동시쓰기 안전성.

accounts.json 은 이 기계에서 재발급할 수 없는 세션 토큰의 유일한 사본이다.
이 스위트가 지키는 것:
  A. merge_accounts 동시호출이 깨진 파일을 승격하지 못한다(고유 임시파일 + 직렬화).
  B. harvest_all 이 프로세스 안에서 직렬화된다.
  C. 스윕의 token_provider 가 함대 수확을 트리거하지 않는다.
  D. GUI 폴링 틱의 씨딩이 수확도, GUI 스레드 네트워크 호출도 하지 않는다.
"""
import os
import sys
import json
import time
import types
import shutil
import tempfile
import threading

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
_left = [n for n in os.listdir(_d) if n != "accounts.json"]
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
_left2 = [n for n in os.listdir(_d) if n != "accounts.json"]
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

passed = sum(1 for x in R if x)
print(f"===== {passed}/{len(R)} PASS =====")
sys.exit(0 if passed == len(R) else 1)

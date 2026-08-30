"""스윕 엔진 분리 테스트 — 엔진이 Qt 없이 도는지 (네트워크 불필요).

    python sweep_engine_test.py

핵심: daangn.auto_monitor 를 import 하고 SweepEngine 을 만드는 것만으로는
Qt 가 절대 딸려오면 안 된다(헤드리스 서버 런타임에는 이벤트 루프가 없다).
실제 스윕은 돌리지 않는다 — 외부 API 를 때린다.
"""
import os
import sys
import json
import subprocess
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


def _cfg(**kw):
    c = {"db_path": tempfile.mktemp(suffix=".db"), "out_json": "./OUT.json",
         "scope": "regions", "regions": []}
    c.update(kw)
    return c


print("=== A. 서브프로세스: import + 엔진 생성에 Qt 가 없다 ===")

PROBE = r"""
import sys, json, tempfile
sys.path.insert(0, %r)
import daangn.auto_monitor as am
after_import = [m for m in sys.modules if m.startswith("PyQt6")]
logs, founds, stats = [], [], []
e = am.SweepEngine(
    {"db_path": tempfile.mktemp(suffix=".db"), "out_json": "./OUT.json",
     "scope": "regions", "regions": []},
    on_log=logs.append, on_found=founds.append, on_status=stats.append)
e._log("x"); e._status("y")
e.stop()
after_engine = [m for m in sys.modules if m.startswith("PyQt6")]
print("RESULT" + json.dumps({
    "after_import": after_import,
    "after_engine": after_engine,
    "logs": logs, "stats": stats,
    "stopped": e._stop,
    "has_engine_cls": hasattr(am, "SweepEngine"),
}))
""" % os.path.dirname(os.path.abspath(__file__))

pr = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True)
ck("서브프로세스 정상 종료", pr.returncode == 0, (pr.stderr or "")[-300:])
data = {}
for line in (pr.stdout or "").splitlines():
    if line.startswith("RESULT"):
        data = json.loads(line[len("RESULT"):])
ck("RESULT 파싱", bool(data), (pr.stdout or "")[-200:])
ck("import 직후 sys.modules 에 PyQt6 없음",
   data.get("after_import") == [], str(data.get("after_import")))
ck("SweepEngine 생성 후에도 PyQt6 없음",
   data.get("after_engine") == [], str(data.get("after_engine")))
ck("엔진 클래스 존재", data.get("has_engine_cls") is True)
ck("콜백이 서브프로세스에서도 동작", data.get("logs") == ["x"] and data.get("stats") == ["y"],
   str(data.get("logs")))
ck("stop() 이 플래그를 세움", data.get("stopped") is True)

print("\n=== B. 어댑터를 꺼내면 그때 Qt 가 들어온다 ===")

PROBE2 = r"""
import sys, json
sys.path.insert(0, %r)
import daangn.auto_monitor as am
before = [m for m in sys.modules if m.startswith("PyQt6")]
A = am.AutoMonitor
after = [m for m in sys.modules if m.startswith("PyQt6")]
print("RESULT" + json.dumps({
    "before": before, "after": bool(after),
    "same": am.AutoMonitor is A,
    "sig": sorted(n for n in ("log", "found", "status") if hasattr(A, n)),
    "methods": sorted(n for n in ("run", "stop") if n in A.__dict__),
    "has_regions_in_dict": "_regions" in A.__dict__,
}))
""" % os.path.dirname(os.path.abspath(__file__))

pr2 = subprocess.run([sys.executable, "-c", PROBE2], capture_output=True, text=True)
d2 = {}
for line in (pr2.stdout or "").splitlines():
    if line.startswith("RESULT"):
        d2 = json.loads(line[len("RESULT"):])
ck("어댑터 서브프로세스 정상", pr2.returncode == 0 and bool(d2), (pr2.stderr or "")[-300:])
ck("어댑터 접근 전에는 Qt 없음", d2.get("before") == [], str(d2.get("before")))
ck("어댑터 접근하면 Qt 로드됨", d2.get("after") is True)
ck("두 번째 접근도 같은 클래스", d2.get("same") is True)
ck("시그널 3종 유지", d2.get("sig") == ["found", "log", "status"], str(d2.get("sig")))
ck("run/stop 을 어댑터가 직접 정의", d2.get("methods") == ["run", "stop"], str(d2.get("methods")))
ck("_regions 언바운드 접근 유지(robust_test)", d2.get("has_regions_in_dict") is True)

print("\n=== C. 콜백이 예전 시그널이 emit 하던 것을 그대로 받는다 ===")

import daangn.auto_monitor as am

logs, founds, stats = [], [], []
eng = am.SweepEngine(_cfg(tg_token=None, tg_chat=None),
                     on_log=logs.append, on_found=founds.append, on_status=stats.append)
ck("SweepEngine 이 순수 클래스", not hasattr(am.SweepEngine, "__bases__") or
   am.SweepEngine.__bases__ == (object,), str(am.SweepEngine.__bases__))

art = {"id": "A1", "title": "샤넬백", "href": "https://x/1", "thumbnail": "t.jpg",
       "content": "설명", "boostedAt": "2026-08-26T00:00:00"}
eng.notify("강남구", art, 1000000)
ck("notify → on_log 문자열", len(logs) == 1 and "강남구" in logs[0] and "🆕 신규" in logs[0],
   logs[:1])
ck("notify → on_found dict 1건", len(founds) == 1 and isinstance(founds[0], dict))
f = founds[0] if founds else {}
ck("found 에 id 필드 유지", f.get("id") == "A1", str(f))
ck("found 페이로드 키 유지",
   set(f) == {"id", "region", "title", "price", "url", "image", "desc",
              "boostedAt", "status"}, str(sorted(f)))
ck("found 내용", (f.get("region"), f.get("title"), f.get("price"), f.get("url"),
                 f.get("image"), f.get("desc"), f.get("status"))
   == ("강남구", "샤넬백", 1000000, "https://x/1", "t.jpg", "설명", "신규"), str(f))

eng.notify("서초구", art, 800000, changed=1000000)
ck("가격변동 status", founds[-1].get("status") == "가격변동", str(founds[-1].get("status")))
ck("가격변동 로그 문구", "💱 가격변동" in logs[-1], logs[-1][:30])

# _dedup_notify: seen DB 동작 + 콜백 경유
logs.clear(); founds.clear()
eng2 = am.SweepEngine(_cfg(), on_log=logs.append, on_found=founds.append)
arts = [{"id": f"N{i}", "title": f"샤넬{i}", "price": "1000000", "href": f"u{i}",
         "boostedAt": "2026-08-26T00:00:00", "content": ""} for i in range(3)]
new, chg = eng2._dedup_notify(arts, "강남구", None, None, None)
ck("_dedup_notify 신규 판정", (new, chg) == (3, 0), f"신규{new} 변동{chg}")
ck("신규가 on_found 로 나감", len(founds) == 3 and founds[0]["id"] == "N0")
new2, chg2 = eng2._dedup_notify(arts, "강남구", None, None, None)
ck("두 번째는 중복(auto_seen.db)", (new2, chg2) == (0, 0), f"신규{new2} 변동{chg2}")
arts[0]["price"] = "800000"
new3, chg3 = eng2._dedup_notify(arts, "강남구", None, None, None)
ck("가격변동만 재알림", (new3, chg3) == (0, 1), f"신규{new3} 변동{chg3}")
ck("변동 페이로드에 id 유지", founds[-1]["id"] == "N0" and founds[-1]["price"] == 800000,
   str(founds[-1]))

# 상태 콜백
stats.clear()
eng._status("사이클 1 · [0/10] 수집 중…")
ck("on_status 문자열 전달", stats == ["사이클 1 · [0/10] 수집 중…"], str(stats))

print("\n=== D. 콜백 기본값은 no-op — 안 주면 조용히 무시 ===")

silent = am.SweepEngine(_cfg())
try:
    silent._log("아무도 안 듣는다")
    silent._status("상태")
    silent._found({"id": "X"})
    silent.notify("강남구", art, 123)
    n, c = silent._dedup_notify(arts, "강남구", None, None, None)
    ck("콜백 없이도 무크래시", True, f"신규{n} 변동{c}")
except Exception as e:
    ck("콜백 없이도 무크래시", False, f"{type(e).__name__}: {e}")
ck("기본 콜백은 no-op 함수", silent.on_log is am._noop and silent.on_found is am._noop
   and silent.on_status is am._noop)

print("\n=== E. stop() 이 루프가 보는 플래그를 세운다 ===")

eng3 = am.SweepEngine(_cfg())
ck("초기 _stop False", eng3._stop is False)
eng3.stop()
ck("stop() 후 _stop True", eng3._stop is True)

# _rest 는 _stop 이면 즉시 깨어난다(종료 지연 방지)
import time as _t
t0 = _t.monotonic()
eng3._rest(30, 60)
ck("_stop 이면 휴식이 즉시 깸", _t.monotonic() - t0 < 1.0,
   f"{_t.monotonic() - t0:.2f}s")

eng4 = am.SweepEngine(_cfg())
t0 = _t.monotonic()
eng4._rest(0.4, 0.4)
ck("_stop 아니면 정상 대기", 0.3 <= _t.monotonic() - t0 < 2.0,
   f"{_t.monotonic() - t0:.2f}s")

# should_stop 배선 — 텔레그램 송신기가 엔진 플래그를 본다
eng5 = am.SweepEngine(_cfg(tg_token="1:X", tg_chat="9"))
ck("TelegramSender should_stop 초기 False", eng5._tg.should_stop() is False)
eng5.stop()
ck("stop() 이 송신기까지 전파", eng5._tg.should_stop() is True)

print("\n=== F. 어댑터가 엔진을 물고 있다 (Qt 로드됨) ===")

AM = am.AutoMonitor
mon = AM(None, _cfg(tg_token="1:X", tg_chat="9"))
ck("어댑터가 SweepEngine 보유", isinstance(mon.engine, am.SweepEngine))
sig_logs, sig_founds, sig_stats = [], [], []
mon.log.connect(sig_logs.append)
mon.found.connect(sig_founds.append)
mon.status.connect(sig_stats.append)
mon.engine._log("엔진 로그")
mon.engine._status("엔진 상태")
mon.engine._found({"id": "Z"})
ck("엔진 on_log → log 시그널", sig_logs == ["엔진 로그"], str(sig_logs))
ck("엔진 on_status → status 시그널", sig_stats == ["엔진 상태"], str(sig_stats))
ck("엔진 on_found → found 시그널", sig_founds == [{"id": "Z"}], str(sig_founds))
ck("어댑터 stop() 전 _stop False", mon._stop is False)
mon.stop()
ck("어댑터 stop() → 엔진 정지", mon.engine._stop is True and mon._stop is True)
ck("어댑터 __getattr__ 위임(_tg)", mon._tg is mon.engine._tg)
ck("어댑터 __getattr__ 위임(_dedup_notify)",
   mon._dedup_notify.__func__ is am.SweepEngine._dedup_notify)
called = []
mon.engine.run = lambda: called.append(1)
mon.run()
ck("어댑터 run() 이 엔진 run 을 부른다", called == [1], str(called))

# _regions 언바운드 사용(robust_test 경로)
_dummy = type("D", (), {"cfg": {"scope": "regions", "regions": ["강남구-381"]}})()
ck("_regions 언바운드 호출", AM.__dict__["_regions"](_dummy) == ["강남구-381"],
   str(AM.__dict__["_regions"](_dummy)))
ck("엔진 _regions 동일 동작",
   am.SweepEngine._regions(_dummy) == ["강남구-381"])

print("\n=== G. 모듈 표면 유지 ===")
ck("load_conditions_from_excel 유지", callable(am.load_conditions_from_excel))
ck("상수 유지", (am.CYCLE_REST_MIN, am.CYCLE_REST_MAX, am.REGION_GAP_MIN,
                am.REGION_GAP_MAX, am.MIN_IP_PER_LANE, am.MAX_LANES)
   == (10.0, 3600.0, 0.3, 10.0, 3, 16))
try:
    am.없는이름
    ck("없는 속성은 AttributeError", False, "예외 없음")
except AttributeError:
    ck("없는 속성은 AttributeError", True)

# 소스에 시그널 emit 잔재가 없어야 한다(엔진 로직 안)
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "daangn", "auto_monitor.py"), encoding="utf-8").read()
head = src.split("def _build_auto_monitor", 1)[0]
ck("엔진 본문에 .emit( 없음", ".emit(" not in head,
   [l for l in head.splitlines() if ".emit(" in l][:1])
ck("모듈 최상단에 PyQt import 없음",
   "from PyQt6" not in src.split("def _build_auto_monitor", 1)[0])

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

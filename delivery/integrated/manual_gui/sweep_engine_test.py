"""스윕 엔진 분리 테스트 — 엔진이 Qt 없이 도는지 (네트워크 불필요).

    python sweep_engine_test.py

핵심: daangn.sweep_engine 을 import 하고 SweepEngine 을 굴리는 것만으로는
Qt 가 절대 딸려오면 안 된다(헤드리스 서버 런타임에는 이벤트 루프가 없다).
실제 스윕은 돌리지 않는다 — 외부 API 를 때린다.
"""
import os
import sys
import json
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


def _cfg(**kw):
    c = {"db_path": tempfile.mktemp(suffix=".db"), "out_json": "./OUT.json",
         "scope": "regions", "regions": []}
    c.update(kw)
    return c


def _probe(src):
    """별도 프로세스에서 돌리고 RESULT json 을 받아온다."""
    pr = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True)
    data = {}
    for line in (pr.stdout or "").splitlines():
        if line.startswith("RESULT"):
            data = json.loads(line[len("RESULT"):])
    return pr, data


print("=== A. 서브프로세스: 엔진을 굴려도 sys.modules 에 PyQt6 가 없다 ===")

PROBE = r"""
import sys, json, tempfile
sys.path.insert(0, %r)
import daangn.sweep_engine as se
after_import = [m for m in sys.modules if m.startswith("PyQt6")]
logs, founds, stats = [], [], []
e = se.SweepEngine(
    {"db_path": tempfile.mktemp(suffix=".db"), "out_json": "./OUT.json",
     "scope": "regions", "regions": []},
    on_log=logs.append, on_found=founds.append, on_status=stats.append)
e._log("x"); e._status("y")
e._dedup_notify([{"id": "A1", "title": "샤넬백", "price": "1000000", "href": "u",
                  "boostedAt": "2026-08-26T00:00:00", "content": ""}],
                "강남구", None, None, None)
e.stop()
after_run = [m for m in sys.modules if m.startswith("PyQt6")]
print("RESULT" + json.dumps({
    "after_import": after_import,
    "after_run": after_run,
    "qt_loaded": bool(after_run),
    "logs": logs, "stats": stats, "founds": founds,
    "stopped": e._stop,
}))
""" % HERE

pr, data = _probe(PROBE)
ck("서브프로세스 정상 종료", pr.returncode == 0, (pr.stderr or "")[-300:])
ck("RESULT 파싱", bool(data), (pr.stdout or "")[-200:])
ck("import 직후 PyQt6 없음", data.get("after_import") == [], str(data.get("after_import")))
ck("엔진을 굴린 뒤에도 PyQt6 없음 (qt_loaded False)",
   data.get("qt_loaded") is False, str(data.get("after_run")))
ck("콜백이 서브프로세스에서도 동작", data.get("logs")[:1] == ["x"] and data.get("stats") == ["y"],
   str(data.get("logs"))[:80])
ck("서브프로세스에서 알림 페이로드까지 나옴",
   len(data.get("founds") or []) == 1 and data["founds"][0]["id"] == "A1",
   str(data.get("founds"))[:120])
ck("stop() 이 플래그를 세움", data.get("stopped") is True)

print("\n=== B. 모듈 분리 형태 ===")

import daangn.sweep_engine as se
import daangn.auto_monitor as am

eng_src = open(os.path.join(HERE, "daangn", "sweep_engine.py"), encoding="utf-8").read()
ad_src = open(os.path.join(HERE, "daangn", "auto_monitor.py"), encoding="utf-8").read()

ck("엔진 모듈에 PyQt import 없음",
   "import PyQt" not in eng_src and "from PyQt" not in eng_src)
ck("엔진 모듈에 .emit( 없음", ".emit(" not in eng_src,
   [l for l in eng_src.splitlines() if ".emit(" in l][:1])
ck("엔진 모듈에 QThread 흔적 없음", "QThread" not in eng_src)
ck("어댑터는 최상단에서 평범하게 PyQt import",
   "from PyQt6.QtCore import QThread, pyqtSignal" in ad_src.split("class ", 1)[0])
ck("모듈 __getattr__ 꼼수 없음",
   "def __getattr__(name)" not in ad_src and "def __getattr__(name)" not in eng_src)
ck("어댑터는 엔진을 import", "from daangn.sweep_engine import SweepEngine" in ad_src)
ck("어댑터 파일은 얇다(80줄 이하)", len(ad_src.splitlines()) <= 80,
   f"{len(ad_src.splitlines())}줄")
ck("SweepEngine 은 엔진 모듈 소속", am.SweepEngine.__module__ == "daangn.sweep_engine")
ck("SweepEngine 은 순수 클래스", se.SweepEngine.__bases__ == (object,),
   str(se.SweepEngine.__bases__))
ck("상수는 엔진 모듈에", (se.CYCLE_REST_MIN, se.CYCLE_REST_MAX, se.REGION_GAP_MIN,
                     se.REGION_GAP_MAX, se.MIN_IP_PER_LANE, se.MAX_LANES)
   == (10.0, 3600.0, 0.3, 10.0, 3, 16))
ck("엑셀 로더는 엔진 모듈에", se.load_conditions_from_excel.__module__ == "daangn.sweep_engine")
ck("엑셀 로더 재수출 유지(full_test/gui_func_test)",
   am.load_conditions_from_excel is se.load_conditions_from_excel)

main_src = open(os.path.join(HERE, "main.py"), encoding="utf-8").read()
# 엑셀은 '엑셀로 조건 넣기' 한 곳으로 모았다(alert_rules). main.py 는 더 이상
# sweep_engine 의 로더를 부르지 않는다 — 어댑터 재수출은 다른 호출자를 위해 남는다.
ck("main.py 는 엑셀 로더를 alert_rules 에서 가져온다",
   "from daangn.sweep_engine import load_conditions_from_excel" not in main_src
   and "load_rules_from_excel" in main_src)
ck("main.py 는 AutoMonitor 를 어댑터에서 가져옴",
   "from daangn.auto_monitor import AutoMonitor" in main_src)

print("\n=== C. 콜백이 예전 시그널이 emit 하던 것을 그대로 받는다 ===")

logs, founds, stats = [], [], []
eng = se.SweepEngine(_cfg(), on_log=logs.append, on_found=founds.append,
                     on_status=stats.append)

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

logs.clear(); founds.clear()
eng2 = se.SweepEngine(_cfg(), on_log=logs.append, on_found=founds.append)
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

stats.clear()
eng._status("사이클 1 · [0/10] 수집 중…")
ck("on_status 문자열 전달", stats == ["사이클 1 · [0/10] 수집 중…"], str(stats))

print("\n=== D. 콜백 기본값은 no-op — 안 주면 조용히 무시 ===")

silent = se.SweepEngine(_cfg())
try:
    silent._log("아무도 안 듣는다")
    silent._status("상태")
    silent._found({"id": "X"})
    silent.notify("강남구", art, 123)
    n, c = silent._dedup_notify(arts, "강남구", None, None, None)
    ck("콜백 없이도 무크래시", True, f"신규{n} 변동{c}")
except Exception as e:
    ck("콜백 없이도 무크래시", False, f"{type(e).__name__}: {e}")
ck("기본 콜백은 no-op 함수", silent.on_log is se._noop and silent.on_found is se._noop
   and silent.on_status is se._noop)

print("\n=== E. stop() 이 루프가 보는 플래그를 세운다 ===")

eng3 = se.SweepEngine(_cfg())
ck("초기 _stop False", eng3._stop is False)
eng3.stop()
ck("stop() 후 _stop True", eng3._stop is True)

import time as _t
t0 = _t.monotonic()
eng3._rest(30, 60)
ck("_stop 이면 휴식이 즉시 깸", _t.monotonic() - t0 < 1.0, f"{_t.monotonic() - t0:.2f}s")

eng4 = se.SweepEngine(_cfg())
t0 = _t.monotonic()
eng4._rest(0.4, 0.4)
ck("_stop 아니면 정상 대기", 0.3 <= _t.monotonic() - t0 < 2.0,
   f"{_t.monotonic() - t0:.2f}s")

eng5 = se.SweepEngine(_cfg(tg_token="1:X", tg_chat="9"))
ck("TelegramSender should_stop 초기 False", eng5._tg.should_stop() is False)
eng5.stop()
ck("stop() 이 송신기까지 전파", eng5._tg.should_stop() is True)

print("\n=== F. 어댑터 (여기서부터 Qt 로드) ===")

AM = am.AutoMonitor
ck("어댑터는 QThread", any(b.__name__ == "QThread" for b in AM.__mro__))
mon = AM(None, _cfg(tg_token="1:X", tg_chat="9"))
ck("어댑터가 SweepEngine 보유", isinstance(mon.engine, se.SweepEngine))
ck("시그널 3종 유지", all(hasattr(AM, n) for n in ("log", "found", "status")))
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
called = []
mon.engine.run = lambda: called.append(1)
mon.run()
ck("어댑터 run() 이 엔진 run 을 부른다", called == [1], str(called))
mon.stop()
ck("어댑터 stop() → 엔진 정지", mon.engine._stop is True)

# ── 아래 3개는 기존 테스트가 실제로 쓰는 하위호환 표면이다(내 테스트 전용 아님) ──
# notify_test.py:379 `m._stop = True`
mon2 = AM(None, _cfg())
mon2._stop = True
ck("[notify_test] m._stop = True 가 엔진에 전달", mon2.engine._stop is True)
mon2._stop = False
ck("[notify_test] 되돌리기도 엔진에 전달", mon2.engine._stop is False)
# notify_test.py:353 `m._tg._post = ...`, full_test.py `m._dedup_notify/_proxy_cycle/_telegram`
ck("[notify_test] m._tg 가 엔진 것과 동일 객체", mon2._tg is mon2.engine._tg)
ck("[full_test] m._proxy_cycle 위임",
   mon2._proxy_cycle.__func__ is se.SweepEngine._proxy_cycle)
ck("[notify_test] m._flush_notify 위임",
   mon2._flush_notify.__func__ is se.SweepEngine._flush_notify)
# robust_test.py:188 `AutoMonitor.__dict__["_regions"](dummy)`
_dummy = type("D", (), {"cfg": {"scope": "regions", "regions": ["강남구-381"]}})()
ck("[robust_test] _regions 언바운드 호출", AM.__dict__["_regions"](_dummy) == ["강남구-381"],
   str(AM.__dict__["_regions"](_dummy)))
ck("엔진 _regions 도 동일 동작", se.SweepEngine._regions(_dummy) == ["강남구-381"])

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

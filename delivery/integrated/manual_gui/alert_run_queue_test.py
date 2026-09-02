"""사용자가 방금 시킨 작업이 조용히 버려지지 않는가.

클라 보고: "엑셀을 넣어도 반영이 안 된다."

실서버 로그(2026-09-02 00:14)가 보여준 것:
    [00:14:18] ── 작업 시작 ──                     ← 자동수확이 돌기 시작
    [00:14:34] [엑셀] 조건 3개 로드 — 라우터로 배정
    [00:14:44] [수확] 갱신 0 · 신규 0              ← 그 작업이 끝난 시각
엑셀 클릭이 다른 작업이 도는 창 안에 들어갔다. `_alert_run` 은 그때 아무것도
하지 않고 돌아가는데, 부르는 쪽은 반환값을 안 보고 "배정 중입니다"를 띄웠다.
사용자에게는 성공으로 보이고 실제로는 아무 일도 없었다. 그 뒤 표가 비어 있으니
'전체 삭제'를 눌렀고 등록 21건이 사라졌다.

무인 서버는 자동수확·자동폴링이 수시로 돈다. 사용자가 누른 순간이 그 창에
겹치는 건 예외가 아니라 일상이다. 그래서 거절이 아니라 **대기**가 맞다.

실행: python alert_run_queue_test.py
"""
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


try:
    from PyQt6 import QtCore, QtWidgets
except Exception as e:
    print(f"[SKIP] PyQt6 없음 ({type(e).__name__})")
    raise SystemExit(0)

import importlib.util

spec = importlib.util.spec_from_file_location("_m", "main.py")
m = importlib.util.module_from_spec(spec)
saved = sys.argv
sys.argv = ["main.py"]
try:
    spec.loader.exec_module(m)
except SystemExit:
    pass
finally:
    sys.argv = saved

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _FakeWorker(QtCore.QObject):
    """진짜 스레드를 띄우지 않는 대역. 언제 끝날지 테스트가 정한다."""
    done = QtCore.pyqtSignal(object)
    log = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, fn):
        super().__init__()
        self._fn = fn
        self._running = False
        self.started_count = 0

    def isRunning(self):
        return self._running

    def start(self):
        self._running = True
        self.started_count += 1

    def finish(self):
        """앞 작업이 끝난 순간을 흉내낸다."""
        self._running = False
        self.done.emit(self._fn(self.log.emit))
        self.finished.emit()


class _Fake:
    """_alert_run 만 돌리는 최소 self."""

    def __init__(self):
        self.logs = []
        self.alerts = []
        self.busy = []                   # 진행 표시가 켜지고 꺼진 자취
        self._alert_worker = None
        self._router = None

    def _alog(self, s):
        self.logs.append(s)

    def alert(self, s):
        self.alerts.append(s)

    def _alert_busy(self, text):
        self.busy.append(text)

    _alert_run = m.MainWindow._alert_run
    _alert_drain = m.MainWindow._alert_drain


def run_and_pump(f, fn, on_done=None, queue=False, label="처리 중"):
    started = f._alert_run(fn, on_done, queue=queue, label=label)
    app.processEvents()
    return started


print("=== 1. 한가하면 바로 시작한다 ===")
f = _Fake()
m._AlertWorker = _FakeWorker
ran = []
ok = run_and_pump(f, lambda log: ran.append("A") or "A")
ck("시작했다고 알린다", ok is True, repr(ok))
ck("워커를 띄웠다", f._alert_worker is not None and f._alert_worker.started_count == 1)

print("\n=== 2. 바쁠 때 queue=False 는 거절을 호출자에게 알린다 ===")
f = _Fake()
run_and_pump(f, lambda log: "A")
busy = f._alert_worker
ok = run_and_pump(f, lambda log: "B")
ck("False 를 돌려준다 (예전엔 None 이라 성공과 구분 불가)", ok is False, repr(ok))
ck("사용자에게 알린다", any("진행 중" in a for a in f.alerts), str(f.alerts))
ck("앞 작업을 밀어내지 않는다", f._alert_worker is busy)

print("\n=== 3. 바쁠 때 queue=True 는 버리지 않고 대기시킨다 (이번 버그) ===")
f = _Fake()
run_and_pump(f, lambda log: "A")
first = f._alert_worker
ran = []
ok = run_and_pump(f, lambda log: ran.append("EXCEL") or "EXCEL",
                  on_done=lambda r: ran.append(f"done={r}"), queue=True)
ck("버리지 않는다", ok is True, repr(ok))
ck("대기 중임을 로그에 남긴다", any("대기" in x for x in f.logs), str(f.logs))
ck("아직 실행 전이다", ran == [], str(ran))

print("\n=== 4. 앞 작업이 끝나면 대기 작업이 실제로 돈다 ===")
first.finish()                           # 앞 작업 종료 → 드레인
for _ in range(40):
    app.processEvents()
    if f._alert_worker is not first:
        break
    QtCore.QThread.msleep(10)
ck("대기 작업이 워커로 올라갔다", f._alert_worker is not first)
ck("대기 자리는 비었다", getattr(f, "_alert_pending", None) is None)
f._alert_worker.finish()                 # 그 작업이 실제로 도는 것까지
app.processEvents()
ck("엑셀 작업이 실행됐다", "EXCEL" in ran, str(ran))
ck("on_done 도 이어진다", any(str(x).startswith("done=") for x in ran), str(ran))

print("\n=== 5. 전체 삭제는 바쁠 때 라우터를 반쯤 비우지 않는다 ===")


class _FakeRouter:
    def __init__(self):
        self._r = [{"keyword": "샤넬"}, {"keyword": "구찌"}]

    def routes(self):
        return list(self._r)

    def remove(self, kw):
        self._r = [x for x in self._r if x["keyword"] != kw]


class _FakeDel(_Fake):
    def __init__(self):
        super().__init__()
        self._router = _FakeRouter()

    def _alert_api(self):
        raise AssertionError("바쁠 때는 API 까지 가면 안 된다")

    _alert_populate = staticmethod(lambda *a, **k: None)
    on_alert_delete_all = m.MainWindow.on_alert_delete_all


# 확인창은 ask_yes_no 로 통일돼 있다(버튼 글자를 한글로 주기 위해서다).
m.ask_yes_no = lambda *a, **k: True

f = _FakeDel()
run_and_pump(f, lambda log: "A")          # 다른 작업이 도는 중
f.on_alert_delete_all()
app.processEvents()
ck("라우터 배정이 남아 있다", len(f._router.routes()) == 2,
   str([r["keyword"] for r in f._router.routes()]))
ck("바쁘다고 알린다", any("진행 중" in a for a in f.alerts), str(f.alerts))

print("\n=== 7. 진행 표시가 켜지고, 끝나면 꺼진다 ===")
f = _Fake()
run_and_pump(f, lambda log: "A", label="엑셀 조건 배정 중")
ck("시작할 때 켜진다", any("엑셀 조건 배정 중" in (x or "") for x in f.busy),
   str(f.busy))
f._alert_worker.finish()
for _ in range(40):
    app.processEvents()
    if "" in f.busy:
        break
    QtCore.QThread.msleep(10)
ck("끝나면 꺼진다", f.busy[-1] == "", str(f.busy))

print("\n=== 8. 대기 중에도 상태를 알린다 ===")
f = _Fake()
run_and_pump(f, lambda log: "A", label="자동 폴링 중")
run_and_pump(f, lambda log: "B", label="엑셀 조건 배정 중", queue=True)
ck("대기 중이라고 말한다",
   any("엑셀 조건 배정 중" in (x or "") and "앞 작업" in (x or "") for x in f.busy),
   str(f.busy))

bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패:", bad)
sys.stdout.flush()
os._exit(1 if bad else 0)

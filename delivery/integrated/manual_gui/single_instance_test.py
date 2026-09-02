"""수동검색과 매물감시는 함께 뜨고, 백그라운드를 도는 창은 하나만 뜨는가.

실서버 2026-09-02: `--watch`(아이콘)와 자동시작 작업이 띄운 `--child`(모드
`all`)가 겹쳐 GUI 가 둘 떴다. 두 KeywordRouter 가 같은 keyword_routes.json 을
서로 덮어 엑셀 조건이 사라졌다.

처음엔 모드별로 잠갔는데 그게 틀렸다 — `watch` 와 `all` 은 이름이 달라 둘 다
통과한다. 잠글 기준은 UI 모드가 아니라 `MODES[...]["background"]` 다:

    manual  background=False  수동검색만 — 수확·폴링·라우터 변경 없음
    watch   background=True   매물감시
    all     background=True   자동시작 작업이 띄우는 3탭

클라는 수동검색과 매물감시를 **두 프로그램으로 동시에** 쓴다. 그건 막으면 안 된다.

실행: python single_instance_test.py
"""
import os
import subprocess
import sys
import tempfile

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


from daangn_ext import single_instance as si

MODES = {
    "manual": {"tabs": ("manual",), "background": False},
    "watch":  {"tabs": ("alert", "emul"), "background": True},
}


def key(mode):
    return si.key_for(mode, MODES)


print("=== 1. 잠그는 기준이 background 다 ===")
ck("모르는 모드(옛 합본)도 watch 와 같은 이름", key("watch") == key("all"),
   f'{key("watch")} vs {key("all")}')
ck("manual 은 다른 이름", key("manual") != key("watch"),
   f'{key("manual")} vs {key("watch")}')

tmp = tempfile.mkdtemp()

print("\n=== 2. 수동 + 매물감시는 동시에 뜬다 (클라 사용법) ===")
ck("매물감시가 뜬다", si.acquire(key("watch"), tmp) is True)
ck("수동검색도 같이 뜬다", si.acquire(key("manual"), tmp) is True)

print("\n=== 3. 백그라운드 창이 둘째는 거절된다 (이번 버그) ===")
ck("자동시작(모드 없음=배경)이 거절된다", si.acquire(key("all"), tmp) is False)
ck("매물감시 두 번째도 거절", si.acquire(key("watch"), tmp) is False)

print("\n=== 4. 수동검색 두 번째도 거절 ===")
ck("manual 재획득 거절", si.acquire(key("manual"), tmp) is False)

print("\n=== 5. 프로세스가 죽으면 락도 풀린다 (스테일 없음) ===")
solo = tempfile.mkdtemp()
code = ("import sys;sys.path.insert(0,%r);"
        "from daangn_ext import single_instance as si;"
        "print(si.acquire('background', %r))" % (os.getcwd(), solo))
r1 = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
ck("자식이 잡는다", r1.stdout.strip() == "True", r1.stdout.strip() + r1.stderr[-200:])
r2 = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
ck("그 프로세스가 끝난 뒤 다시 잡힌다", r2.stdout.strip() == "True",
   r2.stdout.strip() + r2.stderr[-200:])

print("\n=== 6. 두 번째 실행이 먼저 뜬 창을 불러낸다 ===")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PyQt6 import QtCore, QtWidgets
except Exception:
    print("  [SKIP] PyQt6 없음 — 불러내기 검증 생략")
else:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    called = []
    ok = si.serve("summon-test", lambda: called.append(1))
    ck("주인이 문을 연다", ok is True)
    if ok:
        ck("전달된다", si.summon("summon-test") is True)
        for _ in range(50):
            app.processEvents()
            if called:
                break
            QtCore.QThread.msleep(10)
        ck("먼저 뜬 창이 불려 나온다", called == [1], str(called))
        ck("주인이 없으면 실패를 알린다",
           si.summon("summon-test-nobody", timeout_ms=300) is False)

si.release_all()

bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패:", bad)
sys.exit(1 if bad else 0)

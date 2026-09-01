"""실행 모드 분리 계약 — 수동 검색 / 매물 감시를 별도 프로그램으로 쓴다.

클라 요구(2026-09-01): 수동 검색과 '매물 감시+에뮬레이터'를 따로 실행하고 싶다.
코드를 복제하지 않고 한 코드베이스에 모드를 뒀다. 갈라야 하는 건 화면과
백그라운드 기동뿐이고, 상태(accounts.json)는 파일로 공유된다 — 동시 쓰기는
이미 프로세스 간 파일락이 막는다.

Qt 를 띄우지 않고 소스·상수 수준에서 계약을 고정한다(서버·CI 에 디스플레이가 없다).

실행: python run_mode_test.py
"""
import ast
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


src = open("main.py", encoding="utf-8").read()
tree = ast.parse(src)

# MainWindow.MODES 를 소스에서 그대로 꺼낸다(임포트하면 PyQt6 가 필요하다).
modes = None
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == "MainWindow":
        for st in node.body:
            if isinstance(st, ast.Assign) and getattr(st.targets[0], "id", "") == "MODES":
                modes = ast.literal_eval(st.value)
print("=== 1. 모드 정의 ===")
ck("MODES 가 있다", modes is not None)
ck("세 모드", set(modes or {}) == {"all", "manual", "watch"}, str(set(modes or {})))
ck("기본(all)은 종전대로 3탭",
   tuple(modes["all"]["tabs"]) == ("manual", "alert", "emul"))
ck("manual 은 수동 검색만", tuple(modes["manual"]["tabs"]) == ("manual",))
ck("watch 는 감시+에뮬", tuple(modes["watch"]["tabs"]) == ("alert", "emul"))

print("\n=== 2. 수확기는 감시 쪽만 돌린다 ===")
# 둘 다 돌리면 같은 인스턴스에 force-stop 이 겹친다. 수동은 토큰을 소비만 한다.
ck("manual 은 백그라운드 없음", modes["manual"]["background"] is False)
ck("watch 는 백그라운드 있음", modes["watch"]["background"] is True)
ck("all 도 백그라운드 있음", modes["all"]["background"] is True)
ck("수확 스레드가 모드로 갈린다", 'if not self._mode_cfg["background"]:' in src)
ck("자동 폴링도 모드로 갈린다",
   '_mode_cfg", {}).get("background", True)' in src)

print("\n=== 3. 위젯은 모드와 무관하게 다 만든다 ===")
# 서로의 위젯을 참조하는 코드가 흩어져 있어, 안 만들면 AttributeError 가 난다.
ck("세 탭 위젯을 모두 만든다",
   "manual_w = " in src and "alert_w = " in src and "emul_w = " in src)
ck("노출만 모드로 고른다", src.count("if \"manual\" in show:") == 1
   and src.count("if \"alert\" in show:") == 1
   and src.count("if \"emul\" in show:") == 1)

print("\n=== 4. 진입점 ===")
ck("--manual 을 읽는다", '"--manual" in _sysarg.argv' in src)
ck("--watch 를 읽는다", '"--watch" in _sysarg.argv' in src)
ck("인자 없으면 all", '_mode = "all"' in src)
ck("MainWindow 에 모드를 넘긴다", "MainWindow(_mode)" in src)

print("\n=== 5. 워치독이 모드를 물려준다 ===")
# 안 물려주면 재시작 한 번에 수동 전용이 3탭짜리로 되살아나고,
# 수확기까지 도는 프로그램이 둘이 된다.
ns = {}
start = src.index("def _child_cmd():")
end = src.index("def _run_watchdog():")
exec(src[start:end], {"os": os, "__file__": os.path.abspath("main.py")}, ns)
child_cmd = ns["_child_cmd"]

saved = sys.argv
try:
    sys.argv = ["main.py", "--watchdog", "--watch"]
    cmd = child_cmd()
    ck("--watch 가 자식에게 전달된다", "--watch" in cmd, " ".join(cmd[-2:]))
    ck("--child 도 함께", "--child" in cmd)

    sys.argv = ["main.py", "--watchdog", "--manual"]
    ck("--manual 도 전달된다", "--manual" in child_cmd())

    sys.argv = ["main.py", "--watchdog"]
    cmd = child_cmd()
    ck("모드가 없으면 아무것도 안 붙는다",
       "--manual" not in cmd and "--watch" not in cmd, " ".join(cmd[-1:]))

    sys.argv = ["main.py", "--watchdog", "--manual", "--watch"]
    cmd = child_cmd()
    ck("모드가 둘이면 하나만 붙는다",
       len([a for a in cmd if a in ("--manual", "--watch")]) == 1)
finally:
    sys.argv = saved

bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패:", bad)
sys.exit(1 if bad else 0)

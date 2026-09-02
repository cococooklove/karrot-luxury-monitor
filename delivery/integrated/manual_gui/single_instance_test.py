"""같은 모드가 둘 뜨는 것을 막고, 다른 모드는 막지 않는가.

실서버 2026-09-02: 아이콘 실행과 자동시작 작업(karrotgui)이 겹쳐 GUI 가 둘
떴고, 두 KeywordRouter 가 같은 keyword_routes.json 을 서로 덮어 엑셀 조건이
사라졌다.

클라는 `--manual`(수동검색)과 `--watch`(매물감시)를 두 프로그램으로 쓴다 —
통째로 막으면 그 사용법이 깨진다. 같은 모드가 둘인 경우만 사고다.

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

tmp = tempfile.mkdtemp()

print("=== 1. 같은 모드 두 번째는 거절된다 ===")
ck("첫 번째는 잡는다", si.acquire("watch", tmp) is True)
ck("두 번째는 거절", si.acquire("watch", tmp) is False)

print("\n=== 2. 다른 모드는 함께 뜬다 (클라 사용법) ===")
ck("manual 은 따로 잡힌다", si.acquire("manual", tmp) is True)

print("\n=== 3. 프로세스가 죽으면 락도 풀린다 (스테일 없음) ===")
solo = tempfile.mkdtemp()
code = ("import sys;sys.path.insert(0,%r);"
        "from daangn_ext import single_instance as si;"
        "print(si.acquire('watch', %r))" % (os.getcwd(), solo))
r1 = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
ck("자식 프로세스가 잡는다", r1.stdout.strip() == "True", r1.stdout.strip() + r1.stderr[-200:])
r2 = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
ck("그 프로세스가 끝난 뒤에는 다시 잡힌다", r2.stdout.strip() == "True",
   r2.stdout.strip() + r2.stderr[-200:])

print("\n=== 4. 놓으면 다시 잡힌다 ===")
si.release_all()
ck("해제 후 재획득", si.acquire("watch", tmp) is True)

bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패:", bad)
sys.exit(1 if bad else 0)

"""에뮬레이터 스캔 반영(emul_reconcile) 순수 함수 검증 (Qt 창 안 띄움).

    QT_QPA_PLATFORM=offscreen python emul_reconcile_test.py

핵심: 탭에 부착된 LDPlayer 창은 WS_CHILD 라 EnumWindows(top-level 열거)에서
빠진다. 그래서 스캔 결과에 없다고 '사라졌다'고 판정하면 안 되고, IsWindow 로만
생사를 본다. 이걸 어기면 8초마다 부착 창을 떼어 바탕화면에 띄우는 버그가 된다.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, app_dir)
os.chdir(app_dir)

import main as m

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


def row(index, top_hwnd, running=True, name=None, pid=0):
    return {"index": index, "name": name or f"계정{index}", "top_hwnd": top_hwnd,
            "bind_hwnd": 0, "running": running, "pid": pid,
            "title": name or f"계정{index}"}


def alive(*hwnds):
    s = set(hwnds)
    return lambda h: h in s


# 1. 부착 창이 스캔 목록에서 빠져도(child 라 열거 안 됨) 떼지 않는다
live, detach = m.emul_reconcile([row(0, 0, running=False)], {0: 111}, alive(111))
ck("부착 창 스캔 누락 → 유지", detach == [] and 0 in live, f"{detach} {live}")
ck("부착 창 hwnd 는 child hwnd", live[0]["top_hwnd"] == 111, str(live))
ck("부착 창은 running", live[0]["running"] is True)

# 2. 스캔이 같은 pid 의 다른 top-level 창(툴바 등)을 골라와도 떼지 않는다
live, detach = m.emul_reconcile([row(0, 222)], {0: 111}, alive(111, 222))
ck("스캔 hwnd 불일치 → 유지", detach == [] and live[0]["top_hwnd"] == 111,
   f"{detach} {live}")

# 3. 부착 창이 정말 죽었으면(IsWindow 거짓) 뗀다
live, detach = m.emul_reconcile([row(0, 0, running=False)], {0: 111}, alive())
ck("부착 창 죽음 → 분리", detach == [0], str(detach))
ck("죽은 인스턴스는 live 에서 빠짐", 0 not in live, str(live))

# 4. 부착 창 죽고 인스턴스가 새 창으로 다시 떴으면 떼되 새 창은 live 에 남긴다
live, detach = m.emul_reconcile([row(0, 333)], {0: 111}, alive(333))
ck("재기동 → 분리 + 새 창 live", detach == [0] and live[0]["top_hwnd"] == 333,
   f"{detach} {live}")

# 5. 부착 안 된 인스턴스는 기존대로 스캔 결과를 따른다
live, detach = m.emul_reconcile(
    [row(1, 444), row(2, 555, running=False), row(3, 666)],
    {}, alive(444, 555))
ck("미부착: running+IsWindow 인 것만", sorted(live) == [1], str(sorted(live)))

# 6. 부착 + 미부착 섞임
live, detach = m.emul_reconcile([row(1, 444), row(0, 0, running=False)],
                                {0: 111}, alive(111, 444))
ck("섞임", detach == [] and sorted(live) == [0, 1], f"{detach} {sorted(live)}")

# 7. 부착 창이 스캔에 아예 없어도(list2 행 자체 누락) 이름을 지어 유지한다
live, detach = m.emul_reconcile([], {7: 777}, alive(777))
ck("list2 행 누락 → 유지·제목 있음", detach == [] and live[7]["title"],
   f"{detach} {live}")

fails = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(fails)}/{len(R)} passed")
if fails:
    print("FAILED:", fails)
    sys.exit(1)

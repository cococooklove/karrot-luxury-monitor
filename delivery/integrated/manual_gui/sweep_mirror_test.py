"""앱 알림 사각지대를 스윕이 메울 수 있는가 — 미러 배선 계약.

실서버 상태: 브랜드 20개가 전부 앱 슬롯(상한 30)에 들어가 스윕 큐가 비었고,
검색 스윕은 아예 뜨지 않았다. 그런데 앱 알림은 **계정 인증동네** 기반이라
운영 계정(오산·평택)이 보는 곳만 본다 — 서울 명품은 아무도 안 보고 있었다.
스윕은 지역을 인자로 받으므로 그 사각지대를 메울 수 있는 유일한 경로다.

기본은 꺼져 있어야 한다. 켜면 설정된 지역 전체(서울 806동)의 매물이 알림으로
나가므로 받는 쪽이 감당할지는 운영 판단이다.

실행: python sweep_mirror_test.py
"""
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


src = open("main.py", encoding="utf-8").read()
ns = {}
start = src.index("def mirror_app_keywords_to_sweep(")
end = src.index("def harvest_interval()")
exec(src[start:end], ns)
mirror = ns["mirror_app_keywords_to_sweep"]


class _Router:
    def __init__(self, rows):
        self._rows = rows

    def routes(self):
        return list(self._rows)


class _Queue:
    def __init__(self, existing=()):
        self.items = list(existing)

    def add(self, keyword, **_kw):
        if keyword in self.items:
            return False
        self.items.append(keyword)
        return True


ROWS = [{"keyword": "샤넬", "route": "app"},
        {"keyword": "구찌", "route": "app"},
        {"keyword": "롤렉스", "route": "sweep"}]

print("=== 1. 기본은 꺼져 있다 ===")
q = _Queue()
n = mirror(_Router(ROWS), q, enabled=False)
ck("끄면 아무것도 안 싣는다", n == 0 and q.items == [],
   "켜면 서울 전역 매물이 알림으로 나간다 — 운영 판단")

print("\n=== 2. 켜면 앱 배정 키워드가 스윕에도 실린다 ===")
q = _Queue()
logs = []
n = mirror(_Router(ROWS), q, log=logs.append, enabled=True)
ck("app 인 것만 싣는다", n == 2 and set(q.items) == {"샤넬", "구찌"}, f"{q.items}")
ck("이미 sweep 인 것은 건드리지 않는다", "롤렉스" not in q.items)
ck("무엇을 왜 했는지 남긴다", any("스윕미러" in m for m in logs), f"{logs}")

print("\n=== 3. 두 번 돌려도 중복되지 않는다 ===")
n2 = mirror(_Router(ROWS), q, enabled=True)
ck("이미 실린 것은 다시 안 센다", n2 == 0 and len(q.items) == 2, f"{q.items}")

print("\n=== 4. 없거나 깨져도 폴링을 멈추지 않는다 ===")
ck("라우터 없음", mirror(None, _Queue(), enabled=True) == 0)
ck("큐 없음", mirror(_Router(ROWS), None, enabled=True) == 0)


class _Boom:
    def routes(self):
        raise RuntimeError("routes 폭발")


logs = []
ck("라우터가 터져도 0 을 돌려준다",
   mirror(_Boom(), _Queue(), log=logs.append, enabled=True) == 0)
ck("터진 사실은 남긴다", any("실패" in m for m in logs), f"{logs}")


class _BadQueue(_Queue):
    def add(self, keyword, **_kw):
        if keyword == "구찌":
            raise RuntimeError("큐 폭발")
        return super().add(keyword)


logs = []
q = _BadQueue()
n = mirror(_Router(ROWS), q, log=logs.append, enabled=True)
ck("한 키워드가 터져도 나머지는 실린다", "샤넬" in q.items and n == 1, f"{q.items}")

print("\n=== 5. 두 런타임 모두 배선돼 있다 ===")
ck("GUI·헤드리스 양쪽에서 호출한다",
   src.count("mirror_app_keywords_to_sweep(") >= 3,
   f"{src.count('mirror_app_keywords_to_sweep(')}곳(정의 1 + 호출 2)")
ck("설정 키로 켠다", src.count("sweep_mirror_app") >= 2,
   f"{src.count('sweep_mirror_app')}곳")

bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패:", bad)
sys.exit(1 if bad else 0)

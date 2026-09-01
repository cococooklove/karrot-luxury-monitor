"""엑셀 조건이 껐다 켜도, 일괄등록을 해도 살아남는가.

실서버에서 20/20 키워드가 조건 없이 남아 있었다. 클라는 엑셀을 넣은 적이 있다고
했고 실제로 그랬다 — `add()` 가 `extra`·`days` 만 이전 조건에서 이어받고
`min`·`max`·`exclude` 는 흘려보냈기 때문이다. 그래서 '명품20 전계정등록'이나
승격·재시도가 한 번 돌면 가격·제외어가 지워졌다. 주석은 "안 넘어온 것은 이전
조건을 잇는다"였는데 구현이 절반만 그랬다.

조건을 지우거나 바꾸는 권한은 엑셀을 다시 불러오는 경로에만 있다.

실행: python cond_persist_test.py
"""
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

import json
import tempfile

from daangn_ext.keyword_router import KeywordRouter

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


class _Alerts:
    """등록은 언제나 성공한다 — 여기서 보려는 건 조건 보존이다."""

    def register_all(self, kws, mn, mx, ex, log=None, core_only=False):
        return {"added": len(kws), "skipped": 0, "failed": 0}

    def keywords(self):
        return []


class _Queue:
    def add(self, *a, **k):
        return True

    def remove(self, *a, **k):
        return True

    def keywords(self):
        return []

    def entries(self):
        return []

    def __len__(self):
        return 0


tmp = tempfile.mkdtemp()
FP = os.path.join(tmp, "routes.json")


def router():
    return KeywordRouter(_Alerts(), _Queue(), routes_fp=FP)


print("=== 1. 엑셀 조건이 저장된다 ===")
r = router()
r.add("샤넬", min_price=1000000, max_price=5000000, exclude=["레플", "짝퉁"],
      extra=["클래식"], days=7, replace_cond=True)
c = r.condition_for("샤넬")
ck("가격이 남는다", c.get("min") == 1000000 and c.get("max") == 5000000, str(c))
ck("제외어가 남는다", c.get("exclude") == ["레플", "짝퉁"])
ck("추가어·끌올일수가 남는다", c.get("extra") == ["클래식"] and c.get("days") == 7)

print("\n=== 2. 껐다 켜도 남는다 ===")
c2 = router().condition_for("샤넬")
ck("디스크에서 그대로 읽힌다", c2 == c, str(c2))

print("\n=== 3. 일괄등록이 조건을 지우지 않는다 (이번 사고) ===")
r3 = router()
r3.add("샤넬")                      # '명품20 전계정등록' 처럼 조건 없이
c3 = r3.condition_for("샤넬")
ck("가격이 살아남는다", c3.get("min") == 1000000 and c3.get("max") == 5000000, str(c3))
ck("제외어가 살아남는다", c3.get("exclude") == ["레플", "짝퉁"])
ck("추가어·끌올일수도 살아남는다", c3.get("extra") == ["클래식"] and c3.get("days") == 7)
ck("디스크에도 남는다", router().condition_for("샤넬") == c3)

print("\n=== 4. add_many(일괄) 도 마찬가지 ===")
r4 = router()
r4.add_many(["샤넬", "구찌"])       # 조건 없는 일괄 경로
ck("기존 키워드 조건 유지", r4.condition_for("샤넬").get("min") == 1000000)
ck("새 키워드는 조건 없음", r4.condition_for("구찌") == {})

print("\n=== 5. 엑셀을 다시 불러오면 바뀐다 ===")
r5 = router()
r5.add_many(["샤넬"], 2000000, None, [], extra=None, days=None,
            replace_cond=True)
c5 = r5.condition_for("샤넬")
ck("새 최소가로 바뀐다", c5.get("min") == 2000000, str(c5))
ck("엑셀에서 뺀 상한은 사라진다", "max" not in c5, str(c5))
ck("엑셀에서 뺀 제외어도 사라진다", "exclude" not in c5, str(c5))
ck("디스크에 반영된다", router().condition_for("샤넬") == c5)

print("\n=== 6. 엑셀 경로만 그 권한을 쓴다 ===")
src = open("main.py", encoding="utf-8").read()
ck("_route_conditions 가 replace_cond=True", "replace_cond=True" in src)
# 실제 호출부만 센다 — 독스트링에도 같은 낱말이 나온다.
calls = src.count("replace_cond=True)")
ck("호출부는 엑셀 경로 한 곳뿐", calls == 1, f"{calls}곳")

print("\n=== 7. 조건 없는 키워드는 그대로 조건 없음 ===")
r7 = router()
r7.add("에르메스")
ck("빈 조건", r7.condition_for("에르메스") == {})

bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패:", bad)
sys.exit(1 if bad else 0)

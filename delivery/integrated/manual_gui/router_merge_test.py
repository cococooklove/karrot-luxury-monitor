"""두 창이 같은 keyword_routes.json 을 써도 엑셀 조건이 사라지지 않는가.

실서버 2026-09-02 00:31~00:33 에 난 일:
    00:31:50  A 창이 엑셀 조건과 함께 3개 저장
    00:33:23  B 창이 자기 (오래된) 사본으로 덮음 → 조건 소실
              → B 가 서버 목록을 보고 조건 없이 3개 재씨딩
클라에게는 "엑셀을 넣어도 반영이 안 된다"로 보였다.

원인은 `_save` 가 `dict(self._routes)` 를 통째로 덮은 것. 클라는 `--manual` 과
`--watch` 를 두 프로그램으로 쓰고, 같은 창이 실수로 둘 뜨기도 한다. 각
MainWindow 가 라우터를 하나씩 만들어 같은 파일을 쓴다.

실행: python router_merge_test.py
"""
import json
import os
import sys
import tempfile

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


from daangn_ext.keyword_router import ROUTE_APP, ROUTE_SWEEP, KeywordRouter


class _Q:
    def add(self, *a, **k):
        pass

    def remove(self, *a, **k):
        pass

    def __len__(self):
        return 0


def mk(fp):
    return KeywordRouter(None, _Q(), routes_fp=fp)


def read(fp):
    with open(fp, encoding="utf-8") as f:
        return {k: v for k, v in json.load(f).items() if not k.strip().startswith("__cap__")}


tmp = tempfile.mkdtemp()
FP = os.path.join(tmp, "keyword_routes.json")

EXCEL = {"route": ROUTE_APP, "reason": "앱 알림 등록", "at": 100,
         "cond": {"min": 500000, "max": 3000000, "exclude": ["레플"]}}

print("=== 1. 늦게 저장하는 창이 남의 조건을 지우지 않는다 (이번 버그) ===")
a, b = mk(FP), mk(FP)                      # 둘 다 빈 파일에서 출발
a._routes["샤넬"] = dict(EXCEL)            # A: 엑셀로 조건 등록
a._save()
b._routes["롤렉스"] = {"route": ROUTE_SWEEP, "reason": "슬롯 만원", "at": 200}
b._save()                                  # B: 자기 사본(샤넬 없음)으로 저장
on_disk = read(FP)
ck("A 의 키워드가 남아 있다", "샤넬" in on_disk, str(list(on_disk)))
ck("엑셀 조건이 그대로다", (on_disk.get("샤넬") or {}).get("cond") == EXCEL["cond"],
   str((on_disk.get("샤넬") or {}).get("cond")))
ck("B 의 키워드도 있다", "롤렉스" in on_disk, str(list(on_disk)))

print("\n=== 2. 저장한 쪽은 남이 넣은 키도 받아 온다 ===")
ck("B 가 샤넬을 알게 된다", "샤넬" in b._routes, str(list(b._routes)))
ck("B 의 used 가 맞다", b.capacity()["used"] == 1, str(b.capacity()))

print("\n=== 3. 삭제는 되살아나지 않는다 ===")
c = mk(FP)                                 # 디스크에 샤넬·롤렉스가 있는 상태로 시작
c._routes.pop("샤넬")
c._save()
on_disk = read(FP)
ck("지운 키가 사라졌다", "샤넬" not in on_disk, str(list(on_disk)))
ck("안 지운 키는 남았다", "롤렉스" in on_disk, str(list(on_disk)))

print("\n=== 4. 같은 키를 고치면 내 값이 이긴다 ===")
d, e = mk(FP), mk(FP)
d._routes["롤렉스"] = dict(EXCEL)          # D: 조건을 붙임
d._save()
e._routes["펜디"] = {"route": ROUTE_APP, "reason": "앱 알림 등록", "at": 300}
e._save()                                  # E: 롤렉스는 손대지 않았다
on_disk = read(FP)
ck("D 가 붙인 조건이 살아 있다",
   (on_disk.get("롤렉스") or {}).get("cond") == EXCEL["cond"],
   str((on_disk.get("롤렉스") or {}).get("cond")))
ck("E 의 키워드도 있다", "펜디" in on_disk, str(list(on_disk)))

print("\n=== 5. 상한 관측치는 하강만 한다 ===")
f, g = mk(FP), mk(FP)
f._observed_cap = 12
f._save()
g._observed_cap = 20
g._save()
with open(FP, encoding="utf-8") as fh:
    meta = json.load(fh).get("  __cap__")
ck("더 낮은 관측이 유지된다", (meta or {}).get("observed") == 12, str(meta))

bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패:", bad)
sys.exit(1 if bad else 0)

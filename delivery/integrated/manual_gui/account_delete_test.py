"""계정을 화면에서 지울 때 옆 계정의 토큰이 같이 날아가지 않는가.

`accounts.json` 의 refresh 토큰은 이 기계에서 재발급할 수 없다 — 당근 WAF 가
PC 갱신을 막아서, 복구 경로는 폰 앱 스택이나 LDPlayer `.ldbk` 복원뿐이다.

종전 `remove()` 는 (a) 메모리 사본을 통째로 덮어써서 그 사이 수확기가 넣은
토큰을 지웠고, (b) refresh/label 로만 찾아서 수확으로 들어온 계정(label 이
비고 code 만 있다)을 화면에서 골라도 못 지웠으며, (c) 지운 줄을 어디에도
남기지 않았다.

실행: python account_delete_test.py
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


from daangn_ext import AccountStore

ROWS = [
    {"code": "aaa", "refresh": "R-aaa", "access": "A-aaa", "label": "", "proxy": "p1"},
    {"code": "bbb", "refresh": "R-bbb", "access": "A-bbb", "label": "폰2", "proxy": "p2"},
    {"code": "ccc", "refresh": "R-ccc", "access": "A-ccc", "label": "", "proxy": "p3"},
]


def fresh():
    d = tempfile.mkdtemp()
    fp = os.path.join(d, "accounts.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(ROWS, f, ensure_ascii=False)
    return fp


def read(fp):
    with open(fp, encoding="utf-8") as f:
        return json.load(f)


print("=== 1. code 로 지울 수 있다 (화면에 보이는 값) ===")
fp = fresh()
s = AccountStore(fp)
ok = s.remove("aaa")
ck("지웠다고 알린다", ok is True, repr(ok))
left = [r["code"] for r in read(fp)]
ck("그 계정만 빠졌다", left == ["bbb", "ccc"], str(left))

print("\n=== 2. label 과 refresh 로도 지워진다 ===")
fp = fresh()
s = AccountStore(fp)
ck("label 로 지운다", s.remove("폰2") is True)
ck("refresh 로 지운다", s.remove("R-ccc") is True)
ck("하나만 남았다", [r["code"] for r in read(fp)] == ["aaa"], str(read(fp)))

print("\n=== 3. 없는 계정은 False, 파일은 그대로 ===")
fp = fresh()
s = AccountStore(fp)
ck("False 를 돌려준다", s.remove("없는계정") is False)
ck("파일이 그대로다", len(read(fp)) == 3, str(len(read(fp))))

print("\n=== 4. 그 사이 수확된 토큰을 덮지 않는다 (이번 핵심) ===")
fp = fresh()
s = AccountStore(fp)                    # 여기서 3줄을 메모리에 들고 있다
disk = read(fp)                         # 수확기가 파일을 갱신한다
disk[1]["access"] = "A-bbb-새로수확"
disk.append({"code": "ddd", "refresh": "R-ddd", "access": "A-ddd", "label": ""})
with open(fp, "w", encoding="utf-8") as f:
    json.dump(disk, f, ensure_ascii=False)
s.remove("aaa")                         # 옛 사본을 든 채로 지운다
after = read(fp)
ck("새로 수확된 access 가 살아 있다",
   [r for r in after if r["code"] == "bbb"][0]["access"] == "A-bbb-새로수확",
   str([r for r in after if r["code"] == "bbb"]))
ck("그 사이 추가된 계정이 살아 있다", any(r["code"] == "ddd" for r in after),
   str([r["code"] for r in after]))
ck("지우려던 것만 빠졌다", [r["code"] for r in after] == ["bbb", "ccc", "ddd"],
   str([r["code"] for r in after]))

print("\n=== 5. 지운 줄은 남겨서 되돌릴 수 있다 ===")
fp = fresh()
s = AccountStore(fp)
s.remove("aaa")
graveyard = fp + ".deleted"
ck("무덤 파일이 생긴다", os.path.exists(graveyard), graveyard)
if os.path.exists(graveyard):
    g = read(graveyard)
    ck("지운 계정이 통째로 들어 있다",
       any(r.get("code") == "aaa" and r.get("refresh") == "R-aaa" for r in g), str(g))
    s.remove("bbb")
    g = read(graveyard)
    ck("여러 번 지워도 쌓인다", len(g) == 2, str([r.get("code") for r in g]))

bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패:", bad)
sys.exit(1 if bad else 0)

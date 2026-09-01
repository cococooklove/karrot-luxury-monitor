"""기존 계정에 프록시를 붙일 수 있는가 — 그리고 그게 토큰을 날리지 않는가.

지금까지 계정+프록시 다이얼로그는 추가/삭제만 있었다. 그런데 실제 계정은 전부
LDPlayer 수확으로 들어오므로(PC 직접 갱신은 WAF 가 막는다) 화면에서 프록시를
붙일 방법이 아예 없었다 — accounts.json 을 손으로 고치는 수밖에.

여기서 진짜 위험한 건 저장 방식이다. accounts.json 은 이 기계에서 재발급할 수
없는 세션 토큰의 유일한 사본이고, 수확기가 같은 파일을 병합하며 쓴다. 메모리에
들고 있던 옛 내용을 통째로 덮으면 그 사이 수확된 토큰이 사라진다.

실행: python account_proxy_test.py
"""
import json
import os
import sys
import tempfile

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

from daangn_ext.account_store import AccountStore

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


tmp = tempfile.mkdtemp()
FP = os.path.join(tmp, "accounts.json")
BASE = [
    {"code": "452902", "refresh": "r1", "access": "a1", "label": ""},
    {"code": "463777", "refresh": "r2", "access": "a2", "label": "정지6"},
]


def fresh():
    json.dump(BASE, open(FP, "w", encoding="utf-8"), ensure_ascii=False)
    return AccountStore(FP)


def disk():
    return json.load(open(FP, encoding="utf-8"))


print("=== 1. code 로 찾아 붙인다(수확 계정은 label 이 없다) ===")
st = fresh()
ck("code 로 저장된다", st.set_proxy("452902", "http://u:p@1.2.3.4:8000"))
ck("디스크에 반영", disk()[0].get("proxy") == "http://u:p@1.2.3.4:8000", str(disk()[0]))
ck("다른 계정은 안 건드린다", "proxy" not in disk()[1], str(disk()[1]))

print("\n=== 2. label·refresh 로도 찾는다 ===")
ck("label", st.set_proxy("정지6", "http://a:b@5.6.7.8:9000"))
ck("refresh", st.set_proxy("r1", "http://x:y@9.9.9.9:1111"))
ck("둘 다 반영", disk()[1]["proxy"].endswith(":9000")
   and disk()[0]["proxy"].endswith(":1111"))

print("\n=== 3. 비우면 직결(키 자체를 뺀다) ===")
ck("빈 값 저장", st.set_proxy("452902", ""))
ck("proxy 키가 사라진다", "proxy" not in disk()[0], str(disk()[0]))
ck("None 도 같다", st.set_proxy("정지6", None) and "proxy" not in disk()[1])

print("\n=== 4. 없는 계정은 조용히 실패 ===")
ck("없는 키", st.set_proxy("없는계정", "http://1.1.1.1:1") is False)
ck("빈 키", st.set_proxy("", "http://1.1.1.1:1") is False)
ck("파일은 그대로", len(disk()) == 2)

print("\n=== 5. 토큰을 날리지 않는다 (핵심) ===")
# 스토어를 만든 뒤 수확기가 파일을 갱신한 상황을 흉내낸다.
st2 = fresh()                       # 이 시점 메모리: access a1/a2
after = json.load(open(FP, encoding="utf-8"))
after[0]["access"] = "수확으로_갱신된_새_토큰"
after.append({"code": "999999", "refresh": "r9", "access": "a9", "label": "새계정"})
json.dump(after, open(FP, "w", encoding="utf-8"), ensure_ascii=False)

st2.set_proxy("463777", "http://k:r@2.2.2.2:2222")
d = disk()
ck("그 사이 갱신된 토큰이 살아있다", d[0]["access"] == "수확으로_갱신된_새_토큰",
   d[0]["access"])
ck("그 사이 추가된 계정도 살아있다", len(d) == 3 and d[2]["code"] == "999999",
   f"{len(d)}계정")
ck("프록시는 제대로 붙었다", d[1].get("proxy", "").endswith(":2222"))

print("\n=== 6. 수확기와 같은 파일락을 탄다 ===")
src = open("daangn_ext/account_store.py", encoding="utf-8").read()
ck("ld_autoharvest 의 _file_lock 을 쓴다", "from ld_autoharvest import _file_lock" in src)
ck("락 모듈이 없어도 죽지 않는다", "except Exception:" in src)
ck("임시파일 → os.replace 로 원자적 교체", "os.replace(tmp, self.path)" in src)

print("\n=== 7. 화면에서 쓸 수 있게 배선됐다 ===")
m = open("main.py", encoding="utf-8").read()
ck("프록시 저장 버튼이 있다", "선택 계정에 프록시 저장" in m)
ck("set_proxy 를 부른다", "store.set_proxy(" in m)
ck("고른 계정의 현재 프록시를 보여준다", "listw.currentRowChanged.connect" in m)
ck("code 로도 이름을 표시한다", 'r.get("label") or r.get("code")' in m)
ck("계정 늘리는 법을 화면에 적어둔다", ".ldbk" in m)

bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패:", bad)
sys.exit(1 if bad else 0)

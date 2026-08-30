"""daangn_ext 공통 로직 + 창 조립 테스트 (네트워크 불필요).

    python full_test.py

옛 버전은 실제 당근 API 를 때리는 구간(라이브 수집)과 없어진 API
(TokenManager.ensure_safe)를 함께 들고 있어 오래 빨간 채로 있었다. 라이브
구간은 자격증명 없는 환경에서 영원히 실패하므로 뺐고, 검색 스윕 엔진 구간은
sweep_engine_test.py 가 엔진을 직접 검증하므로 거기로 넘겼다. 여기 남은 것은
다른 스위트가 건드리지 않는 daangn_ext 순수 로직과 창 조립이다.
"""
import base64
import json
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, app_dir)
os.chdir(app_dir)

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


print("=== A. 토큰 매니저 ===")
from daangn_ext import token_manager as T


def mkjwt(code="z", ttl=1800, age=0, typ="access"):
    now = int(time.time()) - age
    h = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    p = base64.urlsafe_b64encode(json.dumps(
        {"iat": now, "exp": now + ttl, "code": code, "type": typ}
    ).encode()).rstrip(b"=").decode()
    return f"{h}.{p}.s"


ck("토큰 code 디코드", T.token_code(mkjwt()) == "z")
ck("토큰 exp 디코드",
   T._jwt_payload(mkjwt())["exp"] - T._jwt_payload(mkjwt())["iat"] == 1800)

refreshed = {"n": 0}


def fr(acc):
    refreshed["n"] += 1
    return mkjwt(ttl=1800), mkjwt(ttl=21600, typ="refresh")


tm = T.TokenManager(refresh_fn=fr)
a = tm.add(refresh=mkjwt(typ="refresh"), access=mkjwt(ttl=1800, age=1795))
tm.ensure(a)
ck("만료 임박이면 검색 전에 갱신", refreshed["n"] == 1 and a.expires_in() > 1700)
tm.ensure(a)
ck("아직 살아 있으면 갱신 안 함", refreshed["n"] == 1)

# 갱신이 실패해도 배치 전체가 죽으면 안 된다 — refresh_all 이 계정별로 삼킨다.
# (옛 ensure_safe 자리. 그 메서드는 없어졌고 이쪽이 실제 graceful 경로다.)
ck("ensure_safe 는 없어진 API", not hasattr(T.TokenManager, "ensure_safe"))


def boom(acc):
    raise RuntimeError("refresh endpoint down")


tm2 = T.TokenManager(refresh_fn=boom)
tm2.add(refresh=mkjwt(code="a", typ="refresh"), access=mkjwt(ttl=1800, age=1795))
tm2.add(refresh=mkjwt(code="b", typ="refresh"), access=mkjwt(ttl=1800))
try:
    st = tm2.refresh_all()
except Exception as e:
    st = {"raised": str(e)}
ck("갱신 실패는 계정별로 격리(예외를 밖으로 안 던짐)",
   len(st) == 2 and any("fail" in v for v in st.values())
   and any(v.startswith("ok") for v in st.values()), str(st))

print("\n=== B. 검색 필터 ===")
from daangn_ext.search_filters import KeywordRule, apply_filter


class P:
    def __init__(self, n, d):
        self.name, self.description = n, d


prods = [P("샤넬 클래식 정품 영수증", "풀박스"), P("샤넬 레플 미러급", "가품"),
         P("구찌 지갑", "정품")]
kept = apply_filter(prods, KeywordRule(required=["샤넬"], extra=["정품"],
                                       extra_mode="and", exclude=["레플", "미러"]))
ck("포함+추가+제외 동시 적용",
   len(kept) == 1 and kept[0].name.startswith("샤넬 클래식"), str([p.name for p in kept]))
ck("제외어는 설명에도 걸린다",
   apply_filter([P("샤넬 가방", "가품입니다")],
                KeywordRule(required=["샤넬"], exclude=["가품"])) == [])

print("\n=== C. 계정·프록시 저장소 ===")
from daangn_ext.account_store import AccountStore

st_path = tempfile.mktemp(suffix=".json")
store = AccountStore(st_path)
store.add_pair(mkjwt(typ="refresh"), "http://u:p@1.2.3.4:8000", "010")
ck("계정+프록시 저장",
   len(store) == 1 and store.proxies() == ["http://u:p@1.2.3.4:8000"])
ck("파일로 남는다(재시작 대비)", os.path.exists(st_path))
ck("다시 열면 그대로", len(AccountStore(st_path)) == 1)

print("\n=== D. 토큰 주입 · 휴식 ===")
from daangn_ext import auth, rest_scheduler

h1 = auth.build_headers("https://api.kr.karrotmarket.com/x", "TOK")
h2 = auth.build_headers("https://www.daangn.com/x", "TOK")
ck("당근 API 에만 토큰 주입",
   h1.get("authorization") == "Bearer TOK" and "authorization" not in h2)
ck("휴식은 지정 범위 안", 0 <= rest_scheduler.sleep_between(0, 0.01) <= 0.01)

print("\n=== E. 창 조립 (offscreen) ===")
try:
    from PyQt6.QtWidgets import QApplication
    import main

    app = QApplication.instance() or QApplication([])
    w = main.MainWindow()
    ck("탭 3개", w.tabs.count() == 3,
       str([w.tabs.tabText(i) for i in range(w.tabs.count())]))
    ck("탭 이름",
       [w.tabs.tabText(i) for i in range(w.tabs.count())]
       == ["수동 검색", "매물 감시", "에뮬레이터"])
    ck("수동 검색 위젯",
       all(hasattr(w, x) for x in ("extraEdit", "excludeEdit", "tokenRefreshCheck",
                                   "accountsBtn", "proxyViewBtn")))
    ck("감시 위젯",
       all(hasattr(w, x) for x in ("watchToggleBtn", "advancedBox", "listingTable",
                                   "alertTable", "alertLog", "_notify")))
except Exception as e:
    import traceback

    ck("창 조립", False, str(e)[:80])
    traceback.print_exc()

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

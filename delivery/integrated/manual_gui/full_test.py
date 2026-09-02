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

# 클라 요구: "띄어쓰기 상관없이 그 글자가 다 포함된 글이면 잡아낸다".
kw = "루이비통 오버 더 문"
spaced = [P("루이비통 오버 더 문 팝니다", ""), P("루이비통 오버더 문", ""),
          P("루이비통 오 버더문", ""), P("루이비통", "내용~~~~ 오버더문"),
          P("노에 나노 루이비통", "")]
ck("띄어쓰기 달라도 어절이 다 있으면 잡는다",
   len(apply_filter(spaced[:4], KeywordRule(required=[kw]))) == 4,
   str([p.name for p in apply_filter(spaced[:4], KeywordRule(required=[kw]))]))
ck("어순이 뒤집혀도 잡는다",
   len(apply_filter([spaced[4]], KeywordRule(required=["루이비통 나노 노에"]))) == 1)
ck("무관 매물은 안 잡는다",
   apply_filter([P("샤넬 클래식 미디움", "")], KeywordRule(required=[kw])) == [])

# 숫자 어절은 앞 어절에 붙어 있어야 한다 — 안 그러면 "50만원"이 사이즈로 걸린다.
num_rule = KeywordRule(required=["루이비통 반둘리에 50"])
ck("숫자 사이즈: 붙어 있으면 잡는다",
   len(apply_filter([P("루이비통 반둘리에 50 정품", ""),
                     P("루이비통 반둘리에 사이즈 50", "")], num_rule)) == 2)
ck("숫자 사이즈: 다른 사이즈 + 가격의 숫자는 안 잡는다",
   apply_filter([P("루이비통 반둘리에25 급처", "가격 50만원 네고")], num_rule) == [])

ck("삽니다 글은 컷",
   apply_filter([P("루이비통 오버더문 삽니다", "")], KeywordRule(required=[kw])) == [])
ck("drop_wanted=False 면 삽니다도 통과",
   len(apply_filter([P("루이비통 오버더문 삽니다", "")],
                    KeywordRule(required=[kw], drop_wanted=False))) == 1)
# 공백을 지운 채 표식을 찾으면 "친구 함께"가 "구함"이 되어 판매글이 사라졌다.
from daangn_ext.search_filters import looks_wanted_ad
ck("'친구 함께'·'가구 함'은 구매글이 아니다",
   not looks_wanted_ad("루이비통 노에 친구 함께 쓰던 가방")
   and not looks_wanted_ad("명품 수납 가구 함 판매")
   and looks_wanted_ad("루이비통 지갑 삽니다"))

# 제목 끝 글자와 본문 첫 글자가 붙어 없던 단어가 생기면 안 된다.
ck("제목·본문 경계를 넘는 어절은 안 잡는다",
   apply_filter([P("루이비통 오버 더", "문의주세요")], KeywordRule(required=[kw])) == [])
# 한 글자 어절('더','문')을 따로 찾으면 아무 데나 걸린다 → 앞 어절에 붙인다.
from daangn_ext.search_filters import keyword_patterns
ck("한 글자 어절은 앞 어절에 붙는다",
   [p.pattern for p in keyword_patterns(kw)] == ["루이비통", "오버더문"],
   str([p.pattern for p in keyword_patterns(kw)]))
ck("앞 어절 없는 숫자는 다른 수의 일부로 안 걸린다",
   not apply_filter([P("가방 550000원", "")], KeywordRule(required=["50 가방"]))
   and len(apply_filter([P("50 가방", "")], KeywordRule(required=["50 가방"]))) == 1)

print("\n=== B-2. 알림 룰 테이블 ===")
from daangn_ext.alert_rules import RuleTable, parse_rule_rows, HIT, WATCH, CUT, PASS

rule_rows = [("키워드", "최소가격", "최대가격"),
             ("루이비통 오버 더 문", 500000, 1500000),
             ("루이비통 반둘리에 50", 600000, 2000000),
             ("루이비통 반둘리에 25", 1000000, 2000000),
             ("루이비통 몽테뉴 GM", "700,000", "1,000,000"),
             ("", None, None),
             ("루이비통 역전", 900000, 100000)]
_rules, _errs = parse_rule_rows(rule_rows)
ck("빈 줄은 건너뛰고 최소>최대 줄은 오류로 남긴다",
   len(_rules) == 4 and len(_errs) == 1, f"{len(_rules)} / {_errs}")
rt = RuleTable(_rules)
ck("룰 테이블 판정",
   all(rt.verdict(t, p)[0] == v for t, p, v in [
       ("루이비통 오버더문 급처", "900,000원", HIT),
       ("루이비통 오 버더 문", 1200000, HIT),
       ("루이비통 오버더문", "285만원", WATCH),      # 상한 초과 → 추적
       ("루이비통 오버더문", 300000, CUT),           # 하한 미달
       ("루이비통 오버더문 삽니다", 900000, CUT),
       ("샤넬 클래식", 900000, CUT),
       ("루이비통 몽테뉴gm", 800000, HIT),
       ("루이비통 오버더문", None, HIT),             # 가격 못 읽음 → 버리지 않는다
   ]))
ck("숫자 사이즈는 룰끼리도 안 섞인다",
   rt.verdict("루이비통 반둘리에25 급처 50만원", 1500000)[1].keyword
   == "루이비통 반둘리에 25")
ck("빈 테이블은 아무것도 안 거른다", RuleTable().verdict("아무거나", 1)[0] == PASS)
ck("제목·본문 경계를 넘는 어절은 안 잡는다",
   rt.verdict("루이비통 오버 더", 900000, body="문의주세요")[0] == CUT
   and rt.verdict("루이비통", 900000, body="상세: 오버더문 정품")[0] == HIT)
_exc, _ = parse_rule_rows([("키워드", "최소가격", "최대가격", "제외"),
                           ("루이비통 오버 더 문", 500000, 1500000, "A급 레플리카, 부속품")])
_ert = RuleTable(_exc)
ck("제외는 쉼표로만 나눈다(구절 단위)",
   _exc[0].exclude == ("A급 레플리카", "부속품")
   and _ert.verdict("루이비통 오버더문 A급 레플리카", 900000)[0] == CUT
   and _ert.verdict("루이비통 오버더문 A급 정품", 900000)[0] == HIT)
ck("'285만원' 같은 축약가도 읽는다",
   rt.verdict("루이비통 오버더문", "125만원")[0] == HIT)
_p = tempfile.mktemp(suffix=".json")
rt.save(_p)
ck("화면 요약", "조건 4개" in rt.summary() and "브랜드" in rt.summary(),
   rt.summary())
ck("조건 없으면 그 사실을 말한다", "없음" in RuleTable().summary()
   and "없음" in RuleTable().detail(), RuleTable().summary())
_at = RuleTable(list(rt.rules))
_ap = tempfile.mktemp(suffix=".json")
_at.save(_ap)
ck("적용 시각이 남는다", RuleTable.load(_ap).applied_at > 0
   and "적용" in RuleTable.load(_ap).detail(), RuleTable.load(_ap).detail())
ck("저장·복원", len(RuleTable.load(_p)) == len(rt)
   and RuleTable.load(_p).verdict("루이비통 오버더문", 900000)[0] == HIT)
ck("없는 파일은 빈 테이블", len(RuleTable.load(tempfile.mktemp())) == 0)

# 엑셀 한 장으로 등록과 알림 조건을 같이 넣는다 — 옛 '엑셀 조건' 시트도 읽힌다.
from daangn_ext.alert_rules import brand_days, brands

_old_sheet = [("대분류", "키워드", "추가키워드", "제외키워드",
               "최소금액", "최대금액", "끌올일수"),
              ("가방", "루이비통 오버 더 문", "정품", "레플, 미러", 500000, 1500000, 7),
              ("가방", "샤넬 클래식", "", "", 1000000, "", 14),
              ("시계", "로렉스", "", "", None, None, None)]
_or, _oe = parse_rule_rows(_old_sheet)
ck("옛 엑셀 조건 시트도 읽는다", len(_or) == 3 and not _oe, f"{len(_or)} / {_oe}")
ck("추가키워드는 키워드에 합쳐진다",
   _or[0].keyword == "루이비통 오버 더 문 정품" and _or[0].exclude == ("레플", "미러"),
   f"{_or[0].keyword} / {_or[0].exclude}")
ck("합친 추가키워드가 실제로 걸린다",
   RuleTable(_or).verdict("루이비통 오버더문 정품 급처", 900000)[0] == HIT
   and RuleTable(_or).verdict("루이비통 오버더문 급처", 900000)[0] == CUT)
ck("브랜드는 키워드 첫 어절, 처음 순서로 중복 제거",
   brands(_or) == ["루이비통", "샤넬", "로렉스"], str(brands(_or)))
ck("브랜드별 끌올일수는 가장 느슨한 값",
   brand_days(_or) == {"루이비통": 7, "샤넬": 14}, str(brand_days(_or)))

# 머리글이 1행이라는 보장이 없다 — 제목·빈 줄이 위에 붙은 파일이 흔하다.
_titled = [("루이비통 조건표", None, None), (None, None, None),
           ("키워드", "최소가격", "최대가격"),
           ("루이비통 나노 노에", 800000, 1300000)]
_tr, _te = parse_rule_rows(_titled)
ck("제목·빈 줄이 위에 있어도 머리글을 찾는다",
   len(_tr) == 1 and _tr[0].row == 4, f"{len(_tr)} / {[r.row for r in _tr]} / {_te}")
ck("머리글이 아예 없으면 무엇을 해야 할지 말한다",
   not parse_rule_rows([("품명", "가격"), ("루이비통", 1)])[0]
   and "샘플" in parse_rule_rows([("품명", "가격")])[1][0],
   str(parse_rule_rows([("품명", "가격")])[1]))

# 브랜드는 짐작하지 않는다. '보테가 베네타'·'생 로랑' 처럼 두 어절 브랜드가
# 실제로 있어서, 키워드 첫 어절로 뽑으면 '보테가'·'생' 이 등록된다.
_b5 = [("브랜드", "제품명", "최소가격", "최대가격", "제외"),
       ("루이비통", "오버 더 문", 500000, 1500000, ""),
       ("루이비통", "", 3000000, "", ""),
       ("보테가베네타", "카세트백", 1000000, 2500000, "레플리카, 부속품")]
_br, _be = parse_rule_rows(_b5)
ck("브랜드·제품명 5열 시트", len(_br) == 3 and not _be, f"{len(_br)} / {_be}")
ck("매칭은 브랜드+제품명을 이어 붙인 말로",
   [r.keyword for r in _br]
   == ["루이비통 오버 더 문", "루이비통", "보테가베네타 카세트백"],
   str([r.keyword for r in _br]))
ck("등록 브랜드는 브랜드 열 그대로",
   brands(_br) == ["루이비통", "보테가베네타"], str(brands(_br)))
ck("제품명이 비면 브랜드 전체가 그 가격대로",
   RuleTable(_br).verdict("루이비통 스피디 급처", 3500000)[0] == HIT
   and RuleTable(_br).verdict("루이비통 스피디 급처", 100000)[0] == CUT)
ck("브랜드 열이 없으면 예전처럼 첫 어절로 짐작",
   parse_rule_rows([("키워드", "최소가격"), ("루이비통 나노 노에", 100)])[0][0]
   .brand_name() == "루이비통")
ck("두 어절 브랜드도 제외 구절과 함께 산다",
   _br[2].exclude == ("레플리카", "부속품")
   and RuleTable(_br).verdict("보테가베네타 카세트백 레플리카", 1500000)[0] == CUT
   and RuleTable(_br).verdict("보테가 베네타 카세트백 정품", 1500000)[0] == HIT)

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
       all(hasattr(w, x) for x in ("extraEdit", "excludeEdit")))
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

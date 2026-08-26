"""daangn_ext 로직 스모크 — 네트워크 없이 전 로직 + 토큰갱신 메커니즘 end-to-end."""
import base64, json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))

from daangn_ext import token_manager as T
from daangn_ext.search_filters import KeywordRule, apply_filter
from daangn_ext.account_store import AccountStore
from daangn_ext import auth, rest_scheduler


def make_jwt(code="z", ttl=1800, age=0, typ="access"):
    """실측 형식 HS256 토큰 생성(서명 무의미, exp 디코드용)."""
    now = int(time.time()) - age
    hdr = base64.urlsafe_b64encode(b'{"typ":"JWT","alg":"HS256"}').rstrip(b"=").decode()
    pl = {"iat": now, "exp": now + ttl, "code": code, "type": typ}
    plb = base64.urlsafe_b64encode(json.dumps(pl).encode()).rstrip(b"=").decode()
    return f"{hdr}.{plb}.sig"


# 1) 토큰 디코드 (실측 형식)
acc = ("eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9."
       "eyJpYXQiOjE3ODc0MDUwOTksImV4cCI6MTc4NzQwNjg5OSwiY29kZSI6InoiLCJ0eXBlIjoiYWNjZXNzIn0.s")
p = T._jwt_payload(acc)
assert T.token_code(acc) == "z" and p["exp"] - p["iat"] == 1800
print(f"[1 token] code={T.token_code(acc)} ttl={p['exp']-p['iat']}s OK")

# 2) 키워드 포함필터
class P:
    def __init__(s, name, description): s.name, s.description = name, description
prods = [P("샤넬 클래식 정품 영수증", "풀박스"), P("샤넬 스타일 레플", "미러급"), P("구찌 지갑", "정품")]
rule = KeywordRule(required=["샤넬"], extra=["정품"], extra_mode="and", exclude=["레플", "미러"])
kept = apply_filter(prods, rule)
assert len(kept) == 1 and kept[0].name.startswith("샤넬 클래식")
print(f"[2 filter] {len(prods)}→{len(kept)} OK")

# 3) 계정+프록시 스토어 → TokenManager
store = AccountStore("/tmp/acc_smoke.json")
store.rows = []
store.add_pair(refresh=make_jwt(typ="refresh", ttl=21600), proxy="http://u:p@1.2.3.4:8000", label="010-1")
assert len(store) == 1 and store.proxies() == ["http://u:p@1.2.3.4:8000"]
tm = T.TokenManager()
tm.add_many(store.rows)
assert "z" in tm.accounts
print(f"[3 store] 계정{len(store)} 프록시{store.proxies()} → TM {list(tm.accounts)} OK")

# 4) 토큰 갱신 메커니즘 end-to-end (mock refresh_fn, 네트워크 없음)
refreshed = {"n": 0}
def fake_refresh(a):
    refreshed["n"] += 1
    return make_jwt(code=a.code, ttl=1800), make_jwt(code=a.code, typ="refresh", ttl=21600)
tm2 = T.TokenManager(refresh_fn=fake_refresh, skew=90)
a = tm2.add(refresh=make_jwt(typ="refresh", ttl=21600),
            access=make_jwt(ttl=1800, age=1795))   # 5초 남은 만료임박 access
tok = tm2.ensure(a)                                 # 검색 전 갱신 발동해야
assert refreshed["n"] == 1, "만료임박인데 갱신 안 함"
assert a.expires_in() > 1700, "갱신 후 30분 아님"
tm2.ensure(a)                                       # 방금 갱신됨 → 재갱신 X
assert refreshed["n"] == 1, "불필요 재갱신"
print(f"[4 refresh] 만료임박→자동갱신 1회, 신선하면 skip. expires_in={a.expires_in()}s OK")

# 5) graceful: REFRESH_URL 미설정이어도 크래시 없이 진행
tm3 = T.TokenManager()                               # 기본 refresh=REFRESH_URL(공백)→예외
a3 = tm3.add(refresh=make_jwt(typ="refresh"), access=make_jwt(ttl=1800, age=1795))
safe = tm3.ensure_safe(a3)                           # 예외 삼키고 기존/ None
assert safe == a3.access
res = tm3.refresh_all()                              # 실패 보고하되 크래시 X
assert "fail" in list(res.values())[0]
print(f"[5 graceful] 엔드포인트 공백 → ensure_safe 무크래시, refresh_all={res} OK")

# 6) auth 주입 (대상 호스트만)
h1 = auth.build_headers("https://api.kr.karrotmarket.com/x", "TOK")
h2 = auth.build_headers("https://www.daangn.com/kr/buy-sell/", "TOK")
assert h1.get("authorization") == "Bearer TOK" and "authorization" not in h2
print(f"[6 auth] karrot주입 O / daangn주입 X OK")

# 7) 휴식 랜덤
d = rest_scheduler.sleep_between(0.0, 0.02)
assert 0 <= d <= 0.02
print(f"[7 rest] 랜덤대기 {d:.4f}s OK")

print("\nALL PASS")

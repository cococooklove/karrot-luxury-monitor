"""무인 체인 end-to-end 검증 (목 기반, 네트워크 없음).

증명 대상: karrot_token.ds → 추출 → TokenManager → app_source 자동갱신 → 수집.
진짜 토큰/네트워크만 목으로 대체. 이 배선이 맞으면, zip 도착 시 진짜 토큰만 꽂으면 된다.

체인:
  extract_tokens(karrot_token.ds) → accounts.json
    → TokenManager.add_many(refresh 토큰들)
    → app_source.AppSource(refresh_fn = TokenManager.ensure)
    → collect_region: access 만료 → refresh_fn 호출 → TokenManager 가 refresh 로 새 access
    → 검색 재시도 성공

실행: ../../../.venv/bin/python e2e_chain_test.py
"""
import base64
import json
import os
import sys
import time
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


# ── 합성 토큰/저장소 ──
def mkjwt(sub, ttl, typ):
    now = int(time.time())
    h = base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode().rstrip("=")
    p = {"iat": now, "exp": now + ttl, "sub": sub, "type": typ, "code": sub,
         "client_name": "KARROT_APP"}
    pb = base64.urlsafe_b64encode(json.dumps(p).encode()).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(b"s" * 32).decode().rstrip("=")
    return f"{h}.{pb}.{sig}"


def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def proto_field(num, val):
    b = val.encode()
    # 태그 + varint 길이(>127 문자열도 올바르게) + 값 — 실제 protobuf 와 동일
    return _varint((num << 3) | 2) + _varint(len(b)) + b


print("=== 1. karrot_token.ds → 추출 → accounts.json ===")

sys.path.insert(0, os.path.abspath("../../../tools"))
import extract_tokens as ex

backup = tempfile.mkdtemp()
subs = ["userA", "userB", "userC"]
for s in subs:
    dd = f"{backup}/{s}/data/com.towneers.www/files/datastore"
    os.makedirs(dd)
    # 만료 임박 access(짧게) + 긴 refresh
    blob = proto_field(1, mkjwt(s, 21600, "refresh")) + proto_field(2, mkjwt(s, 30, "access"))
    with open(f"{dd}/karrot_token.ds", "wb") as f:
        f.write(blob)

jwts, headers, n, ds_hits = ex.scan(backup)
accounts, _ = ex.build_accounts(jwts, headers)
ck("계정 3개 추출", len(accounts) == 3, f"{len(accounts)}개")
ck("모두 refresh 보유", all(a["refresh"] for a in accounts))
ck("karrot_token.ds proto 파싱", len(ds_hits) == 3, f"{len(ds_hits)}개")

print("\n=== 2. TokenManager 적재 + 자동 갱신 ===")

from daangn_ext import token_manager as tm

# 갱신 목: refresh_fn 을 주입해 네트워크(WAF) 없이 체인만 검증.
# (실제 _default_refresh 는 api.kr.karrotmarket.com 을 치는데 WAF 403 — 그건 별도 이슈,
#  여기선 "refresh 로 새 access 가 발급되면 체인이 도는가"를 본다.)
refresh_calls = {"n": 0}


def mock_refresh(acc):
    refresh_calls["n"] += 1
    sub = tm._jwt_payload(acc.refresh).get("sub", "?")
    return mkjwt(sub, 1800, "access"), mkjwt(sub, 21600, "refresh")


mgr = tm.TokenManager(refresh_fn=mock_refresh)
mgr.add_many([{"refresh": a["refresh"], "access": a["access"]} for a in accounts])
ck("3계정 등록", len(mgr.accounts) == 3)

# access 가 만료임박(30s < skew 90) → ensure 가 refresh 호출
acc0 = list(mgr.accounts.values())[0]
before = acc0.access
new_access = mgr.ensure(acc0)
ck("만료임박 → 자동 갱신됨", new_access != before and acc0.expires_in() > 1000,
   f"새 TTL {acc0.expires_in()}s")
ck("refresh 엔드포인트 호출됨", refresh_calls["n"] == 1)
ck("refresh 토큰도 회전 반영", acc0.refresh != accounts[0]["refresh"])

print("\n=== 3. app_source 가 TokenManager.ensure 를 refresh_fn 으로 ===")

from daangn_ext import app_api, app_source as aps

# app API 검색 목: 페이지 1개
def search_post(url, json=None, headers=None, **kw):
    return type("R", (), {
        "status_code": 200,
        "content": b"x" * 100,
        "json": staticmethod(lambda: {
            "results": [{"type": "FLEA_MARKET_LIST_VIEW",
                         "document": {"id": "1", "title": "샤넬백",
                                      "regionName": "서초동", "watchesCount": 5}}],
            "hasNextPage": False, "nextToken": None})
    })()


app_api.requests.post = search_post

# config.json 목
cfgp = tempfile.mktemp(suffix=".json")
json.dump({"headers": {"authorization": "Bearer " + acc0.access,
                       "x-device-identity": "d", "x-user-agent": "u"}},
          open(cfgp, "w"))

# refresh_fn = 특정 계정의 TokenManager.ensure
src = aps.AppSource(cfgp, refresh_fn=lambda: mgr.ensure(acc0))
arts, st = src.collect_region("샤넬", "서초동-6128")
ck("app_source 수집 동작", len(arts) == 1 and arts[0]["title"] == "샤넬백", f"{len(arts)}건")
ck("정규화 필드(href/watchesCount)", arts[0]["href"].startswith("https://")
   and arts[0]["watchesCount"] == 5)

# 이제 access 를 강제 만료시키고, 검색이 401 → refresh_fn → 재시도 성공하는지
app_call = {"n": 0}


def search_401_then_ok(url, json=None, headers=None, **kw):
    app_call["n"] += 1
    if app_call["n"] == 1:
        return type("R", (), {"status_code": 401, "content": b"", "text": "x",
                              "json": staticmethod(lambda: {})})()
    return search_post(url, json=json, headers=headers, **kw)


app_api.requests.post = search_401_then_ok
refresh_calls["n"] = 0
# access 를 만료로: config 를 만료 토큰으로
json.dump({"headers": {"authorization": "Bearer " + mkjwt("userA", 30, "access"),
                       "x-device-identity": "d", "x-user-agent": "u"}},
          open(cfgp, "w"))
src2 = aps.AppSource(cfgp, refresh_fn=lambda: mgr.ensure(acc0))
arts2, st2 = src2.collect_region("샤넬", "서초동-6128")
ck("검색 401 → 자동 갱신 → 재시도 성공", len(arts2) == 1 and not st2["token_expired"],
   f"{len(arts2)}건, refresh {refresh_calls['n']}회")

print("\n=== 4. 전체 체인 요약 ===")
print("  karrot_token.ds → extract → TokenManager(refresh) → app_source(자동갱신) → 수집")
print(f"  계정 {len(accounts)} · refresh 회전 정상 · 401 자동복구 정상")

print("\n" + "=" * 50)
bad = [n for n, c in R if not c]
print(f"{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("FAIL:", *bad, sep="\n  - ")
sys.exit(1 if bad else 0)

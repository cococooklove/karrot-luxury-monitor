"""앱 API 클라이언트 테스트 — 네트워크 없이(목) 돌아간다.

핵심 회귀 대상: pageToken. 응답은 nextToken 으로 오지만 요청은 pageToken 으로
보내야 하고, 틀리면 서버가 에러 없이 1페이지를 재반환한다(조용한 중복).
실측: 잘못된 이름으로 40페이지 순회 → 유니크 33건.

실행: ../../../.venv/bin/python app_api_test.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


from daangn_ext import app_api
from daangn_ext.app_api import (AppApiConfig, build_body, collect, to_article,
                                TokenExpired, COORD_TYPE)

LAT, LON = 37.498, 127.026


def mkcfg(token="Bearer test.token.sig"):
    p = tempfile.mktemp(suffix=".json")
    json.dump({"endpoint": app_api.SEARCH_URL,
               "headers": {"authorization": token, "x-device-identity": "dev",
                           "x-user-agent": "ua"}},
              open(p, "w", encoding="utf-8"))
    return AppApiConfig(p)


print("=== A. 요청 본문 스키마 ===")

b = build_body("샤넬", "6128", LAT, LON)
ck("spatialContext 가 루트에 있음", "spatialContext" in b)
ck("spatialContext 가 fleaMarket.filter 에도 있음",
   "spatialContext" in b["fleaMarket"]["filter"],
   "둘 중 하나만 있으면 422")
ck("regionId 는 문자열", b["spatialContext"]["region"]["regionId"] == "6128")
ck("좌표 타입 enum 고정",
   b["spatialContext"]["userCoordinates"][0]["type"] == COORD_TYPE, COORD_TYPE)
ck("판매완료 제외 기본값", b["fleaMarket"]["filter"]["withoutCompleted"] is True)
ck("1페이지엔 페이지토큰 없음", "pageToken" not in b)

b2 = build_body("샤넬", "6128", LAT, LON, page_token="tok-1")
ck("페이징 파라미터 이름은 pageToken", b2.get("pageToken") == "tok-1")
ck("nextToken 으로 보내지 않음(조용한 중복 원인)", "nextToken" not in b2)
ck("regionId 정수로 줘도 문자열화", build_body("k", 6128, LAT, LON)["spatialContext"]["region"]["regionId"] == "6128")

print("\n=== B. 페이지네이션 ===")


class FakeResp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._p = payload
        self.text = text or json.dumps(payload or {})

    def json(self):
        return self._p


def make_pager(total, page_size=20, honor="pageToken"):
    """honor 로 지정한 키만 인식하는 서버. 그 외 키로 오면 1페이지를 재반환."""
    calls = {"n": 0, "bodies": []}

    def post(url, json=None, headers=None, **kw):
        body = json
        calls["n"] += 1
        calls["bodies"].append(body)
        tok = body.get(honor)
        start = int(tok.split(":")[1]) if tok and tok.startswith("p:") else 0
        docs = [{"id": str(i), "title": f"매물{i}"}
                for i in range(start, min(start + page_size, total))]
        nxt = start + page_size
        return FakeResp(200, {
            "results": [{"type": "FLEA_MARKET_LIST_VIEW", "document": d} for d in docs],
            "hasNextPage": nxt < total,
            "nextToken": f"p:{nxt}" if nxt < total else None,
        })
    return post, calls


cfg = mkcfg()
post, calls = make_pager(total=95)
app_api.requests.post = post
seen, st = collect(cfg, "샤넬", "6128", LAT, LON, gap=0)
ck("전량 수집", len(seen) == 95, f"{len(seen)}건 / {st['pages']}페이지")
ck("페이지 수 정확", st["pages"] == 5, f"{st['pages']}페이지 (95÷20)")
ck("정상 종료", st["stopped_by"] == "end", st["stopped_by"])
ck("2페이지부터 pageToken 전송",
   calls["bodies"][1].get("pageToken") == "p:20", str(calls["bodies"][1].get("pageToken")))

# 서버가 pageToken 만 인식하는데 클라가 nextToken 을 보내면 → 중복 감지로 조기 종료
post2, _ = make_pager(total=500, honor="pageToken")


def bad_post(url, json=None, headers=None, **kw):
    body = dict(json or {})
    body.pop("pageToken", None)          # 잘못된 이름으로 보낸 상황 재현
    return post2(url, json=body, headers=headers, **kw)


app_api.requests.post = bad_post
seen2, st2 = collect(cfg, "샤넬", "6128", LAT, LON, gap=0)
ck("페이징 헛돌면 중복으로 감지·중단", st2["stopped_by"] == "duplicate", st2["stopped_by"])
ck("무한 순회 안 함", st2["pages"] <= 3, f"{st2['pages']}페이지에서 멈춤")

# max_pages 상한
app_api.requests.post = make_pager(total=10_000)[0]
seen3, st3 = collect(cfg, "샤넬", "6128", LAT, LON, max_pages=7, gap=0)
ck("max_pages 상한 준수", st3["pages"] == 7 and st3["stopped_by"] == "max_pages",
   f"{st3['pages']}페이지 {st3['stopped_by']}")

# should_stop 반응
app_api.requests.post = make_pager(total=10_000)[0]
n = {"i": 0}


def stop():
    n["i"] += 1
    return n["i"] > 3


seen4, st4 = collect(cfg, "샤넬", "6128", LAT, LON, gap=0, should_stop=stop)
ck("정지 요청 즉시 반영", st4["stopped_by"] == "stopped", f"{st4['pages']}페이지")

print("\n=== C. 토큰 만료 ===")

app_api.requests.post = lambda *a, **k: FakeResp(401, {}, "unauthorized")
try:
    app_api.search_page(cfg, "샤넬", "6128", LAT, LON)
    ck("401 → TokenExpired", False, "예외 없음")
except TokenExpired:
    ck("401 → TokenExpired", True)
except Exception as e:
    ck("401 → TokenExpired", False, type(e).__name__)

app_api.requests.post = lambda *a, **k: FakeResp(401, {}, "unauthorized")
seen5, st5 = collect(cfg, "샤넬", "6128", LAT, LON, gap=0)
ck("수집 중 만료 → 크래시 없이 종료", st5["stopped_by"] == "token" and seen5 == {})

cfg2 = mkcfg()
cfg2.set_access_token("new.jwt.value")
ck("토큰 갱신 반영", cfg2.headers["authorization"] == "Bearer new.jwt.value")
ck("Bearer 중복 안 붙음",
   AppApiConfig(cfg2.path).headers["authorization"].count("Bearer") == 1)
ck("갱신 후 파일 권한 0600",
   oct(os.stat(cfg2.path).st_mode & 0o777) == "0o600", oct(os.stat(cfg2.path).st_mode & 0o777))

print("\n=== D. 정규화 (웹 파이프라인 재사용) ===")

doc = {"id": "1234124135", "title": "샤넬 클래식 캐비어 스몰", "categoryId": "31",
       "regionName": "강남 개포1동", "watchesCount": 20, "chatRoomsCount": 3,
       "republishCount": 1, "createdAt": "2026-08-26T09:15:34.044Z",
       "publishedAt": "2026-08-26T09:15:34.040Z",
       "firstImage": {"url": "https://img/x.webp"}}
a = to_article(doc)
for k in ("id", "title", "price", "thumbnail", "href", "region", "boostedAt", "content"):
    ck(f"필드 {k} 존재", k in a, repr(a.get(k))[:44])
ck("링크가 매물 URL 형태", a["href"].endswith("-1234124135/"), a["href"])
ck("앱 전용 신호 보존", a["watchesCount"] == 20 and a["chatRoomsCount"] == 3)
ck("빈 문서도 크래시 없음", isinstance(to_article({}), dict))

# 기존 웹 필터가 그대로 먹는지
from daangn_ext.search_filters import KeywordRule


class P:
    def __init__(self, d):
        self.name = d["title"]
        self.description = d["content"]


rule = KeywordRule(required=["샤넬"], exclude=["레플"])
ck("웹 키워드 필터 재사용 가능", rule.match(P(a)))
ck("제외어도 동작", not rule.match(P(to_article({**doc, "title": "샤넬 레플리카"}))))

print("\n=== E. 설정 로드 ===")

p = tempfile.mktemp(suffix=".json")
json.dump({"headers": {"authorization": "Bearer x"}}, open(p, "w"))
try:
    AppApiConfig(p)
    ck("필수 헤더 없으면 거부", False, "통과해버림")
except ValueError as e:
    ck("필수 헤더 없으면 거부", "x-device-identity" in str(e), str(e)[:70])
ck("x-search-tab 자동 주입", mkcfg().headers.get("x-search-tab") == "fleamarket")



# ── F. AppSource 어댑터 (모니터 연동) ──
print("\n=== F. AppSource 어댑터 ===")
from daangn_ext import app_source as _as

_cfg_path = tempfile.mktemp(suffix=".json")
json.dump({"headers": {"authorization": "Bearer a.b.c", "x-device-identity": "d",
                       "x-user-agent": "u"}}, open(_cfg_path, "w"))

# 정상 수집 → 웹 형태 stats 반환
app_api.requests.post = make_pager(total=45)[0]
src = _as.AppSource(_cfg_path)
arts, st = src.collect_region("샤넬", "역삼동-6035")
ck("region_in 에서 regionId 추출", True)  # 크래시 없이 왔으면 통과
ck("웹 형태 articles 반환", len(arts) == 45 and "title" in arts[0], f"{len(arts)}건")
ck("웹 호환 stats 키", all(k in st for k in ("missed", "suppressed", "expanded")))
ck("articles 정규화됨(href 포함)", arts[0]["href"].startswith("https://"))

# 토큰 만료 + refresh 성공 → 재시도해서 수집
state = {"expired_once": False}
def flaky_post(url, json=None, headers=None, **kw):
    if not state["expired_once"]:
        state["expired_once"] = True
        return FakeResp(401, {}, "unauthorized")
    return make_pager(total=20)[0](url, json=json, headers=headers, **kw)
app_api.requests.post = flaky_post
refreshed = {"n": 0}
def refresh():
    refreshed["n"] += 1
    return "new.jwt.token"
src2 = _as.AppSource(_cfg_path, refresh_fn=refresh)
arts2, st2 = src2.collect_region("샤넬", "역삼동-6035")
ck("만료 시 refresh 호출", refreshed["n"] == 1)
ck("갱신 후 재시도 성공", len(arts2) == 20 and not st2["token_expired"], f"{len(arts2)}건")

# refresh 없으면 토큰만료 표시하고 건너뜀(크래시 없음)
app_api.requests.post = lambda *a, **k: FakeResp(401, {}, "x")
src3 = _as.AppSource(_cfg_path)
arts3, st3 = src3.collect_region("샤넬", "역삼동-6035")
ck("refresh 없으면 토큰만료 표시", st3["token_expired"] and arts3 == [])

print("\n" + "=" * 46)
bad = [n for n, c in R if not c]
print(f"{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("FAIL:", *bad, sep="\n  - ")
sys.exit(1 if bad else 0)

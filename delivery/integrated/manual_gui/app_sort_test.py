"""앱 API 정렬(sortOption) + 증분 정지 규칙(stop_before) 테스트 — 네트워크 없이(스텁) 돈다.

회귀 대상:
  A. sortOption 이 **정확히 body/fleaMarket 바로 아래**에 실린다.
     루트나 fleaMarket.filter 에 넣으면 서버가 422 도 안 주고 조용히 무시한 200 을 준다
     → '정렬이 걸린 줄 알았는데 관련도' 를 눈으로 못 잡는다. 위치가 곧 계약이다.
  B. 허용값이 아닌 정렬값은 **호출 전에** 걸린다(서버 422 를 기다리지 않는다).
  C. stop_before 가 페이지 **중간**에서 끊고 그 뒤 항목을 담지 않는다.
     RECENT 는 publishedAt 단조 내림차순이라 첫 과거 항목 뒤는 전부 과거다.
  D. RECENT 가 아닌 정렬 + stop_before 는 첫 요청 전에 ValueError.
  E. 인자 미지정 시 요청 본문이 **기존과 바이트 단위로 동일**(기존 수집 무영향).
  F. app_source / adaptive 관통 + 웹크롤 폴백 시 '정지 규칙 못 걸었음' 이 stats 에 남는다.
  G. collect_lanes / collect_nationwide 가 **지역별로 다른** stop_before 를 줄 수 있다.

실행: ../../../.venv/bin/python app_sort_test.py  (또는 python3 app_sort_test.py)
"""
import datetime as dt
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


from daangn_ext import adaptive, app_api, app_source  # noqa: E402
from daangn_ext.app_source import AppSource           # noqa: E402

LAT, LON = 37.498, 127.026
PREFIX = "FLEA_MARKET_SORT_OPTION_"   # 테스트 라벨용 접두어 제거
BASE = dt.datetime(2026, 9, 1, 0, 0, 0, tzinfo=dt.timezone.utc)


def iso(ts: dt.datetime) -> str:
    """서버가 주는 모양 그대로 — 'Z' 접미어 + 밀리초."""
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def mkcfg_path(token="Bearer a.b.c"):
    p = tempfile.mktemp(suffix=".json")
    json.dump({"headers": {"authorization": token, "x-device-identity": "d",
                           "x-user-agent": "u"}}, open(p, "w", encoding="utf-8"))
    return p


class FakeResp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._p = payload
        self.text = text or json.dumps(payload or {})

    def json(self):
        return self._p


def doc_pager(docs, page_size=20):
    """주어진 문서 리스트를 page_size 씩 넘겨주는 가짜 서버 + 요청 본문 기록."""
    calls = {"bodies": [], "n": 0}

    def post(url, json=None, headers=None, **kw):
        calls["n"] += 1
        calls["bodies"].append(json)
        tok = (json or {}).get("pageToken")
        start = int(tok.split(":")[1]) if tok and tok.startswith("p:") else 0
        chunk = docs[start:start + page_size]
        nxt = start + page_size
        return FakeResp(200, {
            "results": [{"type": "FLEA_MARKET_LIST_VIEW", "document": d} for d in chunk],
            "hasNextPage": nxt < len(docs),
            "nextToken": f"p:{nxt}" if nxt < len(docs) else None,
        })
    return post, calls


def recent_docs(n, step_sec=60, base=BASE, missing_at=()):
    """publishedAt 이 step_sec 간격으로 **내림차순**인 문서 n개 (RECENT 응답 모사).

    missing_at 인덱스의 문서는 publishedAt 을 아예 뺀다(서버가 가끔 빠뜨리는 경우).
    """
    out = []
    for i in range(n):
        d = {"id": str(i), "title": f"매물{i}",
             # createdAt 은 일부러 정렬순서와 무관하게 흩뿌린다 —
             # 정지 판단이 createdAt 으로 새면 이 테스트가 깨져야 한다.
             "createdAt": iso(base - dt.timedelta(seconds=(i * 7919) % 100000))}
        if i not in missing_at:
            d["publishedAt"] = iso(base - dt.timedelta(seconds=i * step_sec))
        out.append(d)
    return out


CFG = mkcfg_path()
_ORIG_POST = app_api.requests.post

print("=== A. sortOption 이 body/fleaMarket 바로 아래에 실린다 ===")

b = app_api.build_body("샤넬", "6035", LAT, LON, sort_option=app_api.SORT_RECENT)
ck("fleaMarket.sortOption 에 있다", b["fleaMarket"].get("sortOption") == app_api.SORT_RECENT,
   str(b["fleaMarket"].get("sortOption")))
ck("루트에는 없다", "sortOption" not in b)
ck("fleaMarket.filter 에는 없다", "sortOption" not in b["fleaMarket"]["filter"])
ck("전송값은 full enum 문자열",
   b["fleaMarket"]["sortOption"] == "FLEA_MARKET_SORT_OPTION_RECENT")
# 본문 전체에서 sortOption 이 등장하는 자리가 딱 하나여야 한다(어딘가에 중복 삽입 금지)
ck("본문 안에 sortOption 은 딱 한 곳", json.dumps(b).count("sortOption") == 1)

ck("허용값 6개가 모듈 상수로 있다", len(app_api.SORT_OPTIONS) == 6
   and set(app_api.SORT_OPTIONS) == {
       "FLEA_MARKET_SORT_OPTION_UNSPECIFIED", "FLEA_MARKET_SORT_OPTION_RELEVANT",
       "FLEA_MARKET_SORT_OPTION_PRICE_ASC", "FLEA_MARKET_SORT_OPTION_PRICE_DESC",
       "FLEA_MARKET_SORT_OPTION_DISTANCE_ASC", "FLEA_MARKET_SORT_OPTION_RECENT"})
ck("짧은 상수 이름으로 접근된다",
   (app_api.SORT_RECENT, app_api.SORT_RELEVANT, app_api.SORT_PRICE_ASC,
    app_api.SORT_PRICE_DESC, app_api.SORT_DISTANCE_ASC, app_api.SORT_UNSPECIFIED)
   == tuple(sorted(app_api.SORT_OPTIONS, key=lambda v: {
       "FLEA_MARKET_SORT_OPTION_RECENT": 0, "FLEA_MARKET_SORT_OPTION_RELEVANT": 1,
       "FLEA_MARKET_SORT_OPTION_PRICE_ASC": 2, "FLEA_MARKET_SORT_OPTION_PRICE_DESC": 3,
       "FLEA_MARKET_SORT_OPTION_DISTANCE_ASC": 4,
       "FLEA_MARKET_SORT_OPTION_UNSPECIFIED": 5}[v])))

# 모든 허용값이 실제로 통과하는지
for v in app_api.SORT_OPTIONS:
    bb = app_api.build_body("k", "1", LAT, LON, sort_option=v)
    ck(f"허용값 통과: {v.replace(PREFIX, '')}", bb["fleaMarket"]["sortOption"] == v)

# search_page / collect 관통 — 실제 나간 본문에서 확인
post, calls = doc_pager(recent_docs(5))
app_api.requests.post = post
cfg = app_api.AppApiConfig(CFG)
app_api.search_page(cfg, "샤넬", "6035", LAT, LON, sort_option=app_api.SORT_PRICE_ASC)
ck("search_page 가 sortOption 을 실어보낸다",
   calls["bodies"][0]["fleaMarket"].get("sortOption") == app_api.SORT_PRICE_ASC)

post, calls = doc_pager(recent_docs(45))
app_api.requests.post = post
app_api.collect(cfg, "샤넬", "6035", LAT, LON, gap=0, sort_option=app_api.SORT_RECENT)
ck("collect 가 전 페이지에 sortOption 을 유지",
   calls["n"] == 3 and all(bd["fleaMarket"].get("sortOption") == app_api.SORT_RECENT
                           for bd in calls["bodies"]),
   f"{calls['n']}요청")

print("\n=== B. 잘못된 정렬값은 호출 전에 걸린다(서버 422 대기 없음) ===")

for bad in ("RECENT", "recent", "FLEA_MARKET_SORT_OPTION_NEWEST", "", 0, "PRICE_ASC"):
    post, calls = doc_pager(recent_docs(5))
    app_api.requests.post = post
    try:
        app_api.build_body("k", "1", LAT, LON, sort_option=bad)
        ok = False
    except ValueError:
        ok = True
    ck(f"build_body 가 {bad!r} 를 거부", ok and calls["n"] == 0, f"요청 {calls['n']}회")

post, calls = doc_pager(recent_docs(5))
app_api.requests.post = post
try:
    app_api.collect(cfg, "k", "1", LAT, LON, gap=0, sort_option="RECENT")
    ok = False
except ValueError:
    ok = True
ck("collect 도 요청 0회로 거부", ok and calls["n"] == 0, f"요청 {calls['n']}회")

post, calls = doc_pager(recent_docs(5))
app_api.requests.post = post
try:
    app_api.search_page(cfg, "k", "1", LAT, LON, sort_option="nope")
    ok = False
except ValueError:
    ok = True
ck("search_page 도 요청 0회로 거부", ok and calls["n"] == 0, f"요청 {calls['n']}회")

print("\n=== C. stop_before 가 페이지 중간에서 끊는다 ===")

SLACK = app_api.STOP_BEFORE_SLACK
ck("STOP_BEFORE_SLACK 이 양수 초로 정의됨", isinstance(SLACK, (int, float)) and SLACK > 0,
   f"{SLACK}s")

# 60초 간격 × 60건. stop_before = i=10 의 시각 → 여유 300초 = 5건 더 받고 i=16 에서 끊긴다.
DOCS = recent_docs(60, step_sec=60)
STOP_AT = 10
cut = STOP_AT + int(SLACK // 60) + 1          # 여유를 포함해 처음으로 버려지는 인덱스
post, calls = doc_pager(DOCS)
app_api.requests.post = post
seen, st = app_api.collect(cfg, "샤넬", "6035", LAT, LON, gap=0,
                           sort_option=app_api.SORT_RECENT,
                           stop_before=DOCS[STOP_AT]["publishedAt"])
ck("stopped_by == 'stop_before'", st["stopped_by"] == "stop_before", st["stopped_by"])
ck("끊긴 지점까지만 담는다", len(seen) == cut, f"{len(seen)}건 (기대 {cut})")
ck("끊긴 항목과 그 뒤는 안 담긴다",
   all(str(i) not in seen for i in range(cut, 60)) and str(cut - 1) in seen)
ck("페이지 중간에서 끊긴다(같은 페이지 뒷부분도 버림)",
   calls["n"] == 1 and cut < 20, f"요청 {calls['n']}회 / cut={cut}")
ck("여유(STOP_BEFORE_SLACK)만큼 더 받는다 — 정확히 stop_before 에서 끊지 않는다",
   len(seen) > STOP_AT + 1, f"{len(seen)} > {STOP_AT + 1}")

# 2페이지째 중간에서 끊기는 경우 — 3페이지를 요청하지 않아야 한다
STOP_AT2 = 25
cut2 = STOP_AT2 + int(SLACK // 60) + 1
post, calls = doc_pager(DOCS)
app_api.requests.post = post
seen2, st2 = app_api.collect(cfg, "샤넬", "6035", LAT, LON, gap=0,
                             sort_option=app_api.SORT_RECENT,
                             stop_before=DOCS[STOP_AT2]["publishedAt"])
ck("2페이지 중간에서 끊고 3페이지는 안 부른다",
   calls["n"] == 2 and st2["stopped_by"] == "stop_before" and len(seen2) == cut2,
   f"{calls['n']}요청 / {len(seen2)}건 (기대 {cut2})")
ck("pages 는 실제 요청 수와 같다", st2["pages"] == 2 and st2["requests"] == 2)

# datetime / epoch 입력도 같은 결과 (호출측이 형변환하다 조용히 틀리지 않게)
for label, val in (
        ("datetime", BASE - dt.timedelta(seconds=STOP_AT * 60)),
        ("epoch", (BASE - dt.timedelta(seconds=STOP_AT * 60)).timestamp())):
    post, _c = doc_pager(DOCS)
    app_api.requests.post = post
    s3, _st3 = app_api.collect(cfg, "샤넬", "6035", LAT, LON, gap=0,
                               sort_option=app_api.SORT_RECENT, stop_before=val)
    ck(f"stop_before 를 {label} 로 줘도 결과 동일", len(s3) == cut, f"{len(s3)}건")

# 읽을 수 없는 stop_before → 요청 0회로 실패(조용히 '정지 없음' 으로 퇴화 금지)
post, calls = doc_pager(DOCS)
app_api.requests.post = post
try:
    app_api.collect(cfg, "k", "1", LAT, LON, gap=0,
                    sort_option=app_api.SORT_RECENT, stop_before="어제")
    ok = False
except ValueError:
    ok = True
ck("파싱 불가 stop_before 는 요청 전에 실패", ok and calls["n"] == 0, f"요청 {calls['n']}회")

# 전부 최신이라 안 끊기는 경우 → 종전대로 끝까지
post, calls = doc_pager(DOCS)
app_api.requests.post = post
seen4, st4 = app_api.collect(cfg, "샤넬", "6035", LAT, LON, gap=0,
                             sort_option=app_api.SORT_RECENT,
                             stop_before=BASE - dt.timedelta(days=30))
ck("정지 조건에 안 걸리면 종전대로 전량", len(seen4) == 60 and st4["stopped_by"] == "end",
   f"{len(seen4)}건 / {st4['stopped_by']}")

print("\n=== C-2. publishedAt 없는 문서: 버리지도, 끊지도 않는다 ===")

MISS = {3, 7}
DOCS_M = recent_docs(60, step_sec=60, missing_at=MISS)
post, calls = doc_pager(DOCS_M)
app_api.requests.post = post
seen5, st5 = app_api.collect(cfg, "샤넬", "6035", LAT, LON, gap=0,
                             sort_option=app_api.SORT_RECENT,
                             stop_before=DOCS_M[STOP_AT]["publishedAt"])
ck("publishedAt 없는 문서도 담긴다(버리면 유실)",
   all(str(i) in seen5 for i in MISS), f"{sorted(MISS)}")
ck("publishedAt 없는 문서가 정지를 유발하지 않는다", len(seen5) == cut,
   f"{len(seen5)}건 (기대 {cut})")

# createdAt 으로 새면 안 된다 — createdAt 은 정렬순서와 무관하게 흩어져 있으므로
# createdAt 을 보면 훨씬 이른 인덱스에서 끊긴다.
ck("정지 판단이 createdAt 으로 새지 않는다", len(seen5) == cut and str(cut - 1) in seen5)

print("\n=== D. RECENT 가 아닌 정렬 + stop_before 는 첫 요청 전에 실패 ===")

for so in (None, app_api.SORT_RELEVANT, app_api.SORT_PRICE_ASC,
           app_api.SORT_DISTANCE_ASC, app_api.SORT_UNSPECIFIED):
    post, calls = doc_pager(DOCS)
    app_api.requests.post = post
    try:
        app_api.collect(cfg, "샤넬", "6035", LAT, LON, gap=0,
                        sort_option=so, stop_before=DOCS[10]["publishedAt"])
        ok = False
    except ValueError:
        ok = True
    ck(f"sort_option={so and so.replace(PREFIX, '')} + stop_before → ValueError, 요청 0회",
       ok and calls["n"] == 0, f"요청 {calls['n']}회")

print("\n=== E. 인자 미지정 시 요청 본문이 기존과 바이트 단위로 동일 ===")

SPATIAL = {"region": {"regionId": "6035"},
           "userCoordinates": [{"type": app_api.COORD_TYPE,
                                "coordinate": {"latitude": LAT, "longitude": LON}}]}
GOLDEN = {                       # 이번 변경 이전의 본문 (하드코딩 = 회귀 기준선)
    "query": "샤넬",
    "fleaMarket": {"filter": {"withoutCompleted": True, "spatialContext": SPATIAL}},
    "spatialContext": SPATIAL,
}
GOLDEN_PAGED = dict(GOLDEN, pageToken="p:20")

got = app_api.build_body("샤넬", "6035", LAT, LON)
ck("build_body() 본문이 기존과 완전히 동일(키 순서 포함)",
   json.dumps(got, ensure_ascii=False) == json.dumps(GOLDEN, ensure_ascii=False),
   json.dumps(got, ensure_ascii=False)[:120])
got_p = app_api.build_body("샤넬", "6035", LAT, LON, page_token="p:20")
ck("pageToken 있는 본문도 기존과 동일",
   json.dumps(got_p, ensure_ascii=False) == json.dumps(GOLDEN_PAGED, ensure_ascii=False))
ck("sort_option=None 이면 sortOption 키 자체가 없다", "sortOption" not in json.dumps(got))

post, calls = doc_pager(recent_docs(45))
app_api.requests.post = post
seen6, st6 = app_api.collect(cfg, "샤넬", "6035", LAT, LON, gap=0)
ck("collect 기본 호출의 모든 본문이 기존과 동일",
   all(json.dumps(bd, ensure_ascii=False)
       == json.dumps(dict(GOLDEN, **({"pageToken": bd["pageToken"]}
                                     if "pageToken" in bd else {})),
                     ensure_ascii=False)
       for bd in calls["bodies"]))
ck("기본 호출 결과·stats 가 종전 그대로",
   len(seen6) == 45 and st6["stopped_by"] == "end" and st6["pages"] == 3
   and st6["sort_option"] is None)

print("\n=== F. app_source / adaptive 관통 ===")

import inspect  # noqa: E402
for fn in (app_api.build_body, app_api.search_page, app_api.collect):
    ck(f"app_api.{fn.__name__}() 에 sort_option 인자", "sort_option" in inspect.signature(fn).parameters)
ck("app_api.collect() 에 stop_before 인자", "stop_before" in inspect.signature(app_api.collect).parameters)
for fn in (AppSource.collect_region, adaptive.collect_region,
           adaptive.collect_lanes, adaptive.collect_nationwide):
    p = inspect.signature(fn).parameters
    ck(f"{fn.__qualname__} 에 sort_option/stop_before 인자",
       "sort_option" in p and "stop_before" in p)

post, calls = doc_pager(DOCS)
app_api.requests.post = post
arts, st = AppSource(CFG).collect_region(
    "샤넬", "역삼동-6035", sort_option=app_api.SORT_RECENT,
    stop_before=DOCS[STOP_AT]["publishedAt"])
ck("AppSource 가 sortOption 을 실제 요청에 실는다",
   calls["bodies"][0]["fleaMarket"].get("sortOption") == app_api.SORT_RECENT)
ck("AppSource 가 stop_before 로 끊는다",
   len(arts) == cut and st["stopped_by"] == "stop_before", f"{len(arts)}건")
ck("AppSource stats 에 정렬·정지 사실이 남는다",
   st.get("sort_option") == app_api.SORT_RECENT and st.get("stopped_by_stop_before") is True)

# adaptive 앱 분기 관통 — _app_source_for 를 스텁으로 갈아 kwargs 를 잡는다
_orig_app_for = adaptive._app_source_for
_orig_web = adaptive.robust_fetch_articles
SEEN_KW = []


class FakeSrc:
    def collect_region(self, keyword, region_in, **kw):
        SEEN_KW.append(dict(kw, _region=region_in))
        return [], {"requests": 1, "pages": 1, "stopped_by": "stop_before",
                    "saturated": False, "splits": 0, "missed": [], "suppressed": 0,
                    "expanded": [], "empties": 0}


adaptive._app_source_for = lambda _tok: FakeSrc()
SEEN_KW.clear()
adaptive.collect_region("샤넬", "역삼동-6035", access_token="t",
                        sort_option=app_api.SORT_RECENT, stop_before="2026-09-01T00:00:00Z")
ck("adaptive → AppSource 로 sort_option/stop_before 관통",
   SEEN_KW and SEEN_KW[0].get("sort_option") == app_api.SORT_RECENT
   and SEEN_KW[0].get("stop_before") == "2026-09-01T00:00:00Z", str(SEEN_KW[:1]))

SEEN_KW.clear()
adaptive.collect_region("샤넬", "역삼동-6035", access_token="t")
ck("인자 미지정이면 앱 분기에도 None 으로 간다(종전 동작)",
   SEEN_KW[0].get("sort_option") is None and SEEN_KW[0].get("stop_before") is None)

print("\n=== F-2. 웹크롤 폴백이면 '정지 규칙 못 걸었음' 이 stats 에 남는다 ===")

WEB = {"n": 0}


def fake_web(kw, region_in, **k):
    WEB["n"] += 1
    return [{"id": f"w{WEB['n']}", "title": "웹"}], {"empties": 0}


adaptive.robust_fetch_articles = fake_web
adaptive.set_app_fallback_logger(lambda _m: None)
adaptive.reset_app_fallback_notices()


def boom(_tok):
    raise app_api.AppApiError("HTTP 403", status=403)


adaptive._app_source_for = boom
arts, st = adaptive.collect_region("샤넬", "역삼동-6035", access_token="t",
                                   sort_option=app_api.SORT_RECENT,
                                   stop_before="2026-09-01T00:00:00Z")
ck("폴백 stats 에 app_api_failed 와 stop_before_unapplied 가 같이 남는다",
   st.get("app_api_failed") and st.get("stop_before_unapplied") == "2026-09-01T00:00:00Z",
   str(st.get("stop_before_unapplied")))
ck("정렬 요청도 못 걸었음이 남는다",
   st.get("sort_option_unapplied") == app_api.SORT_RECENT)

# 토큰이 아예 없어 앱 분기를 못 탄 경우도 같은 표시가 있어야 한다
arts, st = adaptive.collect_region("샤넬", "역삼동-6035",
                                   sort_option=app_api.SORT_RECENT,
                                   stop_before="2026-09-01T00:00:00Z")
ck("토큰 없이 웹만 탄 경우에도 stop_before_unapplied 가 남는다",
   st.get("stop_before_unapplied") == "2026-09-01T00:00:00Z"
   and "app_api_failed" not in st)

# 정지 규칙을 요청하지 않았으면 키가 생기지 않는다(기존 stats 모양 유지)
arts, st = adaptive.collect_region("샤넬", "역삼동-6035")
ck("요청 안 했으면 키가 안 생긴다",
   "stop_before_unapplied" not in st and "sort_option_unapplied" not in st)

print("\n=== G. 지역별 stop_before (collect_lanes / collect_nationwide) ===")

adaptive._app_source_for = lambda _tok: FakeSrc()
REGIONS = [
    {"in": "동A-1", "stop_before": "2026-09-01T01:00:00Z"},
    {"in": "동B-2", "stop_before": "2026-09-01T02:00:00Z"},
    {"in": "동C-3"},                                   # 키 없음 → 함수 기본값
    {"in": "동D-4", "stop_before": None},              # 키 있고 None → '이 지역만 정지 없음'
]

for label, run in (
    ("collect_lanes",
     lambda: adaptive.collect_lanes("샤넬", REGIONS, proxies=None, access_token="t",
                                    rest_range=None, sort_option=app_api.SORT_RECENT,
                                    stop_before="2026-09-01T09:00:00Z")),
    ("collect_nationwide",
     lambda: adaptive.collect_nationwide("샤넬", REGIONS, access_token="t",
                                         rest_range=None, sort_option=app_api.SORT_RECENT,
                                         stop_before="2026-09-01T09:00:00Z")),
):
    SEEN_KW.clear()
    run()
    got = {k["_region"]: k.get("stop_before") for k in SEEN_KW}
    ck(f"{label}: 지역마다 다른 stop_before 가 짝이 맞게 전달된다",
       got == {"동A-1": "2026-09-01T01:00:00Z", "동B-2": "2026-09-01T02:00:00Z",
               "동C-3": "2026-09-01T09:00:00Z", "동D-4": None}, str(got))
    ck(f"{label}: sort_option 은 함수 기본값이 전 지역에 적용",
       all(k.get("sort_option") == app_api.SORT_RECENT for k in SEEN_KW))

# 인자를 안 주면 종전과 같이 전 지역 None
SEEN_KW.clear()
adaptive.collect_lanes("샤넬", [{"in": "동A-1"}, {"in": "동B-2"}], proxies=None,
                       access_token="t", rest_range=None)
ck("collect_lanes 인자 미지정 = 전 지역 None(종전 동작)",
   all(k.get("sort_option") is None and k.get("stop_before") is None for k in SEEN_KW)
   and len(SEEN_KW) == 2)

# 요약에 '정지 못 건 지역 수' 가 집계된다
adaptive._app_source_for = boom
adaptive.reset_app_fallback_notices()
_arts, summary = adaptive.collect_lanes(
    "샤넬", [{"in": "동A-1"}, {"in": "동B-2"}], proxies=None, access_token="t",
    rest_range=None, sort_option=app_api.SORT_RECENT, stop_before="2026-09-01T00:00:00Z")
ck("collect_lanes 요약에 stop_before_unapplied_regions 집계",
   summary.get("stop_before_unapplied_regions") == 2,
   str(summary.get("stop_before_unapplied_regions")))
adaptive.reset_app_fallback_notices()
_arts, summary = adaptive.collect_nationwide(
    "샤넬", [{"in": "동A-1"}], access_token="t", rest_range=None,
    sort_option=app_api.SORT_RECENT, stop_before="2026-09-01T00:00:00Z")
ck("collect_nationwide 요약에도 집계",
   summary.get("stop_before_unapplied_regions") == 1)

adaptive._app_source_for = _orig_app_for
adaptive.robust_fetch_articles = _orig_web
adaptive.set_app_fallback_logger(None)
adaptive.reset_app_fallback_notices()
app_api.requests.post = _ORIG_POST

print("\n" + "=" * 46)
bad = [n for n, c in R if not c]
print(f"{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("FAIL:", *bad, sep="\n  - ")
sys.exit(1 if bad else 0)

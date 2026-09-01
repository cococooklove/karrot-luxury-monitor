"""앱 API 프록시 주입 + 앱API→웹크롤 폴백 가시성 테스트 — 네트워크 없이(목) 돌아간다.

회귀 대상 두 가지:
  A. 앱 API(search-bff) 요청이 프록시를 탄다. 예전엔 AppSource.collect_region 이
     proxies 를 받고 버려서 운영 서버(미국 IP)의 모든 검색이 직결로 나갔다.
  B. 앱 API 실패 시 웹크롤 폴백이 '조용하지' 않다. 웹크롤은 명품 브랜드를 억제하므로
     ('샤넬' 0건 vs 앱API 1,000건+) 조용한 폴백은 장애를 '매물 없음'으로 위장한다.

실행: ../../../.venv/bin/python app_proxy_test.py
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


from daangn_ext import adaptive, app_api, app_source, proxy_budget
from daangn_ext.app_source import AppSource

LAT, LON = 37.498, 127.026


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


def spy_pager(total=45, page_size=20):
    """페이징하는 가짜 서버 + 매 요청의 proxy 인자를 기록한다."""
    calls = {"proxies": [], "n": 0}

    def post(url, json=None, headers=None, **kw):
        calls["n"] += 1
        calls["proxies"].append(kw.get("proxy"))
        tok = (json or {}).get("pageToken")
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


CFG = mkcfg_path()

print("=== A. app_api 요청 경로가 프록시를 받는다 ===")

# 설치본 시그니처 확인 — 추측 금지. curl_cffi 0.16 은 proxy(str)/proxies(dict) 둘 다 받는다.
# 이 저장소는 robust.py 가 sess.get(..., proxy=cur_proxy) 로 단수형을 쓰므로 그쪽에 맞춘다.
import inspect
from curl_cffi.requests import Session as _CSession
_sig = inspect.signature(_CSession.request).parameters
ck("curl_cffi 가 proxy(단수) 를 받는다", "proxy" in _sig, "robust.py 와 같은 인자명")

for fn, want in ((app_api._post, "proxy"), (app_api.search_page, "proxy"),
                 (app_api.collect, "proxy")):
    ck(f"{fn.__name__}() 에 proxy 인자 있음", want in inspect.signature(fn).parameters)

post, calls = spy_pager(total=45)
app_api.requests.post = post
cfg = app_api.AppApiConfig(CFG)
seen, st = app_api.collect(cfg, "샤넬", "6035", LAT, LON, gap=0,
                           proxy="http://ip-a:1")
ck("전 페이지가 지정 프록시로 나감",
   calls["n"] == 3 and set(calls["proxies"]) == {"http://ip-a:1"},
   f"{calls['n']}요청 / {set(calls['proxies'])}")
ck("stats 에 사용 프록시 기록", st.get("proxy") == "http://ip-a:1")

post, calls = spy_pager(total=5)
app_api.requests.post = post
app_api.collect(cfg, "샤넬", "6035", LAT, LON, gap=0)
ck("proxy 미지정이면 직결(None) — 예외 없음", calls["proxies"] == [None], str(calls["proxies"]))

print("\n=== B. AppSource.collect_region 이 proxies 를 실제로 쓴다 ===")

proxy_budget.reset()
POOL = ["http://p1:1", "http://p2:2", "http://p3:3"]

post, calls = spy_pager(total=45)
app_api.requests.post = post
src = AppSource(CFG)
arts, st = src.collect_region("샤넬", "역삼동-6035", proxies=POOL)
used = set(calls["proxies"])
ck("풀에서 고른 IP 로 요청", used <= set(POOL) and len(used) == 1, str(used))
ck("한 지역 안에서는 IP 고정", len(used) == 1 and calls["n"] == 3, f"{calls['n']}요청")
ck("stats.proxy 가 실제 사용 IP 와 일치", st.get("proxy") in used, str(st.get("proxy")))
ck("수집 결과는 그대로", len(arts) == 45)

# 쿨다운 규칙을 따르는지 — 웹 경로(proxy_budget.pick) 와 같은 선택 규칙이어야 한다
proxy_budget.reset()
proxy_budget.mark_exhausted("http://p1:1", 60)
proxy_budget.mark_exhausted("http://p2:2", 60)
post, calls = spy_pager(total=5)
app_api.requests.post = post
AppSource(CFG).collect_region("샤넬", "역삼동-6035", proxies=POOL)
ck("쿨다운 중인 IP 는 피한다(proxy_budget.pick 규칙)",
   calls["proxies"] == ["http://p3:3"], str(calls["proxies"]))
proxy_budget.reset()

# 명시 proxy 가 풀보다 우선(웹 경로 `proxy or pick(proxies)` 와 동일)
post, calls = spy_pager(total=5)
app_api.requests.post = post
AppSource(CFG).collect_region("샤넬", "역삼동-6035", proxy="http://fixed:9", proxies=POOL)
ck("명시 proxy 가 풀보다 우선", calls["proxies"] == ["http://fixed:9"], str(calls["proxies"]))

# 프록시 없음 → 직결, 예외 없음
for empty in (None, []):
    post, calls = spy_pager(total=5)
    app_api.requests.post = post
    a, s = AppSource(CFG).collect_region("샤넬", "역삼동-6035", proxies=empty)
    ck(f"proxies={empty!r} 이면 직결(예외 없음)",
       calls["proxies"] == [None] and len(a) == 5 and s.get("proxy") is None)

print("\n=== C. 앱 stats 가 웹 stats 와 키 호환 (레인 KeyError 회귀) ===")

post, _ = spy_pager(total=5)
app_api.requests.post = post
_, st = AppSource(CFG).collect_region("샤넬", "역삼동-6035")
for k in ("requests", "saturated", "splits", "missed", "suppressed", "expanded", "empties"):
    ck(f"앱 stats 에 '{k}' 있음", k in st,
       "없으면 collect_lanes 의 st['saturated'] 가 레인을 죽인다" if k == "saturated" else "")

print("\n=== D. adaptive 앱분기가 proxies 를 그대로 넘긴다 ===")


class SpySource:
    def __init__(self):
        self.kw = None

    def collect_region(self, keyword, region_in, **kw):
        self.kw = kw
        return [{"id": "1", "title": "x"}], {"requests": 1, "saturated": False,
                                             "splits": 0, "missed": [],
                                             "suppressed": 0, "expanded": [],
                                             "empties": 0}


spy = SpySource()
_orig_app_for = adaptive._app_source_for
adaptive._app_source_for = lambda tok: spy
arts, st = adaptive.collect_region("샤넬", "역삼동-6035", access_token="t",
                                   proxies=POOL, proxy="http://fixed:9")
ck("adaptive → AppSource 로 proxies 전달", spy.kw.get("proxies") == POOL, str(spy.kw.get("proxies")))
ck("adaptive → AppSource 로 proxy 전달", spy.kw.get("proxy") == "http://fixed:9")
ck("앱분기 성공 시 폴백 표시 없음", "app_api_failed" not in st)

print("\n=== E. 앱API 실패가 조용하지 않다 ===")

LOG = []
adaptive.set_app_fallback_logger(LOG.append)
adaptive.reset_app_fallback_notices()


def boom(_tok):
    raise RuntimeError("요청 실패: HTTP 503")


adaptive._app_source_for = boom

WEB = {"n": 0}


def fake_web(keyword, region_in, **kw):
    WEB["n"] += 1
    return [{"id": f"w{WEB['n']}", "title": "웹매물"}], {"empties": 0}


_orig_web = adaptive.robust_fetch_articles
adaptive.robust_fetch_articles = fake_web

arts, st = adaptive.collect_region("샤넬", "역삼동-6035", access_token="t", proxies=POOL)
ck("폴백은 유지된다(안전망)", WEB["n"] > 0 and len(arts) >= 1, f"웹 {WEB['n']}회 호출")
ck("stats 에 app_api_failed 실림", "app_api_failed" in st, str(st.get("app_api_failed")))
ck("예외 종류·메시지가 요약에 담김",
   "RuntimeError" in str(st.get("app_api_failed")) and "503" in str(st.get("app_api_failed")),
   str(st.get("app_api_failed")))
ck("로그로도 나간다", any("앱API" in m for m in LOG), LOG[0][:70] if LOG else "(없음)")
ck("첫 경고는 눈에 띄게(⚠️)", any(m.startswith("⚠️") for m in LOG))
ck("웹크롤 억제 위험을 로그가 알린다", any("억제" in m for m in LOG))

# 토큰 없으면(앱API 시도 자체 없음) 폴백 표시도 없어야 한다 — 오탐 방지
_, st_noauth = adaptive.collect_region("샤넬", "역삼동-6035", proxies=POOL)
ck("토큰 없으면 app_api_failed 없음(오탐 방지)", "app_api_failed" not in st_noauth)

print("\n=== F. 폴백이 상위 요약(collect_lanes)까지 올라온다 ===")

adaptive.reset_app_fallback_notices()
LOG.clear()
regions = [{"in": f"동{i}-{i}"} for i in range(4)]
seen_stats = []
_, summary = adaptive.collect_lanes(
    "샤넬", regions, proxies=POOL, lanes=2, access_token="t",
    rest_range=None, on_result=lambda r, a, s: seen_stats.append(s))
ck("지역별 stats 에 키가 살아서 on_result 로 온다",
   len(seen_stats) == 4 and all("app_api_failed" in s for s in seen_stats),
   f"{len(seen_stats)}개 지역")
ck("레인 요약이 폴백 지역 수를 센다", summary.get("app_api_fallbacks") == 4,
   str(summary.get("app_api_fallbacks")))
ck("레인 요약에 마지막 예외 요약", "RuntimeError" in str(summary.get("app_api_failed")))
ck("같은 예외 반복은 1회만 크게 경고",
   sum(1 for m in LOG if m.startswith("⚠️")) == 1, f"⚠️ {sum(1 for m in LOG if m.startswith('⚠️'))}건 / 총 {len(LOG)}줄")

# 앱API 정상일 때는 요약이 깨끗해야 한다(레인 KeyError 회귀 포함)
adaptive._app_source_for = lambda tok: SpySource()
_, summary_ok = adaptive.collect_lanes(
    "샤넬", regions, proxies=POOL, lanes=2, access_token="t", rest_range=None)
ck("앱API 정상이면 폴백 0 (레인 KeyError 없음)",
   summary_ok.get("app_api_fallbacks") == 0 and summary_ok["regions"] == 4,
   str(summary_ok.get("app_api_fallbacks")))

adaptive._app_source_for = _orig_app_for
adaptive.robust_fetch_articles = _orig_web
adaptive.set_app_fallback_logger(None)

print("\n=== G. sweep_engine 배선 ===")

import daangn.sweep_engine as se
ck("sweep_engine 이 폴백 로거를 임포트", hasattr(se, "set_app_fallback_logger"))
_src = inspect.getsource(se.SweepEngine.run)
ck("run() 이 _log 를 폴백 로거로 등록", "set_app_fallback_logger(self._log)" in _src)
ck("사이클마다 경고 재알림", "reset_app_fallback_notices()" in _src)
# 전역 로거를 걸고 안 되돌리면, GUI 가 AutoMonitor 를 버린 뒤에도 죽은 수신자를
# 물고 있어 경고가 stderr 폴백조차 못 타고 사라진다.
ck("스윕이 끝나면 이전 로거로 복원", "set_app_fallback_logger(_prev_fallback_log)" in _src)
_probe = lambda m: None                      # noqa: E731
adaptive.set_app_fallback_logger(_probe)
ck("get_app_fallback_logger 로 현재 로거를 읽어 왕복 복원 가능",
   adaptive.get_app_fallback_logger() is _probe)
adaptive.set_app_fallback_logger(None)
ck("None 도 그대로 왕복", adaptive.get_app_fallback_logger() is None)
ck("레인 요약의 app_api_fallbacks 를 운영자에게 표시",
   'lsm.get("app_api_fallbacks")' in _src)

print("\n=== H. 죽은 IP 로 실패하면 쿨다운 + 다른 IP 로 1회 재시도(결함3) ===")

# 배경: 웹 경로는 robust.py:190 에서 실패 IP 에 mark_exhausted 를 걸고
# adaptive.collect_region 의 exhausted 분기(:190)가 pick(exclude=) 로 갈아탄 뒤
# 1회 더 시도한다. 앱 경로에 그게 없으면 stabilize(레인당 고정 IP 1개)에서
# 그 IP 가 죽는 순간 사이클 전 지역이 웹크롤(명품 억제)로 떨어진다.

DEAD = "http://dead:1"
ALIVE = ["http://ok1:1", "http://ok2:2"]


def dead_ip_pager(dead, total=25, page_size=20):
    """dead 프록시로 오는 요청만 403 으로 막는 가짜 서버."""
    calls = {"proxies": [], "n": 0}

    def post(url, json=None, headers=None, **kw):
        calls["n"] += 1
        p = kw.get("proxy")
        calls["proxies"].append(p)
        if p == dead:
            return FakeResp(403, {}, text="blocked by upstream " + str(p))
        tok = (json or {}).get("pageToken")
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


proxy_budget.reset()
post, calls = dead_ip_pager(DEAD)
app_api.requests.post = post
try:
    arts, st = AppSource(CFG).collect_region(
        "샤넬", "역삼동-6035", proxy=DEAD, proxies=[DEAD] + ALIVE)
    ok, err = True, ""
except Exception as e:                      # noqa: BLE001 — 재현 테스트
    arts, st, ok, err = [], {}, False, f"{type(e).__name__}: {e}"
ck("죽은 IP 여도 다른 IP 로 재시도해 성공(웹크롤 폴백 전에)", ok and len(arts) == 25, err)
ck("실패한 IP 에 쿨다운(proxy_budget.mark_exhausted)",
   proxy_budget.is_cooling(DEAD), str(proxy_budget.stats()))
ck("재시도는 풀의 다른 IP 로", st.get("proxy") in ALIVE, str(st.get("proxy")))

# 재시도까지 실패하면 지금처럼 예외 → adaptive 가 웹크롤로 폴백(안전망 유지)
proxy_budget.reset()
post, calls = dead_ip_pager(DEAD)
app_api.requests.post = post
raised = None
try:
    AppSource(CFG).collect_region("샤넬", "역삼동-6035", proxy=DEAD, proxies=[DEAD])
except Exception as e:                      # noqa: BLE001
    raised = e
ck("갈아탈 IP 가 없으면 예외를 올려 폴백 유지", isinstance(raised, RuntimeError), str(raised))
ck("그 경우에도 죽은 IP 는 쿨다운", proxy_budget.is_cooling(DEAD))

# 프록시 없음(None/[]) → 직결 1회, 쿨다운 로직 자체를 건너뛴다
for empty in (None, []):
    proxy_budget.reset()
    post, calls = dead_ip_pager(None)        # 직결(None) 요청이 403
    app_api.requests.post = post
    raised = None
    try:
        AppSource(CFG).collect_region("샤넬", "역삼동-6035", proxies=empty)
    except Exception as e:                   # noqa: BLE001
        raised = e
    ck(f"proxies={empty!r} 이면 직결 1회만 시도(재시도·쿨다운 없음)",
       raised is not None and calls["proxies"] == [None] and not proxy_budget.stats(),
       f"{calls['proxies']} / {proxy_budget.stats()}")

# 5xx 는 IP 탓이 아니다(robust 의 NOT_IP_FAULT 와 같은 판단) → 멀쩡한 IP 를 태우지 않는다
proxy_budget.reset()


def _sleepless():
    import types as _t
    real = app_api.time
    app_api.time = _t.SimpleNamespace(sleep=lambda *_: None, time=real.time)
    return real


_realtime = _sleepless()
srv_calls = {"proxies": []}


def server_down(url, json=None, headers=None, **kw):
    srv_calls["proxies"].append(kw.get("proxy"))
    return FakeResp(503, {}, text="upstream down")


app_api.requests.post = server_down
try:
    AppSource(CFG).collect_region("샤넬", "역삼동-6035", proxy=ALIVE[0], proxies=ALIVE)
except Exception:                            # noqa: BLE001
    pass
app_api.time = _realtime
ck("5xx 에는 쿨다운을 걸지 않는다(풀 마름 방지)",
   not proxy_budget.is_cooling(ALIVE[0]), str(proxy_budget.stats()))
proxy_budget.reset()

print("\n=== I. 폴백 경고 dedup 키가 안정적이다(결함4) ===")

LOG.clear()
adaptive.set_app_fallback_logger(LOG.append)
adaptive.reset_app_fallback_notices()


def boom_varying(_tok):
    """실제 예외 문자열 — 지역·IP·응답본문이 매번 다르다.
    app_api.search_page 의 'HTTP {code}: {body[:200]}' 와 같은 모양."""
    n = len(LOG)
    raise app_api.AppApiError(f"HTTP 503: upstream {n} at http://p{n}:900{n}", status=503)


adaptive._app_source_for = boom_varying
adaptive.robust_fetch_articles = fake_web
for i in range(30):
    adaptive.collect_region("샤넬", f"동{i}-{i}", access_token="t", proxies=POOL)
big = [m for m in LOG if m.startswith("⚠️")]
ck("메시지가 매번 달라도 큰 경고는 1회만", len(big) == 1, f"⚠️ {len(big)}건 / 총 {len(LOG)}줄")
ck("축약 줄에도 지역·예외 요약은 남는다",
   any("동29-29" in m and "503" in m for m in LOG), LOG[-1][:90] if LOG else "(없음)")
ck("dedup 키 저장소가 메시지 수만큼 커지지 않는다",
   len(adaptive._FALLBACK_SEEN) == 1, str(adaptive._FALLBACK_SEEN))

# 상태코드가 다르면 별개 경고(진짜 새 장애는 놓치지 않는다)
adaptive.reset_app_fallback_notices()
LOG.clear()


def boom_401(_tok):
    raise app_api.AppApiError("HTTP 401: token expired", status=401)


adaptive._app_source_for = boom_varying
adaptive.collect_region("샤넬", "동A-1", access_token="t", proxies=POOL)
adaptive._app_source_for = boom_401
adaptive.collect_region("샤넬", "동B-2", access_token="t", proxies=POOL)
ck("상태코드가 다르면 각각 1회 크게 경고",
   sum(1 for m in LOG if m.startswith("⚠️")) == 2,
   f"⚠️ {sum(1 for m in LOG if m.startswith('⚠️'))}건")

# 상한 — 서로 다른 키가 아무리 많이 와도 _FALLBACK_SEEN 은 상한 이하로 유지
adaptive.reset_app_fallback_notices()
LOG.clear()
CAPN = adaptive._FALLBACK_SEEN_CAP
for i in range(CAPN * 3):
    def boom_i(_tok, _i=i):
        raise app_api.AppApiError(f"HTTP {i}", status=600 + _i)
    adaptive._app_source_for = boom_i
    adaptive.collect_region("샤넬", f"동{i}-{i}", access_token="t", proxies=POOL)
ck("_FALLBACK_SEEN 이 상한을 넘지 않는다",
   len(adaptive._FALLBACK_SEEN) <= CAPN, f"{len(adaptive._FALLBACK_SEEN)} <= {CAPN}")
ck("상한 도달 뒤에도 폴백 자체는 계속 동작(안전망)", WEB["n"] > 0)

adaptive._app_source_for = _orig_app_for
adaptive.robust_fetch_articles = _orig_web
adaptive.set_app_fallback_logger(None)
adaptive.reset_app_fallback_notices()
proxy_budget.reset()

print("\n" + "=" * 46)
bad = [n for n, c in R if not c]
print(f"{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("FAIL:", *bad, sep="\n  - ")
sys.exit(1 if bad else 0)

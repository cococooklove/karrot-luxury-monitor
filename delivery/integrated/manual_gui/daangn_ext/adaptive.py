"""
구 단위 + 가격분할 적응형 수집 — 최소 요청으로 전국 완전 수집.

원리:
  - 당근은 요청당 ~290건 상한 + 페이징 없음.
  - `in` 파라미터는 **동 ID 만** 받는다. 구 ID 를 넣으면 에러 없이 대표 동 하나로
    폴백해 나머지 동을 통째로 누락시킨다(실측: 강남구-381 → 역삼동 258건만,
    동 6개 합집합 1,544건 중 1,286건 유실). 반드시 load_dong_regions() 로 순회할 것.
  - 동이 상한에 차면(포화=매물 잘림) **가격 범위를 이분 재귀 분할**해 상한 우회.
    [0,1억] → 포화면 [0,5천만]+[5천만,1억] → 또 포화면 계속 반분. + [1억,∞) 초고가 버킷.
  - 전 구간 합집합을 id 로 중복제거 → 완전 수집.

프록시 로테이션(next_proxy)·토큰(옵션)은 robust 로 그대로 전달.

지역 순회는 **지역 사이마다 랜덤 휴식**을 넣는다(등간격·무휴식 버스트 = IP 스로틀 유발).
한 IP 안에서는 절대 병렬로 돌리지 말 것 — 실측상 같은 IP 동시요청은 전멸(8/8 빈응답).
병렬이 필요하면 서로 다른 프록시 IP 를 쓰는 레인끼리만.
"""
from __future__ import annotations

from typing import Callable

from . import proxy_budget, throttle
from .rest_scheduler import asleep_between, sleep_between
from .robust import robust_fetch_articles

REGION_REST = (0.4, 1.2)    # 지역 사이 랜덤 휴식(초). None 이면 휴식 없음

PMAX = 100_000_000          # 재귀 분할 상단(1억). 그 위는 별도 개방버킷.
CAP = 280                   # 이 이상이면 '포화'(잘림)로 보고 분할
MIN_GAP = 10_000            # 가격 구간이 이보다 좁으면 더 안 쪼갬(그만 수용)
MAX_DEPTH = 12


# 억제 키워드 우회용 접미어. 실측상 '샤넬' 은 12회 중 2회만 응답하지만
# '샤넬가방' 은 12/12 응답하고 건수(270)도 동일하다.
SUFFIXES = ("가방", "지갑", "시계", "신발", "옷", "팔찌", "목걸이")
EXPAND_TRIES = 3        # 억제 시 시도할 접미어 개수 상한(전체구간 1회에만 적용)


def suffixes_for(keyword: str) -> list:
    """억제된 키워드를 대체할 확장 키워드 후보."""
    kw = (keyword or "").strip()
    if not kw:
        return []
    return [f"{kw}{s}" for s in SUFFIXES]


import threading as _threading
_APP_SRC = None
_APP_SRC_LOCK = _threading.Lock()

# 앱API→웹크롤 폴백 통지. 기본은 stderr 로 찍는다(모니터가 없어도 흔적이 남게).
# GUI/서버는 set_app_fallback_logger(self._log) 로 갈아끼우면 화면·로그파일로 간다.
_FALLBACK_LOG: Callable[[str], None] | None = None
# 같은 예외로 매 지역마다 로그가 폭주하지 않게 **원인별** 1회만 크게 알린다.
# 키는 예외 요약문이 아니라 _fallback_key() 가 만드는 안정된 값이다(아래 참고).
_FALLBACK_SEEN: set = set()
_FALLBACK_SEEN_LOCK = _threading.Lock()
# 키가 안정적이면 실제로는 몇 종류뿐이지만, 예상 못 한 예외가 쏟아져도
# 이 집합이 무한히 커지지 않게 상한을 둔다(6,537개 지역 × 사이클).
_FALLBACK_SEEN_CAP = 64


def set_app_fallback_logger(fn: Callable[[str], None] | None) -> None:
    """앱API 폴백 경고를 받을 로거 주입(모니터의 _log 등). None 이면 stderr."""
    global _FALLBACK_LOG
    _FALLBACK_LOG = fn


def get_app_fallback_logger() -> Callable[[str], None] | None:
    """현재 등록된 폴백 로거. 호출자가 끝날 때 되돌리려고 읽는다.

    _FALLBACK_LOG 는 프로세스 전역이라, 스윕이 자기 _log 를 걸고 안 되돌리면
    이미 죽은 수신자(disconnect 된 시그널의 bound emit)를 계속 물고 있게 된다.
    호출은 성공하지만 아무도 못 보고 stderr 폴백도 안 타 경고가 통째로 사라진다.
    """
    return _FALLBACK_LOG


def reset_app_fallback_notices() -> None:
    """1회성 경고 기억 초기화(테스트/새 사이클용)."""
    with _FALLBACK_SEEN_LOCK:
        _FALLBACK_SEEN.clear()


def _exc_summary(e: BaseException) -> str:
    """'ValueError: 헤더 없음' 형태의 한 줄 요약. 로그·stats 양쪽에 같은 값을 쓴다."""
    msg = str(e).strip().replace("\n", " ")
    return f"{type(e).__name__}: {msg[:160]}" if msg else type(e).__name__


def _fallback_key(e: BaseException) -> str:
    """경고 dedup 키 — **매번 달라지지 않는 것만** 넣는다: 예외 타입 + HTTP 상태코드.

    _exc_summary(예외 메시지)를 키로 쓰면 안 된다. 실제 메시지는
    app_api.search_page 의 'HTTP {code}: {응답본문 200자}' 와 _post 의
    '요청 실패: {전송오류}'(프록시 host:port 가 박힘)라서 지역·IP 마다 다르다.
    그러면 매번 처음 보는 키가 되어 6,537개 지역이 전부 ⚠️ 전체 줄을 찍고
    _FALLBACK_SEEN 도 무한히 커진다.

    상태코드는 예외 메시지 파싱이 아니라 app_api.AppApiError.status 로 받는다 —
    메시지 포맷이 바뀌면 조용히 깨지는 정규식보다 낫고, 상태코드가 필요한 곳이
    여기 말고 app_source(IP 쿨다운 판단)에도 있어서 어차피 구조적 노출이 필요했다.
    """
    st = getattr(e, "status", None)
    return f"{type(e).__name__}:{st if isinstance(st, int) else '-'}"


def _warn_app_fallback(region_in: str, keyword: str, summary: str,
                       key: str | None = None) -> None:
    """앱API 실패 → 웹크롤 폴백 사실을 반드시 밖으로 낸다.

    웹크롤은 명품 브랜드를 억제한다('샤넬' 0건 vs 앱API 1,000건+). 조용히 폴백하면
    토큰만료·네트워크오류·앱API 스펙변경이 전부 '매물 없음'으로 보여 운영자가
    장애를 인지할 수 없다(이 함수가 존재하는 유일한 이유).

    줄이는 건 '크게 찍는 빈도'뿐이다 — 축약 줄에도 지역·예외 요약은 그대로 남긴다.
    """
    key = key or summary
    with _FALLBACK_SEEN_LOCK:
        first = key not in _FALLBACK_SEEN
        if first and len(_FALLBACK_SEEN) >= _FALLBACK_SEEN_CAP:
            # 상한 도달: 새 키는 기록하지 않고 크게 알리지도 않는다(축약 줄만 남음).
            # 이 함수의 목적이 로그 폭주 방지이므로, 상한을 넘겨 키를 계속 쌓느니
            # 큰 경고를 포기한다. reset_app_fallback_notices()(사이클마다 호출)로 풀린다.
            first = False
        elif first:
            _FALLBACK_SEEN.add(key)
    head = "⚠️ [앱API 실패→웹크롤 폴백]" if first else "[앱API 폴백]"
    line = (f"{head} {summary} · 지역 {region_in} · 키워드 '{keyword}' — "
            "웹크롤은 명품 브랜드를 억제하므로 결과가 0건일 수 있다. 토큰/헤더 확인 필요")
    fn = _FALLBACK_LOG
    if fn:
        try:
            fn(line)
            return
        except Exception:
            pass
    import sys
    print(line, file=sys.stderr, flush=True)


def _app_source_for(access_token):
    """캐시된 AppSource 에 토큰만 메모리 갱신해 반환. config.json 재로드·파일쓰기 없음.
    config.json(device 헤더) 없거나 필수헤더 누락이면 AppApiConfig 가 예외 → 호출측서 웹크롤 폴백."""
    global _APP_SRC
    with _APP_SRC_LOCK:
        if _APP_SRC is None:
            from .app_source import AppSource
            _APP_SRC = AppSource()          # data/config.json 헤더 로드
        tok = access_token if access_token.lower().startswith("bearer ") else f"Bearer {access_token}"
        _APP_SRC.cfg.headers["authorization"] = tok
        return _APP_SRC


def collect_region(
    keyword: str,
    region_in: str,                         # "강남구-381"
    proxy: str | None = None,
    only_on_sale: bool = True,
    access_token: str | None = None,
    next_proxy: Callable[[], str | None] | None = None,
    cap: int = CAP,
    should_stop: Callable[[], bool] | None = None,
    proxies: list | None = None,
) -> tuple[list, dict]:
    """한 지역(구) 완전 수집. (articles, stats) 반환. 포화면 가격분할.
    proxies 풀 주면 시작 IP 만 풀에서 고르고, 빈응답이 나는 즉시 robust 가 다음 IP 로 넘긴다.
    should_stop() True 면 즉시 중단.

    ★ 토큰이 있으면 app-API(search-bff)로 수집한다. 웹크롤(daangn.com)은 명품 브랜드
      키워드를 억제해 '샤넬' 0건이 나오지만, 앱API는 수천 건 + 페이징을 준다(app_api.py).
      토큰 없거나 앱API 실패 시에만 웹크롤로 폴백."""
    app_failed: str | None = None
    if access_token:
        try:
            src = _app_source_for(access_token)
            return src.collect_region(
                keyword, region_in, only_on_sale=only_on_sale,
                proxy=proxy, proxies=proxies, should_stop=should_stop)
        except Exception as _e:
            # 폴백은 안전망이라 유지한다. 다만 절대 조용히 넘어가지 않는다 —
            # 로그로 알리고 stats["app_api_failed"] 로 상위(sweep_engine/GUI)까지 올린다.
            app_failed = _exc_summary(_e)
            _warn_app_fallback(region_in, keyword, app_failed, key=_fallback_key(_e))
    seen: dict = {}
    # missed = 재시도 소진으로 "확인 못 한" 가격구간. 0건과 반드시 구분해야 한다.
    stats = {"requests": 0, "splits": 0, "saturated": False, "missed": [],
             "empties": 0, "suppressed": 0, "expanded": []}
    if app_failed:
        # 이 지역 결과가 '앱API 없이 얻은 것'임을 결과에 박아둔다.
        stats["app_api_failed"] = app_failed
    # 시작 IP 만 고정. 쿨다운 중인 IP 는 후보에서 제외.
    fixed_proxy = proxy or proxy_budget.pick(proxies)

    def _once(pmin, pmax, use_proxy, kw=None):
        stats["requests"] += 1
        arts, meta = robust_fetch_articles(
            kw or keyword, region_in, proxy=use_proxy, only_on_sale=only_on_sale,
            min_price=pmin, max_price=pmax, access_token=access_token,
            next_proxy=next_proxy, should_stop=should_stop, proxies=proxies)
        stats["empties"] += meta.get("empties", 0)
        return arts, meta

    def fetch(pmin, pmax):
        """0건일 때 원인별로 다르게 대응한다.

        suppressed — 카나리아가 통과 = 세션·IP 정상. 이 쿼리만 억제됐거나 진짜 0건.
                     IP 를 갈아도 소용없으므로 재시도하지 않고, 키워드 접미어로 우회한다.
                     (실측: '샤넬' 단독 성공 2/12 vs '샤넬가방' 12/12, 건수는 둘 다 270)
        exhausted  — 카나리아도 실패 = 세션·IP 문제. 새 IP 로 1회 더, 그래도 실패면 missed.
        """
        arts, meta = _once(pmin, pmax, fixed_proxy)
        stopped = should_stop and should_stop()

        if meta.get("suppressed") and not stopped:
            stats["suppressed"] += 1
            # 확장은 전체구간(0~PMAX) 1회만. 가격 분할 구간·초고가 버킷까지 확장하면
            # 진짜 0건에도 접미어 7개를 헛되이 쏘게 된다.
            if (pmin, pmax) == (0, PMAX):
                for alt in suffixes_for(keyword)[:EXPAND_TRIES]:
                    arts2, _m2 = _once(pmin, pmax, fixed_proxy, kw=alt)
                    if arts2:
                        stats["expanded"].append(alt)
                        arts = arts2
                        break
                    if should_stop and should_stop():
                        break
        elif meta.get("exhausted") and not stopped:
            retry_proxy = proxy_budget.pick(proxies, exclude=fixed_proxy) if proxies else None
            arts, meta = _once(pmin, pmax, retry_proxy or fixed_proxy)
            if meta.get("exhausted"):
                stats["missed"].append((pmin, pmax))

        for a in arts:
            seen[a["id"]] = a
        return len(arts)

    def rec(pmin, pmax, depth):
        if should_stop and should_stop():
            return
        n = fetch(pmin, pmax)
        if n >= cap:
            stats["saturated"] = True
            if depth < MAX_DEPTH and (pmax - pmin) > MIN_GAP:
                stats["splits"] += 1
                mid = (pmin + pmax) // 2
                rec(pmin, mid, depth + 1)
                rec(mid + 1, pmax, depth + 1)

    rec(0, PMAX, 0)
    fetch(PMAX + 1, None)                    # 1억 초과 초고가 버킷
    return list(seen.values()), stats


def load_dong_regions(out_json_path: str) -> list[dict]:
    """OUT.json → 전국 동(depth 3) 목록 [{'in':'역삼동-6035', ...}].

    당근 웹의 `in` 파라미터는 **동 ID 만** 받는다. 구 ID 를 넘기면 에러가 아니라
    임의의 대표 동 하나로 폴백해 조용히 그 동 결과만 돌려준다.
    실측(2026-08-27, '가방'): 강남구-381 → 258건인데 전부 역삼동.
    역삼동-6035 와 100% 동일하고, 대치/청담/논현/삼성/압구정 매물은 0건 포함.
    동 6개만 합쳐도 1,544건 → 구 조회는 강남구 31개 동 중 1개만 커버(약 3%).
    """
    import json
    d = json.load(open(out_json_path, encoding="utf-8"))
    out, seen = [], set()
    for b in d:
        for l in b.get("locations", []):
            if l.get("depth") != 3:
                continue
            code = f"{l['name']}-{l['id']}"
            if code in seen:
                continue
            seen.add(code)
            out.append({"in": code, "name1": l.get("name1"),
                        "name2": l.get("name2"), "name3": l.get("name3")})
    return out


def load_gu_regions(out_json_path: str) -> list[dict]:
    """⚠️ 수집에 쓰지 말 것 — 구 ID 는 당근 `in` 파라미터가 받지 않는다.

    반환하는 'in'(예: '강남구-381')을 그대로 조회하면 대표 동 하나로 폴백해
    구의 나머지 동이 통째로 누락된다. 지역 목록 표시 등 비수집 용도로만.
    수집은 load_dong_regions() 를 쓸 것.
    """
    import json
    d = json.load(open(out_json_path, encoding="utf-8"))
    locs = []
    for b in d:
        locs += b.get("locations", [])
    gus = {}
    for l in locs:
        key = (l["name1Id"], l["name2Id"])
        if key not in gus:
            gus[key] = {"in": f"{l['name2']}-{l['name2Id']}",
                        "name1": l["name1"], "name2": l["name2"]}
    return list(gus.values())


def collect_nationwide(
    keyword: str,
    regions: list[dict],
    proxy: str | None = None,
    only_on_sale: bool = True,
    access_token: str | None = None,
    next_proxy: Callable[[], str | None] | None = None,
    on_region: Callable[[dict, int, dict], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    proxies: list | None = None,
    rest_range: tuple[float, float] | None = REGION_REST,
) -> tuple[list, dict]:
    """전국(구 목록) 적응형 수집. 전역 id 중복제거. (articles, summary).
    rest_range 로 지역 사이 랜덤 휴식(등간격 폴링 = 봇 패턴 → 스로틀). None 이면 생략."""
    seen: dict = {}
    total_req = sat = rested = app_fb = 0
    app_fb_last = None
    for idx, reg in enumerate(regions):
        if should_stop and should_stop():
            break
        if rest_range and idx:                       # 첫 지역 앞에는 휴식 불필요
            sleep_between(*throttle.scale_range(rest_range))   # 감속 중이면 휴식도 함께 길어진다
            rested += 1
        arts, st = collect_region(keyword, reg["in"], proxy=proxy,
                                  only_on_sale=only_on_sale,
                                  access_token=access_token, next_proxy=next_proxy,
                                  should_stop=should_stop, proxies=proxies)
        for a in arts:
            seen[a["id"]] = a
        total_req += st.get("requests", 0)
        sat += 1 if st.get("saturated") else 0
        if st.get("app_api_failed"):
            app_fb += 1
            app_fb_last = st["app_api_failed"]
        if on_region:
            on_region(reg, len(arts), st)
    return list(seen.values()), {"regions": len(regions), "requests": total_req,
                                 "saturated_regions": sat, "unique": len(seen),
                                 "rests": rested,
                                 # 앱API 폴백이 한 번이라도 있었으면 요약에도 남긴다
                                 "app_api_fallbacks": app_fb,
                                 "app_api_failed": app_fb_last}


async def collect_region_async(
    session,                                # aiohttp.ClientSession (재사용)
    keyword: str,
    region_in: str,
    proxy: str | None = None,
    only_on_sale: bool = True,
    access_token: str | None = None,
    cap: int = CAP,
    next_proxy: Callable[[], str | None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    proxies: list | None = None,
) -> tuple[list, dict]:
    """auto(aiohttp)용 구단위+가격분할. robust async 사용.
    sync 판과 동일하게 프록시 풀·예산 쿨다운·중단훅을 전달한다."""
    from .robust import robust_fetch_articles_async
    seen: dict = {}
    stats = {"requests": 0, "splits": 0, "saturated": False}
    # 시작 IP 만 고정. 빈응답이 나면 robust 가 곧바로 다음 IP 로 교체.
    fixed_proxy = proxy or proxy_budget.pick(proxies)

    async def fetch(pmin, pmax):
        stats["requests"] += 1
        arts, _ = await robust_fetch_articles_async(
            session, keyword, region_in, proxy=fixed_proxy, only_on_sale=only_on_sale,
            min_price=pmin, max_price=pmax, access_token=access_token,
            next_proxy=next_proxy, should_stop=should_stop, proxies=proxies)
        for a in arts:
            seen[a["id"]] = a
        return len(arts)

    async def rec(pmin, pmax, depth):
        if should_stop and should_stop():
            return
        n = await fetch(pmin, pmax)
        if n >= cap:
            stats["saturated"] = True
            if depth < MAX_DEPTH and (pmax - pmin) > MIN_GAP:
                stats["splits"] += 1
                mid = (pmin + pmax) // 2
                await rec(pmin, mid, depth + 1)
                await rec(mid + 1, pmax, depth + 1)

    await rec(0, PMAX, 0)
    await fetch(PMAX + 1, None)
    return list(seen.values()), stats


async def collect_nationwide_async(
    session,                                # aiohttp.ClientSession (레인당 1개)
    keyword: str,
    regions: list[dict],
    proxy: str | None = None,
    only_on_sale: bool = True,
    access_token: str | None = None,
    next_proxy: Callable[[], str | None] | None = None,
    on_region: Callable[[dict, int, dict], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    proxies: list | None = None,
    rest_range: tuple[float, float] | None = REGION_REST,
) -> tuple[list, dict]:
    """auto 용 지역 순회 — **순차** + 지역 사이 랜덤 휴식.
    ※ 이 함수를 한 IP 안에서 여러 개 동시에 돌리지 말 것(같은 IP 버스트 = 전멸).
       병렬은 서로 다른 프록시를 가진 레인끼리, 레인마다 이 함수 1개."""
    seen: dict = {}
    total_req = sat = rested = 0
    for idx, reg in enumerate(regions):
        if should_stop and should_stop():
            break
        if rest_range and idx:
            await asleep_between(*throttle.scale_range(rest_range))
            rested += 1
        arts, st = await collect_region_async(
            session, keyword, reg["in"], proxy=proxy, only_on_sale=only_on_sale,
            access_token=access_token, next_proxy=next_proxy,
            should_stop=should_stop, proxies=proxies)
        for a in arts:
            seen[a["id"]] = a
        total_req += st["requests"]
        sat += 1 if st["saturated"] else 0
        if on_region:
            on_region(reg, len(arts), st)
    return list(seen.values()), {"regions": len(regions), "requests": total_req,
                                 "saturated_regions": sat, "unique": len(seen),
                                 "rests": rested}


# ══════════════════════════════════════════════════════════════════════
# 레인 병렬 — 프록시 IP 를 축으로 실제 처리량을 늘리는 유일한 방법
# ══════════════════════════════════════════════════════════════════════
#
# 실측 제약 두 가지가 설계를 강제한다:
#   1. 같은 IP 로 동시요청하면 전멸 (8/8 빈응답). → 한 IP 는 한 순간에 한 요청만.
#   2. 빈응답이 나면 다른 IP 로 교체해야 빠르다 (6/6 vs 4/6, 5.5회 vs 23.5회).
#
# 둘을 동시에 만족시키려면 **풀을 레인 수만큼 샤딩**해야 한다. 레인들이 하나의 풀을
# 공유하면 robust 의 랜덤 교체가 다른 레인이 쓰는 중인 IP 를 뽑아 (1) 을 위반한다.
# 샤딩하면 각 레인은 자기 몫 IP 안에서만 교체하므로 두 조건이 같이 성립한다.
#
# 지역은 정적 분할이 아니라 **공유 큐**로 나눠준다. 지역마다 소요가 10배 이상
# 차이나므로(빈응답 운) 정적 분할은 느린 레인 하나가 전체를 잡아먹는다.

def shard_proxies(proxies: list, lanes: int) -> list[list]:
    """풀을 lanes 개 그룹으로 라운드로빈 분배. 그룹끼리 IP 가 겹치지 않는다."""
    if not proxies:
        return [[] for _ in range(lanes)]
    out: list[list] = [[] for _ in range(lanes)]
    for i, p in enumerate(proxies):
        out[i % lanes].append(p)
    return [g for g in out if g]


def plan_lanes(proxies: list | None, lanes: int | None, max_lanes: int = 16) -> int:
    """실제로 돌릴 레인 수. 프록시 수를 넘을 수 없다(넘으면 IP 를 공유하게 됨)."""
    if not proxies:
        return 1                       # 프록시 없으면 IP 1개 = 레인 1개
    want = lanes or len(proxies)
    return max(1, min(want, len(proxies), max_lanes))


def collect_lanes(
    keyword: str,
    regions: list[dict],
    proxies: list | None = None,
    lanes: int | None = None,
    only_on_sale: bool = True,
    access_token: str | None = None,
    on_region: Callable[[dict, int, dict], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    rest_range: tuple[float, float] | None = REGION_REST,
    max_lanes: int = 16,
    on_lane: Callable[[int, dict], None] | None = None,
    on_result: Callable[[dict, list, dict], None] | None = None,
) -> tuple[list, dict]:
    """지역 목록을 레인 N개로 병렬 수집. 레인끼리 프록시를 공유하지 않는다.

    lanes 미지정이면 프록시 수(최대 max_lanes)만큼. 프록시가 없으면 1레인 = 순차.
    on_region(reg, 건수, stats) / on_result(reg, 매물리스트, stats) 는 레인들이 동시에
    부르므로 내부에서 락으로 직렬화한다. on_result 는 지역이 끝나는 즉시 그 지역 매물을
    넘겨받아 스트리밍 처리(중복제거·알림)를 할 수 있게 한다 — 전체가 끝날 때까지
    기다리지 않아도 된다.
    반환은 collect_nationwide 와 같은 모양 + lanes/per_lane/skipped.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    n_lanes = plan_lanes(proxies, lanes, max_lanes)
    shards = shard_proxies(list(proxies or []), n_lanes) or [[]]
    n_lanes = len(shards)

    queue = list(regions)
    q_lock = threading.Lock()
    w_lock = threading.Lock()
    seen: dict = {}
    total_req = sat = rested = app_fb = 0
    app_fb_last = None
    per_lane = [{"regions": 0, "requests": 0, "articles": 0, "proxies": len(s)}
                for s in shards]

    def take():
        with q_lock:
            return queue.pop(0) if queue else None

    def lane(idx: int):
        nonlocal total_req, sat, rested, app_fb, app_fb_last
        pool = shards[idx] or None
        first = True
        while True:
            if should_stop and should_stop():
                return
            reg = take()
            if reg is None:
                return
            if rest_range and not first:
                sleep_between(*throttle.scale_range(rest_range))
                with w_lock:
                    rested += 1
            first = False
            arts, st = collect_region(
                keyword, reg["in"], only_on_sale=only_on_sale,
                access_token=access_token, should_stop=should_stop, proxies=pool)
            with w_lock:
                for a in arts:
                    seen[a["id"]] = a
                # .get 로 읽는다 — 소스마다 stats 키가 다를 수 있는데 KeyError 가
                # 나면 이 레인 스레드가 통째로 죽어 그 지역들이 조용히 유실된다.
                total_req += st.get("requests", 0)
                sat += 1 if st.get("saturated") else 0
                if st.get("app_api_failed"):
                    app_fb += 1
                    app_fb_last = st["app_api_failed"]
                per_lane[idx]["regions"] += 1
                per_lane[idx]["requests"] += st.get("requests", 0)
                per_lane[idx]["articles"] += len(arts)
                if on_result:
                    on_result(reg, arts, st)
                if on_region:
                    on_region(reg, len(arts), st)
                if on_lane:
                    on_lane(idx, per_lane[idx])

    with ThreadPoolExecutor(max_workers=n_lanes) as ex:
        list(ex.map(lane, range(n_lanes)))

    return list(seen.values()), {
        "regions": len(regions), "requests": total_req,
        "saturated_regions": sat, "unique": len(seen), "rests": rested,
        "lanes": n_lanes, "per_lane": per_lane,
        "skipped": len(queue),          # should_stop 으로 남긴 지역 수
        # 앱API 폴백이 몇 지역에서 일어났는지 + 마지막 예외 요약(운영자 통지용)
        "app_api_fallbacks": app_fb,
        "app_api_failed": app_fb_last,
    }


async def collect_lanes_async(
    keyword: str,
    regions: list[dict],
    proxies: list | None = None,
    lanes: int | None = None,
    only_on_sale: bool = True,
    access_token: str | None = None,
    on_region: Callable[[dict, int, dict], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    rest_range: tuple[float, float] | None = REGION_REST,
    max_lanes: int = 16,
    session_factory=None,
    on_result: Callable[[dict, list, dict], None] | None = None,
) -> tuple[list, dict]:
    """auto(aiohttp)용 레인 병렬. **레인마다 ClientSession 을 따로 만든다**
    (세션을 공유하면 커넥션풀·쿠키가 섞여 레인 격리가 깨진다).
    session_factory() 로 세션 생성을 주입할 수 있다(기본 aiohttp.ClientSession)."""
    import asyncio

    if session_factory is None:
        def session_factory():
            from aiohttp import ClientSession
            return ClientSession()

    n_lanes = plan_lanes(proxies, lanes, max_lanes)
    shards = shard_proxies(list(proxies or []), n_lanes) or [[]]
    n_lanes = len(shards)

    queue = list(regions)
    seen: dict = {}
    totals = {"requests": 0, "saturated": 0, "rested": 0}
    per_lane = [{"regions": 0, "requests": 0, "articles": 0, "proxies": len(s)}
                for s in shards]

    def take():
        return queue.pop(0) if queue else None     # 단일 이벤트루프 = 락 불필요

    async def lane(idx: int):
        pool = shards[idx] or None
        sess = session_factory()
        first = True
        try:
            while True:
                if should_stop and should_stop():
                    return
                reg = take()
                if reg is None:
                    return
                if rest_range and not first:
                    await asleep_between(*throttle.scale_range(rest_range))
                    totals["rested"] += 1
                first = False
                arts, st = await collect_region_async(
                    sess, keyword, reg["in"], only_on_sale=only_on_sale,
                    access_token=access_token, should_stop=should_stop, proxies=pool)
                for a in arts:
                    seen[a["id"]] = a
                totals["requests"] += st["requests"]
                totals["saturated"] += 1 if st["saturated"] else 0
                per_lane[idx]["regions"] += 1
                per_lane[idx]["requests"] += st["requests"]
                per_lane[idx]["articles"] += len(arts)
                if on_result:
                    on_result(reg, arts, st)
                if on_region:
                    on_region(reg, len(arts), st)
        finally:
            close = getattr(sess, "close", None)
            if close:
                r = close()
                if asyncio.iscoroutine(r):
                    await r

    await asyncio.gather(*(lane(i) for i in range(n_lanes)))

    return list(seen.values()), {
        "regions": len(regions), "requests": totals["requests"],
        "saturated_regions": totals["saturated"], "unique": len(seen),
        "rests": totals["rested"], "lanes": n_lanes, "per_lane": per_lane,
        "skipped": len(queue),
    }

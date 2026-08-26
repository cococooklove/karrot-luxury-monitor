"""
구 단위 + 가격분할 적응형 수집 — 최소 요청으로 전국 완전 수집.

원리:
  - 당근은 요청당 ~290건 상한 + 페이징 없음.
  - 동(6537) 대신 **구(252)** 단위로 훑으면 26배 적은 요청.
  - 구가 상한에 차면(포화=매물 잘림) **가격 범위를 이분 재귀 분할**해 상한 우회.
    [0,1억] → 포화면 [0,5천만]+[5천만,1억] → 또 포화면 계속 반분. + [1억,∞) 초고가 버킷.
  - 전 구간 합집합을 id 로 중복제거 → 완전 수집.

프록시 로테이션(next_proxy)·토큰(옵션)은 robust 로 그대로 전달.

지역 순회는 **지역 사이마다 랜덤 휴식**을 넣는다(등간격·무휴식 버스트 = IP 스로틀 유발).
한 IP 안에서는 절대 병렬로 돌리지 말 것 — 실측상 같은 IP 동시요청은 전멸(8/8 빈응답).
병렬이 필요하면 서로 다른 프록시 IP 를 쓰는 레인끼리만.
"""
from __future__ import annotations

from typing import Callable

from . import proxy_budget
from .rest_scheduler import asleep_between, sleep_between
from .robust import robust_fetch_articles

REGION_REST = (0.4, 1.2)    # 지역 사이 랜덤 휴식(초). None 이면 휴식 없음

PMAX = 100_000_000          # 재귀 분할 상단(1억). 그 위는 별도 개방버킷.
CAP = 280                   # 이 이상이면 '포화'(잘림)로 보고 분할
MIN_GAP = 10_000            # 가격 구간이 이보다 좁으면 더 안 쪼갬(그만 수용)
MAX_DEPTH = 12


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
    proxies 풀 주면 이 구는 그 중 1개로 워밍 고정, 실패 시만 교체(구끼리는 상위에서 분산).
    should_stop() True 면 즉시 중단."""
    seen: dict = {}
    stats = {"requests": 0, "splits": 0, "saturated": False}
    # 구당 프록시 1개 고정(세션 워밍 = 빠름). 쿨다운 중인 IP 는 제외하고 고른다.
    fixed_proxy = proxy or proxy_budget.pick(proxies)

    def fetch(pmin, pmax):
        stats["requests"] += 1
        arts, _ = robust_fetch_articles(
            keyword, region_in, proxy=fixed_proxy, only_on_sale=only_on_sale,
            min_price=pmin, max_price=pmax, access_token=access_token,
            next_proxy=next_proxy, should_stop=should_stop, proxies=proxies)
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


def load_gu_regions(out_json_path: str) -> list[dict]:
    """OUT.json → 전국 구(name2) 목록 [{'in':'강남구-381','name1':..,'name2':..}]."""
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
    total_req = sat = rested = 0
    for idx, reg in enumerate(regions):
        if should_stop and should_stop():
            break
        if rest_range and idx:                       # 첫 지역 앞에는 휴식 불필요
            sleep_between(*rest_range)
            rested += 1
        arts, st = collect_region(keyword, reg["in"], proxy=proxy,
                                  only_on_sale=only_on_sale,
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
    # 이 구는 프록시 1개로 워밍 고정, 실패 시에만 robust 가 풀에서 교체.
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
            await asleep_between(*rest_range)
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

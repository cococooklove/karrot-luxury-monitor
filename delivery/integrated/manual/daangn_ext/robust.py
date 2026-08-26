"""
견고한 수집 — "막힘"의 진짜 원인 대응.

실측(2026-08-26): 당근은 새 세션/IP의 **초기 요청 몇 건을 빈 페이지(0건)로 응답**하고
그 뒤 정상(수백건) 응답한다. 기존 코드는 빈 결과를 '성공(0건)'으로 처리해 재시도하지
않아 매물을 놓쳤다 = 사용자가 겪은 "당근이 막는다".

대응: 빈 결과 = 소프트블록으로 간주 → 세션 유지(쿠키) + 재시도(같은/다음 프록시).

빈응답이 나면 **같은 IP 로 버티지 말고 즉시 다른 IP 로 교체**하는 게 실측상 최적이다.
프록시 풀 20개로 6개 지역 A/B (2026-08-26):

  A) 한 IP 고정 재시도    성공 4/6, 성공까지 요청 median 23.5회, 총 549s
  B) 빈응답마다 IP 교체    성공 6/6, 성공까지 요청 median  5.5회, 총 379s

즉 빈응답은 "그 IP 를 더 두드리면 뚫리는 워밍"이 아니라 **시점별 변동**이라, 다음 IP 를
뽑는 편이 빠르다(같은 IP·같은 지역이 몇 분 사이 1회 ↔ 25회로 요동하는 것도 확인).
같은 이유로 빈응답에는 쿨다운을 걸지 않는다 — 20회 연속 빈응답이던 IP 가 몇 분 뒤
1~13회만에 성공했다. 쿨다운은 하드차단·네트워크오류 낸 IP 에만.
백오프 길이는 유의차 없었다(0.1s vs 0.8s → 요청당 4.99s vs 5.52s). 요청 자체가 느려서 묻힌다.
"""
from __future__ import annotations

import json
import time
from typing import Callable

from bs4 import BeautifulSoup as Soup
from curl_cffi import requests

from . import proxy_budget, throttle
from .auth import build_headers
from .block_signals import NOT_IP_FAULT, classify, summarize

BUYSELL = "https://www.daangn.com/kr/buy-sell/"

# ── 카나리아 ──
# 당근은 일부 브랜드 키워드('샤넬' 등)에 확률적으로 빈 결과를 준다(실측 성공률 2/12).
# 이건 IP·세션 차단이 아니라 쿼리 종속이라, IP 를 갈아도 재시도해도 대부분 헛돈다.
# 그래서 빈응답이 연속되면 같은 세션·같은 IP 로 '결과가 확실한 쿼리'를 1회 쏴서 구분한다.
#   카나리아 성공 → 세션·IP 는 멀쩡 = 이 쿼리만 억제됨/진짜 0건 → 조기 종료
#   카나리아 실패 → 세션·IP 문제 = 계속 재시도 + 로테이션
# 실측(2026-08-26): '삽니다' 는 종로구·보은군·부안군·강남구 4/4 성공(10~255건).
CANARY_KEYWORD = "삽니다"
CANARY_AFTER = 3        # 빈응답 이만큼 연속되면 카나리아 1회
CANARY_MAX = 2          # 카나리아 총 횟수 상한


def parse_articles(html: str) -> list | None:
    """remixContext → fleamarketArticles. 파싱 실패(차단/구조변경)면 None, 정상 빈페이지면 []."""
    for s in Soup(html, "html.parser").select("script"):
        if "window.__remixContext" in (s.text or ""):
            j = s.text.replace("window.__remixContext = ", "").rstrip(";")
            try:
                route = json.loads(j)["state"]["loaderData"]["routes/kr.buy-sell._index"]
            except Exception:
                return None
            return (route.get("allPage", {}) or {}).get("fleamarketArticles", [])
    return None


def build_params(keyword: str, area_code: str, only_on_sale: bool,
                 min_price: int | None, max_price: int | None) -> dict:
    price = f"{min_price if min_price is not None else ''}__" \
            f"{max_price if max_price is not None else ''}"
    p = {"search": keyword, "in": area_code, "price": price}
    if only_on_sale:
        p["only_on_sale"] = "true"
    return p


def robust_fetch_articles(
    keyword: str,
    area_code: str,
    proxy: str | None = None,
    only_on_sale: bool = True,
    min_price: int | None = None,
    max_price: int | None = None,
    access_token: str | None = None,
    max_retry: int = 45,          # 실측 22회 필요 사례 확인(2026-08-26) → 30 은 소진 위험
    empty_backoff: float = 0.5,   # 0.1~0.8 유의차 없음 → 중간값
    next_proxy: Callable[[], str | None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    proxies: list | None = None,
    empty_rotate_after: int = proxy_budget.EMPTY_ROTATE_AFTER,
    cooldown_sec: float = proxy_budget.COOLDOWN_SEC,
    give_up_after: int = 3,       # IP 탓 아닌 실패(PARSE/5xx) 연속 이 횟수면 조기중단
    canary_after: int = CANARY_AFTER,     # 빈응답 연속 이 횟수면 카나리아로 원인 판별
    canary_max: int = CANARY_MAX,
) -> tuple[list, dict]:
    """실매물 나올 때까지 재시도. (articles, meta) 반환.
    meta = {tries, empties, blocked, rotations, proxy}. 빈응답 극복이 핵심.
    proxies 를 주면 풀에서 선택(쿨다운 중인 IP 는 제외).
    빈응답 empty_rotate_after(기본 1)회마다 다음 IP 로 교체 — 쿨다운은 걸지 않는다.
    쿨다운은 하드차단·네트워크오류 낸 IP 에만 cooldown_sec 만큼.
    should_stop() 이 True 면 즉시 중단(자동 모니터 정지 반응)."""
    params = build_params(keyword, area_code, only_on_sale, min_price, max_price)
    headers = build_headers(BUYSELL, access_token)     # 기본값이면 daangn엔 미주입
    sess = requests.Session(impersonate="chrome")      # 브라우저 지문 위장(TLS/JA3)
    # 시작 IP. 빈응답이 나면 곧바로 다음 IP 로 넘어간다.
    cur_proxy = proxy or proxy_budget.pick(proxies)
    empties = blocked = rotations = streak = not_ip_streak = 0
    empty_run = canaries = 0        # 카나리아 판별용
    kinds: dict = {}

    def rotate(cooldown: bool):
        """프록시 교체 + 세션 리셋. cooldown=True 는 하드차단·네트워크오류에만
        (빈응답은 그 IP 잘못이 아니므로 쿨다운 없이 교체만)."""
        nonlocal cur_proxy, sess, rotations, streak
        if cooldown:
            proxy_budget.mark_exhausted(cur_proxy, cooldown_sec)
        if proxies:
            nxt = proxy_budget.pick(proxies, exclude=cur_proxy)
        elif next_proxy:
            nxt = next_proxy()
        else:
            return False                # 교체 수단 없음 → 같은 IP 로 계속
        if nxt and nxt != cur_proxy:
            rotations += 1
        cur_proxy = nxt
        sess = requests.Session(impersonate="chrome")   # IP 바뀌면 세션도 새로
        streak = 0
        # empty_run 은 여기서 리셋하지 않는다. 빈응답 1회마다 로테이션이 돌기 때문에
        # 리셋하면 카나리아 임계(3연속)에 영원히 도달하지 못한다.
        # 여러 IP 에서 연달아 빈응답 = 쿼리 종속 억제 신호이므로 IP 를 넘어 누적해야 한다.
        return True

    def _canary_ok():
        """같은 세션·같은 IP 로 결과가 확실한 쿼리를 1회. True 면 세션·IP 는 정상."""
        try:
            cp = build_params(CANARY_KEYWORD, area_code, only_on_sale, None, None)
            cr = sess.get(BUYSELL, params=cp, proxy=cur_proxy,
                          headers=headers or None, timeout=8)
            ca = parse_articles(cr.text)
        except Exception:
            return False
        return bool(ca)

    def meta(tries, **extra):
        m = {"tries": tries, "empties": empties, "blocked": blocked,
             "rotations": rotations, "proxy": cur_proxy,
             "canaries": canaries,
             "kinds": dict(kinds), "diagnosis": summarize(kinds)}
        m.update(extra)
        return m

    for i in range(max_retry):
        if should_stop and should_stop():
            return [], meta(i, stopped=True)
        try:
            r = sess.get(BUYSELL, params=params, proxy=cur_proxy,
                         headers=headers or None, timeout=8)
            status, html, hdrs = r.status_code, r.text, r.headers
        except Exception:
            status, html, hdrs = None, None, None
        arts = parse_articles(html) if html is not None else None
        kind, cool = classify(status, html, arts, hdrs)
        kinds[kind] = kinds.get(kind, 0) + 1
        throttle.observe(kind)      # 차단신호면 전역 감속, 조용하면 서서히 회복

        if kind == "OK":
            return arts, meta(i + 1)
        if kind == "EMPTY":
            # 시점별 변동 → 그 IP 를 더 두드리지 말고 바로 다음 IP 로(A/B 실측).
            empties += 1
            streak += 1
            empty_run += 1
            # 빈응답이 연속되면 원인 판별: 세션·IP 문제인가, 이 쿼리만 그런가.
            if empty_run >= canary_after and canaries < canary_max:
                canaries += 1
                if _canary_ok():
                    # 같은 세션·같은 IP 로 다른 쿼리는 정상 → 재시도해봐야 헛돈다.
                    return [], meta(i + 1, suppressed=True, canary="ok")
                empty_run = 0        # 카나리아도 실패 = 진짜 차단 → 계속 재시도
            if streak >= empty_rotate_after:
                rotate(cooldown=False)
            time.sleep(throttle.scale(empty_backoff))
            continue

        blocked += 1
        if kind in NOT_IP_FAULT:
            # PARSE(구조변경)·SERVER(5xx) 는 IP 를 갈아도 안 풀린다.
            # 여러 IP 에서 연속으로 나면 더 태우지 말고 조기중단.
            not_ip_streak += 1
            if not_ip_streak >= give_up_after:
                return [], meta(i + 1, gave_up=kind)
            time.sleep(throttle.scale(empty_backoff))
            continue
        not_ip_streak = 0
        proxy_budget.mark_exhausted(cur_proxy, cool or cooldown_sec)
        rotate(cooldown=False)          # 쿨다운은 위에서 분류별 길이로 이미 걸었음
        time.sleep(throttle.scale(empty_backoff))
    # 재시도 소진 = "매물 0건" 이 아니라 "확인 실패". 호출측이 구분할 수 있게 표시한다.
    # (이 구분이 없으면 소프트차단이 조용한 누락으로 둔갑 — 실측: 샤넬 0건 ↔ 270건)
    return [], meta(max_retry, exhausted=True)


async def robust_fetch_articles_async(
    session,                            # aiohttp.ClientSession (쿠키유지=워밍업)
    keyword: str,
    area_code: str,
    proxy: str | None = None,
    only_on_sale: bool = True,
    min_price: int | None = None,
    max_price: int | None = None,
    access_token: str | None = None,
    max_retry: int = 45,          # 실측 22회 필요 사례 확인(2026-08-26) → 30 은 소진 위험
    empty_backoff: float = 0.5,   # 0.1~0.8 유의차 없음 → 중간값
    next_proxy: Callable[[], str | None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    proxies: list | None = None,
    empty_rotate_after: int = proxy_budget.EMPTY_ROTATE_AFTER,
    cooldown_sec: float = proxy_budget.COOLDOWN_SEC,
    give_up_after: int = 3,       # IP 탓 아닌 실패(PARSE/5xx) 연속 이 횟수면 조기중단
) -> tuple[list, dict]:
    """auto(aiohttp)용 — 빈응답=소프트블록 재시도. sync 판과 동일한 교체 전략.
    session 은 aiohttp.ClientSession. (실측상 세션 재사용이 성공률을 올려주진 않았다 —
    같은 세션으로 이어 붙여도 지역마다 25회/12회/1회로 요동. 재사용은 연결 재활용 이득만.)
    ※ 같은 IP 로 동시요청하면 전멸(실측 8/8 빈응답) → 레인당 1워커 순차로 호출할 것."""
    import asyncio
    from aiohttp import ClientTimeout
    params = build_params(keyword, area_code, only_on_sale, min_price, max_price)
    headers = build_headers(BUYSELL, access_token)
    cur_proxy = proxy or proxy_budget.pick(proxies)
    empties = blocked = rotations = streak = not_ip_streak = 0
    kinds: dict = {}

    def rotate(cooldown: bool):
        nonlocal cur_proxy, rotations, streak
        if cooldown:
            proxy_budget.mark_exhausted(cur_proxy, cooldown_sec)
        if proxies:
            nxt = proxy_budget.pick(proxies, exclude=cur_proxy)
        elif next_proxy:
            nxt = next_proxy()
        else:
            return False
        if nxt and nxt != cur_proxy:
            rotations += 1
        cur_proxy = nxt
        try:
            session.cookie_jar.clear()   # IP 바뀌면 이전 워밍 쿠키는 무효
        except Exception:
            pass
        streak = 0
        return True

    def meta(tries, **extra):
        m = {"tries": tries, "empties": empties, "blocked": blocked,
             "rotations": rotations, "proxy": cur_proxy,
             "kinds": dict(kinds), "diagnosis": summarize(kinds)}
        m.update(extra)
        return m

    for i in range(max_retry):
        if should_stop and should_stop():
            return [], meta(i, stopped=True)
        status = html = hdrs = None
        try:
            async with session.get(BUYSELL, params=params, proxy=cur_proxy,
                                   headers=headers or None,
                                   timeout=ClientTimeout(8)) as resp:
                status, hdrs = resp.status, resp.headers
                html = await resp.text()
        except Exception:
            pass
        arts = parse_articles(html) if html is not None else None
        kind, cool = classify(status, html, arts, hdrs)
        kinds[kind] = kinds.get(kind, 0) + 1
        throttle.observe(kind)      # 차단신호면 전역 감속, 조용하면 서서히 회복

        if kind == "OK":
            return arts, meta(i + 1)
        if kind == "EMPTY":
            empties += 1
            streak += 1
            if streak >= empty_rotate_after:
                rotate(cooldown=False)
            await asyncio.sleep(throttle.scale(empty_backoff))
            continue

        blocked += 1
        if kind in NOT_IP_FAULT:
            not_ip_streak += 1
            if not_ip_streak >= give_up_after:
                return [], meta(i + 1, gave_up=kind)
            await asyncio.sleep(throttle.scale(empty_backoff))
            continue
        not_ip_streak = 0
        proxy_budget.mark_exhausted(cur_proxy, cool or cooldown_sec)
        rotate(cooldown=False)
        await asyncio.sleep(throttle.scale(empty_backoff))
    # sync 판과 동일 — 소진은 "0건" 이 아니라 "확인 실패"
    return [], meta(max_retry, exhausted=True)

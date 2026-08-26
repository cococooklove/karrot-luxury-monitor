"""
견고한 수집 — "막힘"의 진짜 원인 대응.

실측(2026-08-26): 당근은 새 세션/IP의 **초기 요청 몇 건을 빈 페이지(0건)로 응답**하고
그 뒤 정상(수백건) 응답한다. 기존 코드는 빈 결과를 '성공(0건)'으로 처리해 재시도하지
않아 매물을 놓쳤다 = 사용자가 겪은 "당근이 막는다".

대응: 빈 결과 = 소프트블록으로 간주 → 세션 유지(쿠키) + 재시도(같은/다음 프록시).

단, 빈응답에는 두 종류가 있다:
  - **초기 워밍** — 몇 번 더 두드리면 뚫린다. 같은 IP 유지가 정답(교체하면 콜드세션 재워밍).
  - **예산 소진** — 그 IP 는 이미 스로틀. 계속 두드리면 예산이 더 나빠진다(실측).
연속 빈응답이 empty_rotate_after 를 넘으면 후자로 보고 proxy_budget 에 쿨다운을 걸고 IP 교체.
"""
from __future__ import annotations

import json
import time
from typing import Callable

from bs4 import BeautifulSoup as Soup
from curl_cffi import requests

from . import proxy_budget
from .auth import build_headers

BUYSELL = "https://www.daangn.com/kr/buy-sell/"


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
    max_retry: int = 15,
    empty_backoff: float = 0.8,
    next_proxy: Callable[[], str | None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    proxies: list | None = None,
    empty_rotate_after: int = proxy_budget.EMPTY_ROTATE_AFTER,
    cooldown_sec: float = proxy_budget.COOLDOWN_SEC,
) -> tuple[list, dict]:
    """실매물 나올 때까지 재시도. (articles, meta) 반환.
    meta = {tries, empties, blocked, rotations, proxy}. 빈응답 극복이 핵심.
    proxies 를 주면 풀에서 선택(쿨다운 중인 IP 는 제외).
    연속 빈응답이 empty_rotate_after 를 넘으면 그 IP 를 예산소진으로 보고 쿨다운+교체.
    should_stop() 이 True 면 즉시 중단(자동 모니터 정지 반응)."""
    params = build_params(keyword, area_code, only_on_sale, min_price, max_price)
    headers = build_headers(BUYSELL, access_token)     # 기본값이면 daangn엔 미주입
    sess = requests.Session(impersonate="chrome")      # 쿠키 유지 = 세션 워밍업
    # 이 요청은 한 프록시로 워밍 유지(빠름). 실패 시에만 풀에서 교체.
    cur_proxy = proxy or proxy_budget.pick(proxies)
    empties = blocked = rotations = streak = 0

    def rotate(exhausted: bool):
        """프록시 교체 + 세션 리셋. exhausted 면 그 IP 에 쿨다운."""
        nonlocal cur_proxy, sess, rotations, streak
        if exhausted:
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
        sess = requests.Session(impersonate="chrome")   # 콜드세션 재워밍
        streak = 0
        return True

    for i in range(max_retry):
        if should_stop and should_stop():
            return [], {"tries": i, "empties": empties, "blocked": blocked,
                        "rotations": rotations, "proxy": cur_proxy, "stopped": True}
        try:
            r = sess.get(BUYSELL, params=params, proxy=cur_proxy,
                         headers=headers or None, timeout=8)
        except Exception:
            blocked += 1
            rotate(exhausted=False)     # 네트워크 실패는 예산 문제 아님
            time.sleep(empty_backoff)
            continue
        arts = parse_articles(r.text)
        if arts is None:                # 차단/구조변경 = 하드
            blocked += 1
            rotate(exhausted=True)      # 하드차단은 그 IP 를 쉬게 함
            time.sleep(empty_backoff)
            continue
        if arts:                        # 정상
            return arts, {"tries": i + 1, "empties": empties, "blocked": blocked,
                          "rotations": rotations, "proxy": cur_proxy}
        # 빈응답: 초반이면 워밍(같은 IP 유지), 연속으로 쌓이면 예산소진(교체).
        empties += 1
        streak += 1
        if streak >= empty_rotate_after:
            rotate(exhausted=True)
        time.sleep(empty_backoff)
    # 재시도 소진 — 마지막까지 빈응답이었다면 그 IP 는 쉬게 둔다.
    if streak >= empty_rotate_after:
        proxy_budget.mark_exhausted(cur_proxy, cooldown_sec)
    return [], {"tries": max_retry, "empties": empties, "blocked": blocked,
                "rotations": rotations, "proxy": cur_proxy}


async def robust_fetch_articles_async(
    session,                            # aiohttp.ClientSession (쿠키유지=워밍업)
    keyword: str,
    area_code: str,
    proxy: str | None = None,
    only_on_sale: bool = True,
    min_price: int | None = None,
    max_price: int | None = None,
    access_token: str | None = None,
    max_retry: int = 15,
    empty_backoff: float = 0.8,
    next_proxy: Callable[[], str | None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    proxies: list | None = None,
    empty_rotate_after: int = proxy_budget.EMPTY_ROTATE_AFTER,
    cooldown_sec: float = proxy_budget.COOLDOWN_SEC,
) -> tuple[list, dict]:
    """auto(aiohttp)용 — 빈응답=소프트블록 재시도. 같은 session 재사용해 워밍업 1회.
    session 은 aiohttp.ClientSession(cookie_jar 기본). 여러 지역에 재사용 권장.
    sync 판과 동일하게 프록시 로테이션·예산 쿨다운 지원(교체 시 cookie_jar 를 비워 콜드세션 시작).
    ※ 같은 IP 로 동시요청하면 전멸(실측 8/8 빈응답) → 레인당 1워커 순차로 호출할 것."""
    import asyncio
    from aiohttp import ClientTimeout
    params = build_params(keyword, area_code, only_on_sale, min_price, max_price)
    headers = build_headers(BUYSELL, access_token)
    cur_proxy = proxy or proxy_budget.pick(proxies)
    empties = blocked = rotations = streak = 0

    def rotate(exhausted: bool):
        nonlocal cur_proxy, rotations, streak
        if exhausted:
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

    for i in range(max_retry):
        if should_stop and should_stop():
            return [], {"tries": i, "empties": empties, "blocked": blocked,
                        "rotations": rotations, "proxy": cur_proxy, "stopped": True}
        try:
            async with session.get(BUYSELL, params=params, proxy=cur_proxy,
                                   headers=headers or None,
                                   timeout=ClientTimeout(8)) as resp:
                html = await resp.text()
        except Exception:
            blocked += 1
            rotate(exhausted=False)
            await asyncio.sleep(empty_backoff)
            continue
        arts = parse_articles(html)
        if arts is None:
            blocked += 1
            rotate(exhausted=True)
            await asyncio.sleep(empty_backoff)
            continue
        if arts:
            return arts, {"tries": i + 1, "empties": empties, "blocked": blocked,
                          "rotations": rotations, "proxy": cur_proxy}
        empties += 1
        streak += 1
        if streak >= empty_rotate_after:
            rotate(exhausted=True)
        await asyncio.sleep(empty_backoff)
    if streak >= empty_rotate_after:
        proxy_budget.mark_exhausted(cur_proxy, cooldown_sec)
    return [], {"tries": max_retry, "empties": empties, "blocked": blocked,
                "rotations": rotations, "proxy": cur_proxy}

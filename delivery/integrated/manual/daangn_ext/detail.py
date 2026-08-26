"""
상세 페이지 수집 — 목록에 없는 필드 + **크롤 거부 판정**.

목록 응답(`robust.parse_articles`)에는 id/제목/본문/가격/썸네일/끌올/상태/지역뿐이고
판매자 정보가 아예 없다(실측: 최상위 키 11개, `user` 객체 없음). 리셀 판단에 필요한
이미지 원본·조회수·채팅수·매너온도·판매자의 다른 매물·유사매물은 전부 상세에만 있다.

동시에 **크롤 거부 신호도 상세에만 있다**:

    loaderData["routes/kr.buy-sell.$buy_sell_id"]
        .product.user.webCrawlNotAllowed   ← 판매자가 크롤 거부
        .shouldBlock                       ← 당근이 이 문서 자체를 막음

목록만 수집할 때는 판정할 방법이 없다(플래그가 응답에 없다). 상세로 확장하는 순간
이 판정이 가능해지므로, 이 모듈은 **거부 매물을 데이터로 만들지 않는다** —
`fetch_detail` 은 그런 매물에 `None` 을 돌려주고, 호출측이 세지 못하게 사유를 함께 준다.

robots.txt 상 상세 경로(`/kr/buy-sell/<슬러그>/`)는 차단 대상이 아니며 당근 사이트맵에
등재돼 있다. 차단 대상은 `/kr/buy-sell/s/*`(검색 결과) 뿐이다.
"""
from __future__ import annotations

import json
import time
from typing import Callable

from bs4 import BeautifulSoup as Soup
from curl_cffi import requests

from . import proxy_budget
from .auth import build_headers
from .block_signals import NOT_IP_FAULT, classify, summarize

BASE = "https://www.daangn.com"
ROUTE = "routes/kr.buy-sell.$buy_sell_id"


def parse_detail(html: str) -> dict | None:
    """상세 HTML → 라우트 loaderData. 실패(차단/구조변경)면 None."""
    for s in Soup(html, "html.parser").select("script"):
        if "window.__remixContext" in (s.text or ""):
            try:
                ctx = json.loads(s.text.replace("window.__remixContext = ", "").rstrip(";"))
                return ctx["state"]["loaderData"][ROUTE]
            except Exception:
                return None
    return None


def crawl_refused(route: dict) -> str | None:
    """크롤을 거부하는 신호가 있으면 사유 문자열, 없으면 None."""
    if route.get("shouldBlock"):
        return "shouldBlock"
    user = (route.get("product") or {}).get("user") or {}
    if user.get("webCrawlNotAllowed"):
        return "webCrawlNotAllowed"
    return None


def normalize(product: dict) -> dict:
    """상세 product → 표준 레코드. 목록 레코드와 합쳐 쓰기 좋은 평평한 형태."""
    user = product.get("user") or {}
    region = product.get("region") or {}
    category = product.get("category") or {}
    return {
        "id": product.get("id"),
        "db_id": product.get("dbId"),
        "node_id": product.get("nodeId"),
        "title": product.get("title"),
        "content": product.get("content"),
        "price": product.get("price"),
        "status": product.get("status"),
        "href": product.get("href"),
        "created_at": product.get("createdAt"),
        "boosted_at": product.get("boostedAt"),
        "images": product.get("images") or [],
        "view_count": product.get("viewCount"),
        "chat_count": product.get("chatCount"),
        "favorite_count": product.get("favoriteCount"),
        "adult": product.get("adultContent"),
        "region": region.get("name"),
        "region_full": " ".join(x for x in (region.get("name1"), region.get("name2"),
                                            region.get("name3")) if x),
        "category": category.get("dbId"),
        "seller_id": user.get("dbId"),
        "seller_nick": user.get("nickname"),
        "seller_score": user.get("score"),          # 매너온도
        "seller_reviews": user.get("reviewCount"),
        "seller_articles": len(user.get("userArticles") or []),
        "recommended": [a.get("id") for a in (product.get("recommendedArticles") or [])],
    }


def fetch_detail(
    href: str,
    proxy: str | None = None,
    proxies: list | None = None,
    access_token: str | None = None,
    max_retry: int = 12,
    backoff: float = 0.5,
    next_proxy: Callable[[], str | None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    session=None,
    give_up_after: int = 3,
) -> tuple[dict | None, dict]:
    """상세 1건. (레코드, meta) 반환.

    **크롤 거부 매물은 레코드 대신 None** 을 주고 `meta["refused"]` 에 사유를 담는다.
    실패와 구분되도록 `meta["ok"]` 로 요청 자체의 성공 여부를 따로 표시한다.
    목록 수집과 동일한 분류·로테이션 정책을 쓴다(빈응답 = 즉시 IP 교체, 하드차단 = 쿨다운).
    """
    url = href if href.startswith("http") else BASE + href
    headers = build_headers(url, access_token)
    sess = session or requests.Session(impersonate="chrome")
    cur = proxy or proxy_budget.pick(proxies)
    kinds: dict = {}
    rotations = not_ip = 0

    def meta(tries, **extra):
        m = {"tries": tries, "proxy": cur, "rotations": rotations,
             "kinds": dict(kinds), "diagnosis": summarize(kinds),
             "ok": False, "refused": None}
        m.update(extra)
        return m

    def rotate(cooldown: bool, cool: float = 0.0):
        nonlocal cur, sess, rotations
        if cooldown:
            proxy_budget.mark_exhausted(cur, cool or proxy_budget.COOLDOWN_SEC)
        nxt = (proxy_budget.pick(proxies, exclude=cur) if proxies
               else (next_proxy() if next_proxy else None))
        if nxt is None:
            return
        if nxt != cur:
            rotations += 1
        cur = nxt
        if session is None:                 # 주입 세션은 호출측 소유 → 건드리지 않음
            sess = requests.Session(impersonate="chrome")

    for i in range(max_retry):
        if should_stop and should_stop():
            return None, meta(i, stopped=True)
        status = html = hdrs = None
        try:
            r = sess.get(url, proxy=cur, headers=headers or None, timeout=10)
            status, html, hdrs = r.status_code, r.text, r.headers
        except Exception:
            pass
        route = parse_detail(html) if html is not None else None
        # 상세는 "매물 0건" 개념이 없다 → 라우트를 못 읽으면 articles=None 과 같은 취급
        kind, cool = classify(status, html, None if route is None else [1], hdrs)
        kinds[kind] = kinds.get(kind, 0) + 1

        if kind == "OK":
            why = crawl_refused(route)
            if why:
                return None, meta(i + 1, ok=True, refused=why)
            product = route.get("product") or {}
            return normalize(product), meta(i + 1, ok=True)
        if kind in NOT_IP_FAULT:
            not_ip += 1
            if not_ip >= give_up_after:
                return None, meta(i + 1, gave_up=kind)
            time.sleep(backoff)
            continue
        not_ip = 0
        rotate(cooldown=True, cool=cool)
        time.sleep(backoff)
    return None, meta(max_retry, exhausted=True)


def fetch_details(
    articles: list,
    proxies: list | None = None,
    lanes: int | None = None,
    access_token: str | None = None,
    should_stop: Callable[[], bool] | None = None,
    on_item: Callable[[dict, dict | None, dict], None] | None = None,
    max_lanes: int = 16,
) -> tuple[list, dict]:
    """목록 매물들의 상세를 레인 병렬로 채운다. 크롤 거부 매물은 결과에서 제외한다.

    반환 summary 의 `refused` 는 **버린 게 아니라 존중한 건수**다 — 실패(`failed`)와
    분리해 세므로, 커버리지가 낮아 보일 때 원인을 혼동하지 않는다.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from .adaptive import plan_lanes, shard_proxies

    n = plan_lanes(proxies, lanes, max_lanes)
    shards = shard_proxies(list(proxies or []), n) or [[]]
    n = len(shards)
    queue = list(articles)
    q_lock = threading.Lock()
    w_lock = threading.Lock()
    out: list = []
    stat = {"ok": 0, "refused": 0, "failed": 0, "refused_reasons": {}}

    def take():
        with q_lock:
            return queue.pop(0) if queue else None

    def lane(idx: int):
        pool = shards[idx] or None
        sess = requests.Session(impersonate="chrome")
        while True:
            if should_stop and should_stop():
                return
            art = take()
            if art is None:
                return
            rec, m = fetch_detail(art.get("href", ""), proxies=pool,
                                  access_token=access_token,
                                  should_stop=should_stop, session=sess)
            with w_lock:
                if m.get("refused"):
                    stat["refused"] += 1
                    stat["refused_reasons"][m["refused"]] = \
                        stat["refused_reasons"].get(m["refused"], 0) + 1
                elif rec is not None:
                    stat["ok"] += 1
                    out.append(rec)
                else:
                    stat["failed"] += 1
                if on_item:
                    on_item(art, rec, m)

    with ThreadPoolExecutor(max_workers=n) as ex:
        list(ex.map(lane, range(n)))

    stat["total"] = len(articles)
    stat["lanes"] = n
    stat["skipped"] = len(queue)
    return out, stat

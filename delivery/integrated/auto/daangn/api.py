"""
[AUTO] daangn/api.py 완성본 — 기존 파일 대체(drop-in, aiohttp).

기존 대비: 빈응답 재시도(robust) + access_token 주입 + 키워드 포함필터.
핵심수정: 당근 새세션 초기 빈응답을 재시도로 극복(기존은 0건 성공처리해 누락).
토큰 미설정이면 익명 그대로 — graceful. session 은 재사용(쿠키 워밍업).
"""
from datetime import datetime
from aiohttp import ClientSession
from daangn.model import Product

from daangn_ext.search_filters import KeywordRule, apply_filter
from daangn_ext.robust import robust_fetch_articles_async


async def get_regions(session: ClientSession, parent_region_id: str):
    url = f"https://www.daangn.com/v1/api/filter/kr/region/{parent_region_id}"
    async with session.get(url) as resp:
        return await resp.json()


async def find_locations(session: ClientSession, keyword: str):
    url = "https://www.daangn.com/v1/api/search/kr/location"
    async with session.get(url, params={"keyword": keyword}) as resp:
        return await resp.json()


async def get_products(
    session: ClientSession,
    area: str,
    area_code: str,
    keyword: str,
    only_tradeable: bool,
    minimum_price: int | None,
    maximum_price: int | None,
    proxy: str | None = None,
    access_token: str | None = None,        # 추가
    rule: KeywordRule | None = None,        # 추가
    proxies: list | None = None,            # 추가: 프록시 풀(쿨다운 회피 로테이션)
    next_proxy=None,                        # 추가: 로테이팅 풀 훅
    should_stop=None,                       # 추가: 정지 반응(재시도 즉시 중단)
) -> list[Product]:
    articles, meta = await robust_fetch_articles_async(
        session=session,
        keyword=keyword,
        area_code=area_code,
        proxy=proxy,
        only_on_sale=only_tradeable,
        min_price=minimum_price,
        max_price=maximum_price,
        access_token=access_token,
        proxies=proxies,
        next_proxy=next_proxy,
        should_stop=should_stop,
    )
    if not articles:
        raise Exception(f"상품 리스트 가져오기 실패 (빈응답 {meta['empties']}·차단 {meta['blocked']}, {proxy})")

    products = [
        Product(
            area=area,
            area_code=area_code,
            name=article["title"],
            price=float(article["price"] or "0"),
            imageUrl=article["thumbnail"],
            url=article["href"],
            description=article["content"],
            boostedAt=datetime.fromisoformat(article["boostedAt"]),
            keyword=None,
        )
        for article in articles
    ]
    return apply_filter(products, rule) if rule else products

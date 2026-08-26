"""
[MANUAL] daangn/api.py 완성본 — 기존 파일 대체(drop-in).

기존 대비 추가: access_token 주입(auth), 키워드 포함필터(rule). 파싱 로직 동일.
토큰 미설정이면 익명(기존 동작) 그대로 — graceful.
model.Product 는 기존 프로젝트 것 사용.
"""
from datetime import datetime
from curl_cffi import requests
from daangn.model import Product

from daangn_ext.search_filters import KeywordRule, apply_filter
from daangn_ext.robust import robust_fetch_articles


def get_regions(parent_region_id: str):
    return requests.get(
        f"https://www.daangn.com/v1/api/filter/kr/region/{str(parent_region_id)}",
        impersonate="chrome",
    ).json()


def find_locations(keyword: str):
    return requests.get(
        "https://www.daangn.com/v1/api/search/kr/location",
        impersonate="chrome",
        params={"keyword": keyword},
    ).json()


def get_products(
    area_code: str,
    area: str,
    keyword: str,
    only_tradeable: bool,
    minimum_price: int | None,
    maximum_price: int | None,
    proxy: str | None = None,
    access_token: str | None = None,        # 추가: 토큰(있으면 주입)
    rule: KeywordRule | None = None,        # 추가: 키워드 포함필터
    proxies: list | None = None,            # 추가: 프록시 풀(쿨다운 회피 로테이션)
    next_proxy=None,                        # 추가: 로테이팅 풀 훅
    should_stop=None,                       # 추가: 정지 반응(재시도 즉시 중단)
) -> list[Product]:
    # 핵심수정: 당근은 새 세션 초기요청을 빈 페이지로 응답 → robust 가 빈응답 재시도로 극복.
    # (기존은 빈 결과를 0건 성공으로 처리해 매물을 놓쳤음 = "막힘"의 정체)
    articles, meta = robust_fetch_articles(
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
        raise Exception(f"상품 리스트 가져오기 실패 (빈응답 {meta['empties']}·차단 {meta['blocked']})")

    products = [
        Product(
            no=no,
            name=article["title"],
            searched_keyword=keyword,
            price=article["price"] or "0",
            priceCurrency="KRW",
            description=article["content"],
            image=article["thumbnail"],
            url=article["href"],
            boostedAt=datetime.fromisoformat(article["boostedAt"]),
            area=area,
        )
        for no, article in enumerate(articles, 1)
    ]
    return apply_filter(products, rule) if rule else products    # 추가: 필터

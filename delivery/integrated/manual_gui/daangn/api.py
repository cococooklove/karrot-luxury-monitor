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
    proxies: list | None = None,            # 추가: 프록시 풀(매 요청 분산)
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
        should_stop=should_stop,
    )
    if should_stop and should_stop():
        return []
    if not articles:
        # 재시도 소진 = 매물이 없는 게 아니라 확인 실패. 문구로 구분해준다.
        if meta.get("exhausted"):
            raise Exception(
                f"재시도 소진 — 매물 유무 확인 실패 (빈응답 {meta['empties']}·차단 {meta['blocked']}). "
                "프록시를 늘리거나 잠시 후 재시도하세요.")
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


def get_products_adaptive(
    area: str,
    area_code: str,          # 구 코드 예 "강남구-381"
    keyword: str,
    only_tradeable: bool,
    minimum_price: int | None,
    maximum_price: int | None,
    proxy: str | None = None,
    access_token: str | None = None,
    rule: "KeywordRule | None" = None,
    proxies: list | None = None,
    should_stop=None,
) -> "list[Product]":
    """구 단위 + 가격분할 적응형 수집 → Product 리스트. 상한(290) 자동 돌파.
    proxies 풀 주면 매 요청 분산(밀집구도 빠름)."""
    from daangn_ext.adaptive import collect_region
    arts, st = collect_region(keyword, area_code, proxy=proxy,
                              only_on_sale=only_tradeable, access_token=access_token,
                              proxies=proxies, should_stop=should_stop)
    products = [
        Product(
            no=no,
            name=a["title"],
            searched_keyword=keyword,
            price=a["price"] or "0",
            priceCurrency="KRW",
            description=a["content"],
            image=a["thumbnail"],
            url=a["href"],
            boostedAt=datetime.fromisoformat(a["boostedAt"]),
            area=area,
        )
        for no, a in enumerate(arts, 1)
    ]
    if minimum_price is not None:
        products = [p for p in products if _price_int(p.price) >= minimum_price]
    if maximum_price is not None:
        products = [p for p in products if _price_int(p.price) <= maximum_price]
    return apply_filter(products, rule) if rule else products


def _price_int(v):
    try:
        return int(float(v))
    except Exception:
        return 0

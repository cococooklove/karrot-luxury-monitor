"""
통합 예제 — 기존 api.py 를 어떻게 바꾸는지 그대로 보여줌.
복붙 후 import 경로만 맞추면 동작. (기존 파싱 로직은 손대지 않음)
"""

# ═══════════════════════════════════════════════════════════════
# [MANUAL] daangn/api.py — curl_cffi 버전 get_products 패치
# ═══════════════════════════════════════════════════════════════
"""
from curl_cffi import requests
from daangn_ext import auth
from daangn_ext.search_filters import KeywordRule, apply_filter

def get_products(area_code, area, keyword, only_tradeable,
                 minimum_price, maximum_price, proxy=None,
                 access_token=None,          # ← 추가
                 rule: KeywordRule | None = None):   # ← 추가
    price = ...  # (기존 그대로)
    url = "https://www.daangn.com/kr/buy-sell/"

    headers = auth.build_headers(url, access_token)   # ← 토큰 주입(대상 호스트면)

    html = requests.get(
        url,
        params={...},          # (기존 그대로)
        impersonate="chrome",
        proxy=proxy,
        headers=headers,       # ← 추가
        timeout=10,
    ).text

    products = [...]           # (기존 remixContext 파싱 그대로)

    if rule:                                # ← 키워드 포함 필터
        products = apply_filter(products, rule)
    return products
"""

# 호출부(수동 검색 시작 버튼 핸들러):
"""
from daangn_ext import TokenManager, AccountStore, bind_to_token_manager, KeywordRule

store = AccountStore("accounts.json")       # 계정+프록시 (UI add 로 채움)
tm = TokenManager()
bind_to_token_manager(store, tm)

tm.refresh_all()                            # ← 검색 전 토큰 일괄 갱신(30분 만료 방지)

rule = KeywordRule(required=[keyword],
                   extra=extra_keywords, extra_mode="and",
                   exclude=exclude_keywords)

for acc in tm.accounts.values():
    token = tm.ensure(acc)                  # ← 요청 직전 재확인(만료 임박이면 갱신)
    prds = get_products(..., proxy=acc.proxy, access_token=token, rule=rule)
"""


# ═══════════════════════════════════════════════════════════════
# [AUTO] daangn/api.py + 루프 — aiohttp 버전
# ═══════════════════════════════════════════════════════════════
"""
from daangn_ext import auth
from daangn_ext.search_filters import KeywordRule, apply_filter

async def get_products(session, area, area_code, keyword, only_tradeable,
                       minimum_price, maximum_price, proxy=None,
                       access_token=None, rule=None):     # ← 추가
    url = "https://www.daangn.com/kr/buy-sell/"
    headers = auth.build_headers(url, access_token)       # ← 토큰 주입
    async with session.get(url, params={...}, proxy=proxy,
                           headers=headers, timeout=ClientTimeout(10)) as resp:
        html = await resp.text()
    products = [...]                                       # (기존 파싱)
    return apply_filter(products, rule) if rule else products
"""

# 24시간 루프(run_all / worker 상위):
"""
from daangn_ext import TokenManager, AccountStore, bind_to_token_manager, asleep_between

store = AccountStore("accounts.json")
tm = TokenManager()
bind_to_token_manager(store, tm)

while True:
    tm.refresh_all()                        # ← 매 사이클 검색 전 토큰 갱신
    for acc in tm.accounts.values():
        token = tm.ensure(acc)
        # ... 조건별 검색 → DB/텔레그램 (기존 로직) ...
    await asleep_between(REST_MIN, REST_MAX) # ← 반복 전 휴식 n~n초 랜덤
"""

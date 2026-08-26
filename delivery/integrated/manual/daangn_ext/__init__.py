"""
daangn_ext — 기존 manual/auto 수집기에 얹는 드롭인 확장.

클라 요구기능 매핑:
  검색 전 토큰 갱신(30분 만료 대응)  → token_manager.TokenManager
  계정+프록시 직접 추가              → account_store.AccountStore
  키워드 + 추가키워드 포함 필터       → search_filters.KeywordRule
  검색 반복 전 휴식 n~n초 랜덤        → rest_scheduler
  토큰 요청 주입(헤더/호스트 설정)    → auth.build_headers
  IP 요청예산·쿨다운(스로틀 회피)     → proxy_budget
통합 방법: integration_examples.py + DELIVERY.md
"""
from .token_manager import TokenManager, Account, token_exp, token_code
from .account_store import AccountStore, bind_to_token_manager
from .search_filters import KeywordRule, apply_filter
from .rest_scheduler import sleep_between, asleep_between
from .robust import (robust_fetch_articles, robust_fetch_articles_async,
                     parse_articles, build_params)
from .adaptive import (collect_region, collect_nationwide, load_gu_regions,
                       collect_region_async, collect_nationwide_async)
from . import auth, proxy_budget

__all__ = [
    "TokenManager", "Account", "token_exp", "token_code",
    "AccountStore", "bind_to_token_manager",
    "KeywordRule", "apply_filter",
    "sleep_between", "asleep_between", "auth", "proxy_budget",
    "robust_fetch_articles", "robust_fetch_articles_async",
    "parse_articles", "build_params",
    "collect_region", "collect_nationwide", "load_gu_regions",
    "collect_region_async", "collect_nationwide_async",
]

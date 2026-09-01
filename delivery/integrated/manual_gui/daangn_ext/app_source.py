"""앱 API 수집 소스 — 자동 모니터가 웹 대신 앱 API 로 수집하게 하는 어댑터.

collect_region(웹)과 시그니처를 맞춰, 모니터가 소스만 바꿔 끼우면 되게 한다.
반환도 (articles, stats) 로 동일. articles 는 web parse_articles 와 같은 dict 형태
(app_api.to_article 로 정규화)라 downstream(필터·중복제거·알림·GUI)은 그대로 재사용.

토큰 만료 시:
  - refresh 가 설정돼 있으면(TokenManager 연동) 자동 재발급 후 재시도
  - 아니면 stats["token_expired"]=True 로 표시하고 그 지역은 건너뛴다(크래시 없음)
"""
from __future__ import annotations

from typing import Callable

from . import proxy_budget
from .app_api import AppApiConfig, collect, to_article, TokenExpired


def _ip_fault(e: BaseException) -> bool:
    """이 실패가 'IP 탓'인가 — 쿨다운을 걸어도 되는가.

    웹 경로의 판단(block_signals.NOT_IP_FAULT = {PARSE, SERVER})과 맞춘다:
    5xx 는 당근 서버 문제라 IP 를 갈아도 안 풀리고, 여기에 쿨다운을 걸면
    멀쩡한 IP 가 통째로 풀에서 빠져 풀이 말라버린다(proxy_budget 독스트링).
    전송단 오류(status=None: 프록시 연결실패·타임아웃)와 4xx(403/429 차단)만 IP 탓으로 본다.
    """
    st = getattr(e, "status", None)
    return not (isinstance(st, int) and 500 <= st < 600)

# 좌표 미상 지역용 기본 좌표(서울 시청 근처). regionId 가 결과를 지배하는지
# 실측 전까지의 임시값 — 좌표가 중요하다고 판명되면 동별 좌표표로 교체한다.
DEFAULT_LAT, DEFAULT_LON = 37.5666, 126.9784


class AppSource:
    """앱 API 기반 수집 소스. 모니터에 주입한다."""

    def __init__(self, config_path: str = "./data/config.json",
                 refresh_fn: Callable[[], str] | None = None,
                 region_coords: dict | None = None,
                 max_pages: int = 200,
                 log: Callable[[str], None] | None = None):
        self.cfg = AppApiConfig(config_path)
        self.refresh_fn = refresh_fn          # () -> new access token
        self.region_coords = region_coords or {}   # {regionId: (lat, lon)}
        self.max_pages = max_pages
        self._log = log or (lambda m: None)

    def _coords(self, region_id: str):
        return self.region_coords.get(str(region_id), (DEFAULT_LAT, DEFAULT_LON))

    def _try_refresh(self) -> bool:
        if not self.refresh_fn:
            return False
        try:
            new = self.refresh_fn()
        except Exception as e:
            self._log(f"[토큰 갱신 실패] {type(e).__name__}: {e}")
            return False
        if not new:
            return False
        self.cfg.set_access_token(new)
        self._log("[토큰 갱신] 새 access 토큰 반영")
        return True

    def collect_region(self, keyword: str, region_in: str, *,
                       only_on_sale: bool = True,
                       proxy: str | None = None,
                       proxies=None, access_token=None,
                       should_stop: Callable[[], bool] | None = None,
                       **_ignored) -> tuple[list, dict]:
        """웹 collect_region 과 같은 형태. region_in 은 '역삼동-6035' → 뒤 숫자가 regionId.

        프록시 선택 규칙 — **웹 경로와 동일**하게 `proxy_budget.pick(proxies)` 로
        지역 시작 시 IP 하나를 고르고 그 지역 순회 내내 고정한다.
        근거: adaptive.collect_region:98 의 `proxy or proxy_budget.pick(proxies)`,
        adaptive.collect_region_async:261 도 같은 관례다. pick 은 쿨다운 중인 IP 를
        후보에서 빼고 나머지 중 랜덤(proxy_budget.pick) — 순환이 아니라 랜덤인 이유는
        레인들이 같은 순서로 돌면 IP 가 겹치기 때문(proxy_budget 독스트링).
        proxies 가 None/빈리스트면 pick 이 None 을 반환 → 지금처럼 직결(예외 없음).

        실패 처리도 **웹 경로와 동일**하게 한다:
        robust.py:190 이 실패한 IP 에 `proxy_budget.mark_exhausted` 로 쿨다운을 걸고,
        adaptive.collect_region 의 exhausted 분기(:190)가
        `pick(proxies, exclude=fixed_proxy)` 로 갈아탄 뒤 **1회 더** 시도한다.
        앱 경로에 이게 없으면 고른 IP 가 죽었을 때 그 지역이 곧장 웹크롤로 떨어지고
        (명품 억제 → '샤넬' 0건), 그 죽은 IP 가 다음 지역에서 또 뽑힌다.
        stabilize(레인당 고정 IP 1개)면 그 사이클 전 지역이 웹크롤로 떨어진다.
        재시도까지 실패하면 예외를 그대로 올려 adaptive 가 웹크롤로 폴백한다(안전망 유지).
        """
        region_id = region_in.rsplit("-", 1)[-1] if "-" in region_in else region_in
        lat, lon = self._coords(region_id)
        use_proxy = proxy or proxy_budget.pick(proxies)

        def _run(p):
            docs, st = collect(self.cfg, keyword, region_id, lat, lon,
                               max_pages=self.max_pages, should_stop=should_stop,
                               proxy=p)
            if st.get("stopped_by") == "token":
                if self._try_refresh() and not (should_stop and should_stop()):
                    docs, st = collect(self.cfg, keyword, region_id, lat, lon,
                                       max_pages=self.max_pages, should_stop=should_stop,
                                       proxy=p)
            return docs, st

        try:
            docs, st = _run(use_proxy)
        except Exception as e:
            # 프록시를 안 쓰는 직결이면 쿨다운·교체 대상 자체가 없다 → 지금처럼 그대로 올린다.
            if not use_proxy or not proxies:
                raise
            if _ip_fault(e):
                proxy_budget.mark_exhausted(use_proxy)
            alt = proxy_budget.pick(proxies, exclude=use_proxy)
            if not alt or alt == use_proxy:
                # 갈아탈 IP 가 없다(풀이 1개거나 전부 쿨다운) → 폴백에 맡긴다.
                raise
            self._log(f"[앱API 재시도] {type(e).__name__} — IP 교체 {use_proxy} → {alt}")
            docs, st = _run(alt)          # 여기서 또 실패하면 예외가 그대로 올라가 웹크롤 폴백
            use_proxy = alt

        arts = [to_article(d) for d in docs.values()]
        stats = {
            "requests": st.get("pages", 0),
            "pages": st.get("pages", 0),
            "stopped_by": st.get("stopped_by"),
            "token_expired": st.get("stopped_by") == "token",
            "proxy": use_proxy,
            # 웹 소스와 키를 맞춰 모니터가 동일 코드로 처리.
            # saturated/splits 가 빠지면 collect_lanes 의 st["saturated"] 가
            # KeyError 로 레인을 통째로 죽인다(앱API 성공 시에도).
            "saturated": False, "splits": 0,
            "missed": [], "suppressed": 0, "expanded": [], "empties": 0,
        }
        return arts, stats

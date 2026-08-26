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

from .app_api import AppApiConfig, collect, to_article, TokenExpired

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
                       proxies=None, access_token=None,
                       should_stop: Callable[[], bool] | None = None,
                       **_ignored) -> tuple[list, dict]:
        """웹 collect_region 과 같은 형태. region_in 은 '역삼동-6035' → 뒤 숫자가 regionId."""
        region_id = region_in.rsplit("-", 1)[-1] if "-" in region_in else region_in
        lat, lon = self._coords(region_id)

        docs, st = collect(self.cfg, keyword, region_id, lat, lon,
                           max_pages=self.max_pages, should_stop=should_stop)
        if st.get("stopped_by") == "token":
            if self._try_refresh() and not (should_stop and should_stop()):
                docs, st = collect(self.cfg, keyword, region_id, lat, lon,
                                   max_pages=self.max_pages, should_stop=should_stop)

        arts = [to_article(d) for d in docs.values()]
        stats = {
            "requests": st.get("pages", 0),
            "pages": st.get("pages", 0),
            "stopped_by": st.get("stopped_by"),
            "token_expired": st.get("stopped_by") == "token",
            # 웹 소스와 키를 맞춰 모니터가 동일 코드로 처리
            "missed": [], "suppressed": 0, "expanded": [], "empties": 0,
        }
        return arts, stats

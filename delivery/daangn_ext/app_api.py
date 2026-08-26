"""당근 앱 API 클라이언트 — 중고거래 검색.

웹 SSR 경로의 한계를 전부 없앤다:
  - 브랜드 키워드 억제 없음 (웹: '샤넬' 0건 / 앱: 1,198건+)
  - 페이지네이션 있음 (웹: ~285건 상한, 페이징 불가)
  - 반경 기반이라 인접 동이 자동으로 딸려온다

인증: authorization(JWT) + 디바이스 헤더. **서명/HMAC 없음** → 헤더 재현만으로 호출된다.
헤더 실값은 data/config.json (권한 0600, gitignore). 스펙은 docs/APP_API.md 참고.

주의 — pageToken:
  응답은 `nextToken` 으로 주지만 요청은 **`pageToken`** 으로 보내야 한다.
  `nextToken` 으로 보내면 에러 없이 1페이지가 재반환된다(조용한 중복).
  실측: 잘못된 이름으로 40페이지 순회 → 유니크 33건.
"""
from __future__ import annotations

import json
import os
import time
from typing import Callable

from curl_cffi import requests

SEARCH_URL = "https://search-bff.kr.karrotmarket.com/api/v5/fleamarket/search"
COORD_TYPE = "USER_COORDINATE_TYPE_REGION_CENTER_COORDINATE"
PAGE_SIZE = 20              # 서버 고정
DEFAULT_CONFIG = "./data/config.json"

# 헤더가 없으면 호출 자체가 안 되는 것들
REQUIRED_HEADERS = ("authorization", "x-device-identity", "x-user-agent")


class TokenExpired(RuntimeError):
    """액세스 토큰 만료(401). 갱신 후 재시도해야 한다."""


class AppApiConfig:
    """캡처에서 추출한 헤더 묶음. data/config.json 에서 읽는다."""

    def __init__(self, path: str = DEFAULT_CONFIG):
        self.path = path
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        self.headers = dict(raw.get("headers") or {})
        self.headers.setdefault("x-search-tab", "fleamarket")
        missing = [h for h in REQUIRED_HEADERS if h not in self.headers]
        if missing:
            raise ValueError(f"{path} 에 필수 헤더 없음: {missing} — 캡처를 다시 하세요")

    def set_access_token(self, token: str) -> None:
        """토큰 갱신 후 반영 + 파일에도 기록."""
        self.headers["authorization"] = token if token.lower().startswith("bearer ") \
            else f"Bearer {token}"
        raw = {"endpoint": SEARCH_URL, "headers": self.headers}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def token_expires_in(self) -> int:
        """액세스 토큰 잔여 초. 판단 불가면 -1."""
        import base64
        tok = (self.headers.get("authorization") or "").split()[-1]
        parts = tok.split(".")
        if len(parts) != 3:
            return -1
        try:
            pad = parts[1] + "=" * (-len(parts[1]) % 4)
            exp = json.loads(base64.urlsafe_b64decode(pad)).get("exp")
            return int(exp - time.time()) if exp else -1
        except Exception:
            return -1


def _spatial(region_id: str, lat: float, lon: float) -> dict:
    return {
        "region": {"regionId": str(region_id)},
        "userCoordinates": [{
            "type": COORD_TYPE,
            "coordinate": {"latitude": lat, "longitude": lon},
        }],
    }


def build_body(keyword: str, region_id: str, lat: float, lon: float,
               page_token: str | None = None,
               without_completed: bool = True) -> dict:
    """검색 요청 본문.

    spatialContext 를 **루트와 fleaMarket.filter 양쪽에** 넣어야 한다.
    하나라도 빠지면 422 (서버가 빠진 필드명을 그대로 알려준다).
    """
    body = {
        "query": keyword,
        "fleaMarket": {"filter": {
            "withoutCompleted": without_completed,
            "spatialContext": _spatial(region_id, lat, lon),
        }},
        "spatialContext": _spatial(region_id, lat, lon),
    }
    if page_token:
        body["pageToken"] = page_token      # ← nextToken 아님. 위 독스트링 참고
    return body


def _post(cfg: AppApiConfig, body: dict, timeout: int = 20, retries: int = 2):
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(SEARCH_URL, json=body, headers=cfg.headers,
                              impersonate="safari_ios", timeout=timeout)
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 401:
            raise TokenExpired("액세스 토큰 만료 — 갱신 필요")
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(3 * (attempt + 1))
            last = RuntimeError(f"HTTP {r.status_code}")
            continue
        return r
    raise RuntimeError(f"요청 실패: {last}")


def search_page(cfg: AppApiConfig, keyword: str, region_id: str,
                lat: float, lon: float, page_token: str | None = None) -> tuple[list, str | None, bool]:
    """한 페이지. (문서 리스트, nextToken, hasNextPage)."""
    body = build_body(keyword, region_id, lat, lon, page_token)
    r = _post(cfg, body)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    j = r.json()
    docs = [it["document"] for it in j.get("results", [])
            if isinstance(it, dict) and it.get("document")]
    return docs, j.get("nextToken"), bool(j.get("hasNextPage"))


def collect(cfg: AppApiConfig, keyword: str, region_id: str,
            lat: float, lon: float,
            max_pages: int = 200,
            gap: float = 0.25,
            should_stop: Callable[[], bool] | None = None) -> tuple[dict, dict]:
    """한 지역 전량 수집. ({id: document}, stats).

    stats: pages, requests, stopped_by
      stopped_by = 'end' | 'max_pages' | 'duplicate' | 'stopped' | 'token'
    """
    seen: dict = {}
    token = None
    pages = 0
    why = "end"
    while pages < max_pages:
        if should_stop and should_stop():
            why = "stopped"
            break
        try:
            docs, token, has_next = search_page(cfg, keyword, region_id, lat, lon, token)
        except TokenExpired:
            why = "token"
            break
        pages += 1
        before = len(seen)
        for d in docs:
            if d.get("id"):
                seen[str(d["id"])] = d
        if not has_next or not token:
            why = "end"
            break
        if len(seen) == before:
            # 새 매물이 하나도 안 늘면 페이징이 헛도는 것(파라미터명 오류의 증상).
            why = "duplicate"
            break
        if gap:
            time.sleep(gap)
    else:
        why = "max_pages"
    return seen, {"pages": pages, "requests": pages, "stopped_by": why}


def to_article(doc: dict) -> dict:
    """앱 API document → 기존 파이프라인이 쓰는 매물 dict 로 정규화.

    웹 파서(parse_articles) 출력과 키를 맞춰 downstream(필터·중복제거·알림)을
    그대로 재사용한다.
    """
    img = doc.get("firstImage") or {}
    aid = str(doc.get("id", ""))
    return {
        "id": aid,
        "title": doc.get("title", ""),
        "content": doc.get("content", "") or "",
        "price": doc.get("price") or (doc.get("priceInfo") or {}).get("price") or "0",
        "thumbnail": img.get("url", ""),
        "href": f"https://www.daangn.com/kr/buy-sell/-{aid}/" if aid else "",
        "region": doc.get("regionName", ""),
        "boostedAt": doc.get("publishedAt") or doc.get("createdAt") or "",
        "createdAt": doc.get("createdAt") or "",
        "status": doc.get("status", ""),
        "category": doc.get("categoryId", ""),
        # 앱에만 있는 신호 — 시세·수요 판단에 쓴다
        "watchesCount": doc.get("watchesCount", 0),
        "chatRoomsCount": doc.get("chatRoomsCount", 0),
        "republishCount": doc.get("republishCount", 0),
    }

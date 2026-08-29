"""매물 단건 추적 — 가격변동·판매완료·삭제·끌올 감지.

단건 조회: GET https://webapp.kr.karrotmarket.com/api/v24/articles/{id}.json
Bearer 토큰만 필요(WAF 아님). 묶음 조회는 없다 — articles.json 은 어떤 파라미터
조합이든 invalid_params 를 돌려준다. 따라서 1건 1요청이고, 요청량은 추적 대상 수와
점검 주기로만 조절한다.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sqlite3
import time

import httpx

from .keyword_alert_api import WEBAPP, _headers, token_remaining

WEBAPP_ARTICLE_PATH = "/api/v24/articles/{id}.json"

STATUS_ONGOING = "ongoing"
STATUS_RESERVED = "reserved"
STATUS_CLOSED = "closed"

FRESH_AGE = 48 * 3600
AGED_AGE = 14 * 24 * 3600
FRESH_INTERVAL = 4 * 3600
AGED_INTERVAL = 24 * 3600
ACTIVE_CAP = 300
DAILY_CAP_PER_ACCOUNT = 300
MAX_FAIL = 5
RATE_LIMIT_DELAY = 1800
MIN_TOKEN_REMAINING = 120


def parse_iso(s) -> int:
    """ISO8601(+09:00 포함) → epoch 초. 판단 불가면 0."""
    if not s or not isinstance(s, str):
        return 0
    try:
        return int(_dt.datetime.fromisoformat(s).timestamp())
    except ValueError:
        return 0


def _int(v, default=0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def normalize(payload: dict, article_id: str) -> dict:
    """단건 조회 응답 → 표준 dict. 사라진 매물이면 gone=True 하나만 담는다."""
    art = payload.get("article") if isinstance(payload.get("article"), dict) else payload
    gone = bool(art.get("destroyed_at")) or bool(art.get("is_unpublished")) \
        or art.get("visible") is False
    if gone:
        return {"id": str(article_id), "gone": True}
    return {
        "id": str(art.get("id") or article_id),
        "gone": False,
        "title": art.get("title") or "",
        "price": _int(art.get("price")),
        "status": art.get("status") or "",
        "status_name": art.get("status_name") or "",
        "region": art.get("display_region_name") or art.get("display_location_name") or "",
        "url": art.get("permalink") or f"https://www.daangn.com/kr/buy-sell/-{article_id}/",
        "published_at": parse_iso(art.get("published_at") or art.get("created_at")),
        "updated_at": parse_iso(art.get("updated_at")),
        "republish_count": _int(art.get("republish_count")),
        "watches_count": _int(art.get("watches_count")),
        "chat_rooms_count": _int(art.get("chat_rooms_count")),
        "reads_count": _int(art.get("reads_count")),
    }


class ArticleDetailAPI:
    """계정 1개(access token)로 매물 단건을 조회한다."""

    def __init__(self, access_token: str, config_path: str = "./data/config.json",
                 proxy: str | None = None, client: httpx.Client | None = None):
        self.token = access_token
        self.headers = _headers(access_token, config_path)
        self._own_client = client is None
        self._client = client or httpx.Client(http2=True, timeout=20, proxy=proxy)

    def fetch(self, article_id: str) -> dict:
        """정규화된 dict. 사라졌으면 {"id":..., "gone": True}.
        401/429/5xx 는 httpx.HTTPStatusError 로 올린다."""
        url = f"https://{WEBAPP}{WEBAPP_ARTICLE_PATH.format(id=article_id)}"
        r = self._client.get(url, headers=self.headers)
        if r.status_code in (404, 410):
            return {"id": str(article_id), "gone": True}
        r.raise_for_status()
        return normalize(r.json() or {}, str(article_id))

    def close(self) -> None:
        if self._own_client:
            try:
                self._client.close()
            except Exception:
                pass

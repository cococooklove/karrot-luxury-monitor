"""당근 키워드 알림 API — 확정 스펙 (2026-08-27 실측, Mac 토큰으로 CRUD 성공).

호스트: webapp.kr.karrotmarket.com (WAF 아님, 검색과 동일 토큰/헤더)
  목록  GET    /api/v24/keyword/user_keywords.json
  등록  POST   /api/v24/keyword/user_keywords.json   body {keyword, min_price?, max_price?, exclude_keywords?[], category_ids?[]}
  삭제  DELETE /api/v24/keyword/user_keywords/{id}.json
  차단확인 GET  search-bff.kr.karrotmarket.com/api/v1/fleamarket/keyword/notification/info?keyword=

계정당 subscription_infos = 인증 동네 + ranged_regions_count(예: 역삼동 39지역) → 1계정이 넓게 커버.
매칭(신규매물)은 푸시로 옴 → notification_listener 로 수신(앱 온라인 필요).
"""
from __future__ import annotations

import base64
import json
import os
import time
from typing import Callable

import httpx

WEBAPP = "webapp.kr.karrotmarket.com"
SEARCH_BFF = "search-bff.kr.karrotmarket.com"
UK_PATH = "/api/v24/keyword/user_keywords.json"
UK_DEL = "/api/v24/keyword/user_keywords/{id}.json"
INFO_PATH = "/api/v1/fleamarket/keyword/notification/info"
DEFAULT_UA = "Karrot/26.34.0 (com.towneers.www; build:263400; Android 33)"


def _headers(access_token: str, config_path: str = "./data/config.json") -> dict:
    h = {"accept": "application/json", "content-type": "application/json",
         "x-user-agent": DEFAULT_UA, "authorization": f"Bearer {access_token}"}
    try:
        cfg = json.load(open(config_path, encoding="utf-8")).get("headers", {})
        for k in ("x-user-agent", "user-agent", "x-device-identity", "x-ad-id",
                  "x-country-code", "x-karrot-session-id", "accept-language"):
            if k in cfg:
                h[k] = cfg[k]
    except Exception:
        pass
    return h


def token_remaining(access_token: str) -> int:
    try:
        p = access_token.split(".")[1]; p += "=" * (-len(p) % 4)
        return int(json.loads(base64.urlsafe_b64decode(p)).get("exp", 0) - time.time())
    except Exception:
        return -1


class KeywordAlertAPI:
    """계정 1개(access token)의 키워드 알림 CRUD."""

    def __init__(self, access_token: str, config_path: str = "./data/config.json",
                 proxy: str | None = None):
        self.token = access_token
        self.headers = _headers(access_token, config_path)
        self._client = httpx.Client(http2=True, timeout=20, proxy=proxy)

    # ── 목록 (+구독 동네 정보) ──
    def list(self) -> dict:
        r = self._client.get(f"https://{WEBAPP}{UK_PATH}", headers=self.headers)
        r.raise_for_status()
        return r.json()

    def keywords(self) -> list[dict]:
        return self.list().get("user_keywords") or []

    def subscriptions(self) -> list[dict]:
        """등록된 동네 + 커버 지역수."""
        return self.list().get("subscription_infos") or []

    # ── 차단 키워드 확인 ──
    def is_banned(self, keyword: str) -> bool:
        r = self._client.get(f"https://{SEARCH_BFF}{INFO_PATH}", headers=self.headers,
                             params={"keyword": keyword})
        if r.status_code != 200:
            return False
        d = r.json()
        return bool(d.get("isBannedKeyword") or d.get("isNotificationBannedKeyword"))

    # ── 등록 ──
    def register(self, keyword: str, min_price=None, max_price=None,
                 exclude_keywords=None, category_ids=None) -> dict:
        body = {"keyword": keyword,
                "min_price": min_price, "max_price": max_price,
                "exclude_keywords": exclude_keywords or [],
                "category_ids": category_ids or []}
        r = self._client.post(f"https://{WEBAPP}{UK_PATH}", headers=self.headers,
                              content=json.dumps(body, ensure_ascii=False).encode())
        r.raise_for_status()
        return r.json().get("user_keyword") or r.json()

    def register_many(self, keywords: list[str], min_price=None, max_price=None,
                      exclude_keywords=None, skip_existing=True,
                      log: Callable[[str], None] | None = None) -> dict:
        log = log or (lambda m: None)
        existing = {k.get("keyword") for k in self.keywords()} if skip_existing else set()
        added, skipped, failed = [], [], []
        for kw in keywords:
            if kw in existing:
                skipped.append(kw); continue
            try:
                if self.is_banned(kw):
                    failed.append((kw, "차단키워드")); log(f"  {kw}: 차단됨"); continue
                self.register(kw, min_price, max_price, exclude_keywords)
                added.append(kw); log(f"  {kw}: 등록 ✓")
                time.sleep(0.6)
            except Exception as e:
                failed.append((kw, str(e)[:60])); log(f"  {kw}: 실패 {str(e)[:40]}")
        return {"added": added, "skipped": skipped, "failed": failed}

    # ── 삭제 ──
    def delete(self, user_keyword_id: str) -> bool:
        url = f"https://{WEBAPP}{UK_DEL.format(id=user_keyword_id)}"
        r = self._client.delete(url, headers=self.headers)
        return r.status_code in (200, 204)

    def delete_all(self, log: Callable[[str], None] | None = None) -> int:
        log = log or (lambda m: None)
        n = 0
        for k in self.keywords():
            if self.delete(k.get("id")):
                n += 1; log(f"  삭제 ✓ {k.get('keyword')}")
        return n

    def close(self):
        try:
            self._client.close()
        except Exception:
            pass

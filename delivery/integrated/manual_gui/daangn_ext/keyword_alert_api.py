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
import re
from typing import Callable

import httpx

WEBAPP = "webapp.kr.karrotmarket.com"
SEARCH_BFF = "search-bff.kr.karrotmarket.com"
INBOX_BFF = "inbox-bff.kr.karrotmarket.com"           # 알림함 telefunc RPC
TELEFUNC_FILE = "/src/services/notification/notification.telefunc.ts"
INBOX_ORIGIN = "https://inbox.kr.karrotwebview.com"
INBOX_UA = "TowneersApp/26.34.0/263400 Android/13/33"
UK_PATH = "/api/v24/keyword/user_keywords.json"
UK_DEL = "/api/v24/keyword/user_keywords/{id}.json"
INFO_PATH = "/api/v1/fleamarket/keyword/notification/info"
DEFAULT_UA = "Karrot/26.34.0 (com.towneers.www; build:263400; Android 33)"
FLEA_CATEGORY = "2"                                    # 중고거래 카테고리(명품 매물)


def _debigint(v):
    """telefunc 직렬화 '!BigInt:123' → '123'."""
    if isinstance(v, str) and v.startswith("!BigInt:"):
        return v[len("!BigInt:"):]
    return v


def _detag(x):
    """검색 하이라이트 <b>..</b> 등 태그 제거."""
    if not isinstance(x, str):
        return x
    return re.sub(r"<[^>]+>", "", x).strip()


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

    # ── 알림함 telefunc (매칭 폴링) ──
    def _telefunc(self, name: str, args: list):
        h = dict(self.headers)
        h["content-type"] = "text/plain"
        h["x-user-agent"] = INBOX_UA
        h["origin"] = INBOX_ORIGIN
        h["referer"] = INBOX_ORIGIN + "/"
        body = json.dumps({"file": TELEFUNC_FILE, "name": name, "args": args},
                          ensure_ascii=False)
        r = self._client.post(f"https://{INBOX_BFF}/_telefunc", headers=h,
                              content=body.encode())
        r.raise_for_status()
        return (r.json() or {}).get("ret")

    def new_matches(self, category_id: str = FLEA_CATEGORY) -> list[dict]:
        """키워드 알림 신규 매칭(명품 매물) 폴링 → 파싱된 매물 리스트.
        토큰만으로 됨(앱/푸시 불필요). 각 item: keyword/title/price/region/article_id/url/image/time."""
        ret = self._telefunc("invokeListNewMatchesNotifications",
                             [{"categoryId": str(category_id)}]) or {}
        out = []
        for it in ret.get("notificationInboxItems") or []:
            kv = ((((it.get("style") or {}).get("style")) or {}).get("value")) or {}
            aid = kv.get("articleId")
            out.append({
                "keyword": kv.get("matchedKeyword"),
                "title": _detag(it.get("title")),
                "price": kv.get("priceWithUnit"),
                "region": kv.get("regionName"),
                "article_id": aid,
                "url": f"https://www.daangn.com/kr/buy-sell/-{aid}/" if aid else
                       (it.get("landingDeeplinkUrl") or ""),
                "image": it.get("thumbnailImageUrl"),
                "time": _debigint((it.get("createTime") or {}).get("seconds")),
                "id": _debigint(it.get("id")),
                "instant_buy": kv.get("isInstantBuyAvailable"),
                "source": "keyword",
            })
        # 스폰서(neighborhood) 매물도 매칭이면 포함
        for ad in ret.get("neighborhoodAdvertisements") or []:
            aid = _debigint(ad.get("articleId"))
            out.append({
                "keyword": ad.get("matchedKeyword"), "title": _detag(ad.get("title")),
                "price": ad.get("priceWithUnit"), "region": ad.get("regionName"),
                "article_id": aid,
                "url": f"https://www.daangn.com/kr/buy-sell/-{aid}/" if aid else
                       (ad.get("landingDeeplinkUrl") or ""),
                "image": ad.get("thumbnailImageUrl"),
                "time": _debigint((ad.get("createTime") or {}).get("seconds")),
                "id": _debigint(ad.get("id")), "source": "ad",
            })
        return out

    def new_matches_count(self, category_id: str = FLEA_CATEGORY) -> int:
        ret = self._telefunc("invokeGetNewMatchesNotificationSettingsData",
                             [{"categoryId": str(category_id)}]) or {}
        return int(ret.get("count") or 0)

    def close(self):
        try:
            self._client.close()
        except Exception:
            pass


class MultiAccountAlerts:
    """전 계정(accounts.json) 대상 키워드 알림 — 전국 모니터링.

    각 계정은 자기 인증동네+반경(예 39지역)만 커버 → 여러 계정 = 여러 동네 = 전국.
    유효 토큰(만료 안 된 access) 있는 계정만 참여. 만료분은 스킵(수확 필요).
    """

    def __init__(self, accounts_fp: str = "./accounts.json",
                 config_path: str = "./data/config.json"):
        self.accounts_fp = accounts_fp
        self.config_path = config_path

    def _accounts(self):
        try:
            return json.load(open(self.accounts_fp, encoding="utf-8"))
        except Exception:
            return []

    def _valid(self):
        """(code, access, proxy) 리스트 — access 살아있는 계정만."""
        out = []
        for a in self._accounts():
            acc = a.get("access") or ""
            if acc and token_remaining(acc) > 60:
                out.append((str(a.get("code") or ""), acc, a.get("proxy")))
        return out

    def register_all(self, keywords, min_price=None, max_price=None,
                     exclude_keywords=None, log=None):
        log = log or (lambda m: None)
        valid = self._valid()
        log(f"유효 계정 {len(valid)}개 (만료계정 제외)")
        total = {"added": 0, "skipped": 0, "failed": 0}
        for code, access, proxy in valid:
            log(f"── 계정 {code[:6]} ──")
            api = KeywordAlertAPI(access, self.config_path, proxy=proxy)
            try:
                res = api.register_many(keywords, min_price, max_price,
                                        exclude_keywords, log=log)
                for k in total:
                    total[k] += len(res[k])
            except Exception as e:
                log(f"  계정 {code[:6]} 실패: {str(e)[:50]}")
            finally:
                api.close()
        log(f"전체: 등록 {total['added']} · 스킵 {total['skipped']} · 실패 {total['failed']}")
        return total

    def poll_all(self, category_id: str = FLEA_CATEGORY, log=None, workers: int = 12):
        """전 계정 매칭 폴링(병렬) → 합산(article_id 중복제거). 각 매물 _account 태그.
        병렬이라 계정 100개여도 1순환 수초(주기 유지)."""
        log = log or (lambda m: None)
        from concurrent.futures import ThreadPoolExecutor

        def one(acct):
            code, access, proxy = acct
            api = KeywordAlertAPI(access, self.config_path, proxy=proxy)
            try:
                res = api.new_matches(category_id)
                for m in res:
                    m["_account"] = code[:6]
                return res
            except Exception as e:
                log(f"  {code[:6]} 폴 실패: {str(e)[:40]}")
                return []
            finally:
                api.close()

        valid = self._valid()
        seen, merged = set(), []
        with ThreadPoolExecutor(max_workers=min(workers, max(1, len(valid)))) as ex:
            for res in ex.map(one, valid):
                for m in res:
                    key = m.get("article_id") or m.get("id")
                    if key in seen:
                        continue
                    seen.add(key); merged.append(m)
        log(f"전계정({len(valid)}) 매칭 {len(merged)}건(중복제거)")
        return merged

    def coverage(self, log=None):
        """전 계정 커버 동네 집계 → [(code, 동네명, 지역수)]."""
        log = log or (lambda m: None)
        out = []
        for code, access, proxy in self._valid():
            api = KeywordAlertAPI(access, self.config_path, proxy=proxy)
            try:
                for s in api.subscriptions():
                    out.append((code[:6], s.get("name"), s.get("ranged_regions_count")))
            except Exception as e:
                log(f"  {code[:6]} 실패: {str(e)[:40]}")
            finally:
                api.close()
        return out

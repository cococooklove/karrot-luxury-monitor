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


def _atomic_json(path, obj):
    """원자적 JSON 저장(temp+rename) — 동시 읽기 중 부분쓰기 방지. 성공 bool."""
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


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
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f).get("headers", {})
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
        out = {"added": added, "skipped": skipped, "failed": failed}
        if failed:
            # 실패가 하나라도 있으면 이 계정의 실 보유수를 함께 넘긴다.
            # 차단 키워드인지 한도 초과인지 반환값만으로는 구분 못 하니
            # 추측하지 않고, 서버가 들고 있는 진짜 개수를 라우터에 넘긴다.
            #
            # skip_existing 경로(라우터가 쓰는 유일한 경로)에서는 이미
            # 답을 갖고 있다: existing 은 이 함수 진입 때 받아온 계정의 전체
            # 목록이고 added 는 그 뒤 이 호출이 새로 넣은 것뿐이다 → 지금
            # 보유수 = len(existing)+len(added). 여기서 목록을 다시 조회하면
            # 차단 키워드 한 개가 전 계정에 실패하는 가장 흔한 경로에서
            # 요청이 계정마다 하나씩 더 늘어난다(33~50%).
            if skip_existing:
                out["account_count"] = len(existing) + len(added)
            else:
                # existing 을 안 받아온 경우에만 실측이 필요하다.
                try:
                    out["account_count"] = len(self.keywords())
                except Exception:
                    pass
        return out

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
            with open(self.accounts_fp, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    # 명품 밀집 핵심지역(인증동네명에 포함되면 core). 20-30계정으로 거래량 대부분 커버.
    CORE_REGION_KEYWORDS = [
        "강남", "서초", "송파", "청담", "압구정", "논현", "역삼", "삼성", "대치", "반포",
        "잠원", "잠실", "한남", "성수", "용산", "여의도", "목동",
        "분당", "판교", "정자", "수지", "광교", "영통",
        "해운대", "수영", "센텀", "수성", "봉무", "유성",
    ]
    _REGION_CACHE_FP = "./data/account_regions.json"

    def _region_cache(self):
        try:
            with open(self._REGION_CACHE_FP, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_region_cache(self, cache):
        _atomic_json(self._REGION_CACHE_FP, cache)

    _CORE_FP = "./data/core_regions.json"

    def core_keywords(self):
        """핵심지역 키워드 — 파일(사용자 편집) 우선, 없으면 기본값."""
        try:
            with open(self._CORE_FP, encoding="utf-8") as f:
                v = json.load(f)
            if isinstance(v, list) and v:
                return [str(x).strip() for x in v if str(x).strip()]
        except Exception:
            pass
        return list(self.CORE_REGION_KEYWORDS)

    def save_core_keywords(self, keywords):
        return _atomic_json(self._CORE_FP, list(keywords))

    def _is_core(self, region_name):
        r = region_name or ""
        return any(k in r for k in self.core_keywords())

    def _valid(self, core_only=False):
        """(code, access, proxy) 리스트 — access 살아있는 계정만.
        core_only=True 면 인증동네가 명품 밀집 핵심지역인 계정만(지역명 캐시, 최초 1회 조회)."""
        alive = []
        for a in self._accounts():
            acc = a.get("access") or ""
            if acc and token_remaining(acc) > 60:
                alive.append((str(a.get("code") or ""), acc, a.get("proxy")))
        if not core_only:
            return alive
        cache = self._region_cache()
        dirty = False
        out = []
        for code, access, proxy in alive:
            name = cache.get(code)
            if name is None:                    # 최초 조회 → 캐시
                try:
                    api = KeywordAlertAPI(access, self.config_path, proxy=proxy)
                    subs = api.subscriptions(); api.close()
                    name = (subs[0].get("name") if subs else "") or ""
                except Exception:
                    name = ""
                cache[code] = name; dirty = True
            if self._is_core(name):
                out.append((code, access, proxy))
        if dirty:
            self._save_region_cache(cache)
        return out

    def register_all(self, keywords, min_price=None, max_price=None,
                     exclude_keywords=None, log=None, core_only=False):
        log = log or (lambda m: None)
        valid = self._valid(core_only)
        log(f"유효 계정 {len(valid)}개 (만료계정 제외)")
        total = {"added": 0, "skipped": 0, "failed": 0}
        observed_count = None    # 실패가 난 계정들 중 실측된 보유수의 최댓값
        for code, access, proxy in valid:
            log(f"── 계정 {code[:6]} ──")
            api = KeywordAlertAPI(access, self.config_path, proxy=proxy)
            try:
                res = api.register_many(keywords, min_price, max_price,
                                        exclude_keywords, log=log)
                for k in total:
                    total[k] += len(res[k])
                if "account_count" in res:
                    n = res["account_count"]
                    observed_count = n if observed_count is None else max(observed_count, n)
            except Exception as e:
                log(f"  계정 {code[:6]} 실패: {str(e)[:50]}")
            finally:
                api.close()
        log(f"전체: 등록 {total['added']} · 스킵 {total['skipped']} · 실패 {total['failed']}")
        # added/skipped/failed 세 키는 그대로 둔다 — main.py 와 라우터가 이미
        # 이 모양으로 읽는다. 관측치는 나란히 얹기만 한다.
        if observed_count is not None:
            total["observed_count"] = observed_count
        return total

    def poll_all(self, category_id: str = FLEA_CATEGORY, log=None, workers: int = 12,
                 core_only=False):
        """전 계정 매칭 폴링(병렬) → 합산(article_id 중복제거). 각 매물 _account 태그.
        병렬이라 계정 100개여도 1순환 수초(주기 유지)."""
        log = log or (lambda m: None)
        from concurrent.futures import ThreadPoolExecutor

        state = self._state()

        def one(acct):
            code, access, proxy = acct
            api = KeywordAlertAPI(access, self.config_path, proxy=proxy)
            try:
                res = api.new_matches(category_id)
                for m in res:
                    m["_account"] = code[:6]
                st = state.setdefault(code, {})
                st["fail"] = 0; st["last_ok"] = int(time.time())
                st["last_err"] = ""; st["banned"] = False
                return res
            except Exception as e:
                st = state.setdefault(code, {})
                st["fail"] = int(st.get("fail", 0)) + 1
                st["last_err"] = str(e)[:80]
                if st["fail"] >= 5:                    # 연속 5회 실패 → 밴/불량 계정 격리표시
                    st["banned"] = True
                log(f"  {code[:6]} 폴 실패({st['fail']}회): {str(e)[:40]}")
                return []
            finally:
                api.close()

        valid = self._valid(core_only)
        seen, merged = set(), []
        with ThreadPoolExecutor(max_workers=min(workers, max(1, len(valid)))) as ex:
            for res in ex.map(one, valid):
                for m in res:
                    key = m.get("article_id") or m.get("id")
                    if key in seen:
                        continue
                    seen.add(key); merged.append(m)
        self._save_state(state)
        log(f"전계정({len(valid)}) 매칭 {len(merged)}건(중복제거)")
        return merged

    # ── 계정 상태(폴링 성공/실패·밴 격리) 영속 ──
    _STATE_FP = "./data/account_state.json"

    def _state(self):
        try:
            with open(self._STATE_FP, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_state(self, state):
        _atomic_json(self._STATE_FP, state)

    def reset_state(self):
        """계정 폴링 상태(실패/점검플래그) 초기화 — 오탐(토큰만료로 인한 실패 등) 해소용."""
        self._save_state({})
        return True

    def fleet_status(self):
        """팜 운영용 계정별 상태(무-네트워크: accounts.json + 지역/상태 캐시).
        [{code, region, exp_min, alive, core, fail, banned, last_err}]."""
        rcache = self._region_cache()
        state = self._state()
        out = []
        for a in self._accounts():
            code = str(a.get("code") or "")
            acc = a.get("access") or ""
            rem = token_remaining(acc) if acc else -1
            region = rcache.get(code, "")
            st = state.get(code, {})
            out.append({
                "code": code[:6],
                "region": region or "?",
                "exp_min": rem // 60 if rem > 0 else (0 if acc else -1),
                "alive": rem > 60,
                "core": self._is_core(region),
                "fail": int(st.get("fail", 0)),
                "banned": bool(st.get("banned")),
                "last_err": st.get("last_err", ""),
            })
        # 만료·불량 먼저 보이게 정렬(살아있고 문제없는 계정 뒤로)
        out.sort(key=lambda r: (r["alive"], not r["banned"], r["exp_min"]))
        return out

    def coverage(self, log=None, core_only=False):
        """전 계정 커버 동네 집계 → [(code, 동네명, 지역수)]."""
        log = log or (lambda m: None)
        out = []
        for code, access, proxy in self._valid(core_only):
            api = KeywordAlertAPI(access, self.config_path, proxy=proxy)
            try:
                for s in api.subscriptions():
                    out.append((code[:6], s.get("name"), s.get("ranged_regions_count")))
            except Exception as e:
                log(f"  {code[:6]} 실패: {str(e)[:40]}")
            finally:
                api.close()
        return out

"""키워드를 앱 API 슬롯 또는 검색 스윕으로 자동 배정한다.

사용자는 키워드만 넣는다. 어느 경로로 잡히는지는 라우터가 정하고, 화면에는
진단용으로만 보여준다. 경로를 고르게 하면 사용자가 슬롯 산수를 해야 한다.

슬롯 계산: register_all 은 같은 키워드를 모든 유효 계정에 등록한다. 계정을
늘려도 등록 가능한 키워드 '종류'는 늘지 않는다 — 함대 전체 한도가 곧 계정당
상한이다. 그래서 used 는 앱으로 배정된 키워드 수이고 네트워크 조회가 없다.
"""
from __future__ import annotations

import json
import os
import time

DEFAULT_SLOT_CAP = 30

ROUTE_APP = "app"
ROUTE_SWEEP = "sweep"


class KeywordRouter:
    def __init__(self, alerts, queue, slot_cap: int = DEFAULT_SLOT_CAP,
                 routes_fp: str = "./data/keyword_routes.json"):
        self.alerts = alerts
        self.queue = queue
        self.slot_cap = int(slot_cap)
        self.routes_fp = routes_fp
        self._routes = self._load()

    # ── 영속 ──
    def _load(self) -> dict:
        try:
            with open(self.routes_fp, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        out = {}
        for k, v in data.items():
            if isinstance(v, dict) and v.get("route") in (ROUTE_APP, ROUTE_SWEEP):
                out[str(k)] = {"route": v["route"],
                               "reason": str(v.get("reason") or ""),
                               "at": int(v.get("at") or 0)}
        return out

    def _save(self) -> None:
        try:
            d = os.path.dirname(self.routes_fp)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(self.routes_fp, "w", encoding="utf-8") as f:
                json.dump(self._routes, f, ensure_ascii=False)
        except Exception:
            pass

    # ── 조회 ──
    def capacity(self) -> dict:
        used = sum(1 for v in self._routes.values() if v["route"] == ROUTE_APP)
        return {"cap": self.slot_cap, "used": used,
                "free": max(0, self.slot_cap - used)}

    def routes(self) -> list[dict]:
        return [dict(v, keyword=k) for k, v in
                sorted(self._routes.items(), key=lambda kv: kv[1].get("at") or 0)]

    # ── 배정 ──
    def add(self, keyword, min_price=None, max_price=None, exclude=None,
            core_only=False, log=None) -> dict:
        log = log or (lambda m: None)
        keyword = str(keyword or "").strip()
        now = int(time.time())
        if not keyword:
            return {"keyword": keyword, "route": ROUTE_SWEEP, "reason": "빈 키워드"}

        if self.capacity()["free"] <= 0:
            return self._to_sweep(keyword, min_price, max_price, exclude, now,
                                  f"앱 슬롯 만원({self.slot_cap})", log)
        try:
            res = self.alerts.register_all(
                [keyword], min_price, max_price, exclude,
                log=log, core_only=core_only) or {}
        except Exception as e:
            return self._to_sweep(keyword, min_price, max_price, exclude, now,
                                  f"등록 실패: {str(e)[:60]}", log)
        if not res.get("added") and res.get("failed"):
            # 차단 키워드거나 전 계정에서 거절됐다. 스윕은 이 제약을 안 받는다.
            return self._to_sweep(keyword, min_price, max_price, exclude, now,
                                  "앱 등록 실패(차단 키워드 등)", log)

        self.queue.remove(keyword)
        self._routes[keyword] = {"route": ROUTE_APP, "reason": "앱 알림 등록",
                                 "at": now}
        self._save()
        return {"keyword": keyword, "route": ROUTE_APP, "reason": "앱 알림 등록"}

    def add_many(self, keywords, min_price=None, max_price=None, exclude=None,
                 core_only=False, log=None) -> list[dict]:
        return [self.add(k, min_price, max_price, exclude, core_only, log)
                for k in keywords or []]

    def _to_sweep(self, keyword, min_price, max_price, exclude, now, reason,
                  log) -> dict:
        self.queue.add(keyword, min_price, max_price, exclude, at=now)
        self._routes[keyword] = {"route": ROUTE_SWEEP, "reason": reason, "at": now}
        self._save()
        log(f"  {keyword}: 검색 스윕으로 — {reason}")
        return {"keyword": keyword, "route": ROUTE_SWEEP, "reason": reason}

    def remove(self, keyword) -> None:
        keyword = str(keyword)
        self.queue.remove(keyword)
        if self._routes.pop(keyword, None) is not None:
            self._save()

    def rebalance(self, core_only=False, log=None) -> list[dict]:
        """앱 슬롯이 비면 대기열 최고참을 승격한다. 강등은 하지 않는다."""
        free = self.capacity()["free"]
        if free <= 0 or not len(self.queue):
            return []
        out = []
        for entry in self.queue.oldest(free):
            res = self.add(entry["keyword"], entry.get("min"), entry.get("max"),
                           entry.get("exclude"), core_only=core_only, log=log)
            if res["route"] == ROUTE_APP:
                out.append(res)
            else:
                break               # 여전히 안 되면 다음 회차로
        return out

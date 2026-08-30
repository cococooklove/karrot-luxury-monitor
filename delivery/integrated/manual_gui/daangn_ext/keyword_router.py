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

# 등록이 실패한 키워드는 지수 백오프로만 다시 시도한다. 재시도 한 번이
# '전 계정 × (목록조회 + 차단조회 + 등록)' 이라 계정 12개면 수십 요청이다.
# 차단 키워드처럼 영영 안 되는 것에 이 값을 매 폴링(120초)마다 태우면
# 하루 수만 요청이 된다.
RETRY_BASE = 3600
RETRY_MAX = 24 * 3600


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
                e = {"route": v["route"],
                     "reason": str(v.get("reason") or ""),
                     "at": int(v.get("at") or 0)}
                # 백오프는 재시작으로 초기화되면 안 된다 — 껐다 켜기만 하면
                # 무한 재시도가 되살아난다.
                try:
                    ra = int(v.get("retry_after") or 0)
                except Exception:
                    ra = 0
                if ra:
                    e["retry_after"] = ra
                    try:
                        e["retry_n"] = max(1, int(v.get("retry_n") or 1))
                    except Exception:
                        e["retry_n"] = 1
                out[str(k)] = e
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

    def seed_from_server(self, keywords) -> int:
        """routes 파일이 없던 첫 실행에서, 서버에 이미 등록돼 있는 키워드를
        app 슬롯으로 인정한다.

        이 브랜치 이전의 일괄등록 경로로 계정마다 30개가 차 있어도 라우터는
        used=0 으로 본다. 그 상태로 등록하면 서버 한도에 부딪혀 전부 실패하고
        스윕으로 밀린 뒤, 매 폴링마다 재시도된다.

        서버 목록은 호출자가 이미 읽어 온 것을 넘긴다 — 라우터는 네트워크를
        갖지 않는다."""
        if self._routes:
            return 0
        now = int(time.time())
        n = 0
        for kw in keywords or []:
            kw = str(kw or "").strip()
            if not kw or kw in self._routes:
                continue
            self._routes[kw] = {"route": ROUTE_APP,
                                "reason": "서버에 이미 등록됨(첫 실행 인식)",
                                "at": now}
            n += 1
        if n:
            self._save()
        return n

    # ── 배정 ──
    def add(self, keyword, min_price=None, max_price=None, exclude=None,
            core_only=False, log=None) -> dict:
        log = log or (lambda m: None)
        keyword = str(keyword or "").strip()
        now = int(time.time())
        if not keyword:
            return {"keyword": keyword, "route": None, "reason": "빈 키워드"}

        if self.capacity()["free"] <= 0:
            return self._to_sweep(keyword, min_price, max_price, exclude, now,
                                  f"앱 슬롯 만원({self.slot_cap})", log)
        try:
            res = self.alerts.register_all(
                [keyword], min_price, max_price, exclude,
                log=log, core_only=core_only) or {}
        except Exception as e:
            return self._to_sweep(keyword, min_price, max_price, exclude, now,
                                  f"등록 실패: {str(e)[:60]}", log, failed=True)
        # added 든 skipped 든 하나는 있어야 실제로 등록된 것이다. skipped 는 이미
        # 그 계정에 등록돼 있다는 뜻이라 성공으로 친다. 전부 0 이면 유효 계정이
        # 없었다는 뜻인데, 이때 app 으로 표시하면 슬롯만 먹고 아무데서도 감시되지
        # 않는다 — 느리더라도 스윕이 낫다.
        if not (res.get("added") or res.get("skipped")):
            return self._to_sweep(keyword, min_price, max_price, exclude, now,
                                  "앱 등록 실패(차단 키워드·유효 계정 없음)", log,
                                  failed=True)

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
                  log, failed: bool = False) -> dict:
        prev = self._routes.get(keyword) or {}
        entry = {"route": ROUTE_SWEEP, "reason": reason, "at": now}
        if failed:
            # 실패 횟수만큼 지수적으로 물린다. 슬롯 만원처럼 시도조차 안 한
            # 경우는 실패가 아니므로 백오프를 새로 물리지 않는다.
            n = int(prev.get("retry_n") or 0) + 1
            entry["retry_n"] = n
            entry["retry_after"] = now + min(RETRY_MAX,
                                             RETRY_BASE * (2 ** (n - 1)))
        elif prev.get("retry_after"):
            entry["retry_n"] = int(prev.get("retry_n") or 1)
            entry["retry_after"] = int(prev["retry_after"])
        self.queue.add(keyword, min_price, max_price, exclude, at=now)
        self._routes[keyword] = entry
        self._save()
        log(f"  {keyword}: 검색 스윕으로 — {reason}")
        return {"keyword": keyword, "route": ROUTE_SWEEP, "reason": reason}

    def retry_after(self, keyword) -> int:
        return int((self._routes.get(str(keyword)) or {}).get("retry_after") or 0)

    def remove(self, keyword) -> None:
        keyword = str(keyword)
        self.queue.remove(keyword)
        if self._routes.pop(keyword, None) is not None:
            self._save()

    def rebalance(self, core_only=False, log=None) -> list[dict]:
        """앱 슬롯이 비면 대기열 최고참을 승격한다. 강등은 하지 않는다.

        승격에 실패한 키워드는 (a) 백오프가 풀릴 때까지 건너뛰고 (b) 큐 맨 뒤로
        보낸다. 둘 다 없으면 못 들어가는 키워드 하나가 큐 머리에 눌러앉아
        매 틱 재시도되면서, 뒤에 있는 멀쩡한 키워드는 영영 승격되지 않는다."""
        free = self.capacity()["free"]
        if free <= 0 or not len(self.queue):
            return []
        now = int(time.time())
        out = []
        for entry in self.queue.oldest(len(self.queue)):
            if len(out) >= free:
                break
            kw = entry["keyword"]
            if self.retry_after(kw) > now:
                continue            # 백오프 중 — 이번 틱은 요청을 쓰지 않는다
            res = self.add(kw, entry.get("min"), entry.get("max"),
                           entry.get("exclude"), core_only=core_only, log=log)
            if res["route"] == ROUTE_APP:
                out.append(res)
            else:
                self.queue.touch(kw)    # 머리를 비켜준다
                continue                # 한 건 실패가 나머지를 막지 않는다
        return out

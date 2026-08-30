"""키워드를 앱 API 슬롯 또는 검색 스윕으로 자동 배정한다.

사용자는 키워드만 넣는다. 어느 경로로 잡히는지는 라우터가 정하고, 화면에는
진단용으로만 보여준다. 경로를 고르게 하면 사용자가 슬롯 산수를 해야 한다.

슬롯 계산: register_all 은 같은 키워드를 모든 유효 계정에 등록한다. 계정을
늘려도 등록 가능한 키워드 '종류'는 늘지 않는다 — 함대 전체 한도가 곧 계정당
상한이다. 그래서 used 는 앱으로 배정된 키워드 수이고 네트워크 조회가 없다.

상한은 하드코딩이 아니라 관측값이다: 서버 상한이 설정값(기본 30)보다 낮으면
등록이 매번 실패하는데도 라우터는 계속 여유가 있다고 믿고 재시도한다.
register_all 의 반환에 "fleet_full"(그 실패가 차단 키워드가 아니라 함대
한도에 부딪힌 것이라는 신호)이 있으면, 그 시점의 used 를 유효 상한으로
낮춰 캐시한다. 이 신호가 없으면(현재 실제 구현은 아직 보내지 않는다) 절대
낮추지 않는다 — 차단 키워드 실패를 한도 축소로 오인하면 실제로 있는 슬롯을
스윕으로 묶어버리기 때문이다. 관측값은 절대 스스로 오르지 않고,
reset_observed_cap() 으로만 되돌린다.
"""
from __future__ import annotations

import json
import os
import time

DEFAULT_SLOT_CAP = 30

ROUTE_APP = "app"
ROUTE_SWEEP = "sweep"

# routes 파일에 라우트 항목과 함께 저장되는 예약 키(상한 관측치). 실제
# 키워드는 절대 이 문자열과 같을 수 없다 — add() 의 keyword.strip() 을
# 거치므로 공백을 포함한 이 값은 사용자가 입력할 수 없다.
_CAP_META_KEY = "  __cap__"

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
        self._routes, self._observed_cap = self._load()

    # ── 영속 ──
    def _load(self) -> tuple[dict, int | None]:
        try:
            with open(self.routes_fp, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {}, None
        if not isinstance(data, dict):
            return {}, None
        observed = None
        meta = data.get(_CAP_META_KEY)
        if isinstance(meta, dict):
            try:
                v = int(meta.get("observed"))
                if v > 0:
                    observed = v
            except Exception:
                observed = None
        out = {}
        for k, v in data.items():
            if k == _CAP_META_KEY:
                continue
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
        return out, observed

    def _save(self) -> None:
        try:
            d = os.path.dirname(self.routes_fp)
            if d:
                os.makedirs(d, exist_ok=True)
            payload = dict(self._routes)
            if self._observed_cap is not None:
                payload[_CAP_META_KEY] = {"observed": self._observed_cap}
            with open(self.routes_fp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
        except Exception:
            pass

    # ── 조회 ──
    def capacity(self) -> dict:
        used = sum(1 for v in self._routes.values() if v["route"] == ROUTE_APP)
        cap = self.slot_cap
        if self._observed_cap is not None and self._observed_cap < cap:
            cap = self._observed_cap
        return {"cap": cap, "used": used, "free": max(0, cap - used)}

    def _observe_cap_full(self, log) -> None:
        """등록 실패가 '함대 한도 도달' 신호일 때만 호출된다(add 참고).
        그 시점에 이미 app 배정된 키워드 수가 곧 진짜 상한이다 — 그보다
        낮게 다시 관측되지 않는 한 갱신하지 않는다(오직 하강만)."""
        used = self.capacity()["used"]
        if self._observed_cap is not None and self._observed_cap <= used:
            return
        prev = self._observed_cap if self._observed_cap is not None else self.slot_cap
        self._observed_cap = used
        self._save()
        log(f"  ⚠ 앱 슬롯 상한 관측치 하향: {prev} → {used}"
            f"(서버가 등록을 거부함 — reset_observed_cap() 으로 되돌릴 수 있음)")

    def reset_observed_cap(self, log=None) -> bool:
        """관측으로 낮아진 유효 상한을 되돌린다 — 일시적 서버 오류·오탐으로
        낮아진 경우 운영자가 빠져나갈 구멍. seed_from_server 는 routes 가
        비어 있을 때만 동작해 관측치가 있는 상태에선 거의 열리지 않으므로,
        평시 탈출 경로는 이 메서드다."""
        if self._observed_cap is None:
            return False
        self._observed_cap = None
        self._save()
        if log:
            log("  앱 슬롯 상한 관측치 초기화")
        return True

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
            # routes 가 비어 씨딩이 열렸다는 것 자체가 서버 상태를 다시
            # 믿기로 한 것이다 — 남아 있던 관측 상한(예: 예전에 다 지워진
            # 뒤에도 파일에 남았던 값)도 같이 씻어낸다.
            self._observed_cap = None
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

        cap_now = self.capacity()
        if cap_now["free"] <= 0:
            return self._to_sweep(keyword, min_price, max_price, exclude, now,
                                  f"앱 슬롯 만원({cap_now['cap']})", log)
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
            # fleet_full 은 alerts 가 "이 실패는 차단 키워드가 아니라 함대
            # 한도 때문"이라고 명시했을 때만 켜진다. 신호가 없으면(현재의
            # 실제 구현이 그렇다) 관측하지 않는다 — 차단 키워드 실패를
            # 한도로 오인하면 멀쩡한 슬롯을 스윕에 묶어버린다.
            if res.get("failed") and res.get("fleet_full"):
                self._observe_cap_full(log)
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

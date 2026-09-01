"""키워드를 앱 API 슬롯 또는 검색 스윕으로 자동 배정한다.

사용자는 키워드만 넣는다. 어느 경로로 잡히는지는 라우터가 정하고, 화면에는
진단용으로만 보여준다. 경로를 고르게 하면 사용자가 슬롯 산수를 해야 한다.

슬롯 계산: register_all 은 같은 키워드를 모든 유효 계정에 등록한다. 계정을
늘려도 등록 가능한 키워드 '종류'는 늘지 않는다 — 함대 전체 한도가 곧 계정당
상한이다. 그래서 used 는 앱으로 배정된 키워드 수이고 네트워크 조회가 없다.

상한은 하드코딩이 아니라 관측값이다: 서버 상한이 설정값(기본 30)보다 낮으면
등록이 매번 실패하는데도 라우터는 계속 여유가 있다고 믿고 재시도한다.

실패 사유(차단 키워드 vs 진짜 한도 초과)는 register_all 의 반환값만으로는
구분할 수 없다 — keyword_alert_api.register_many 는 이 둘을 내부적으로는
구분해 알고 있지만 register_all 이 계정별 결과를 세 정수(added/skipped/
failed)로 뭉개면서 사유가 사라진다. 그래서 사유를 추측하는 대신, 실패한
계정이 실제로 몇 개의 키워드를 들고 있는지(KeywordAlertAPI 가 이미 받아온
목록에서 센 값, register_all 의 "observed_count")를 근거로 쓴다.

'만원'의 정의는 이 클래스에 하나뿐이다: 이번 거부가 함대 한도 때문이라고
볼 근거가 있으면 지금 이 순간 남은 슬롯은 0 이다 → 관측 상한은 그때의
used 다(_observe_cap_full 이 유일한 결론 지점). 실측값은 '상한 값'이
아니라 '근거'로만 쓴다 — 서버 실보유수에는 이 라우터가 모르는 키워드
(이 브랜치 이전 일괄등록분 등)가 섞여 있어 그건 라우터가 쓸 수 있는
슬롯수가 아니다. 실측 20 을 그대로 상한으로 삼으면 used=15 에서 free=5
가 되는데, 그 5 는 영영 채워지지 않는다(등록이 계속 거부되니 used 가
안 오르고, used 가 안 오르니 더 낮은 관측도 못 받는다) — 상한이 수렴하지
않고 매 틱 재시도만 태우는 원인이었다.

근거로 인정하는 조건: used 가 0 보다 크고, 실측값이 used 이상. "우리가
밀어 넣었다고 믿는 만큼은 그 계정이 실제로 갖고 있는데도 이번 등록은
거부당했다" — 남은 슬롯이 0 이라는 직접 신호다. 실측값 < used 는 그
계정이 아직 다른 계정만큼 못 따라간 것일 수 있어(막 유효해진 계정 등)
근거가 아니다 — 차단 키워드가 실패한 계정이 겨우 2개를 갖고 있다고 해서
상한이 2 라는 뜻은 아니다. 뒤처짐과 상한 도달을 구분 못 하면 오탐이다.
used 가 아직 0(성공 이력 없음)이면 비교 기준이 없으므로 건너뛴다.

register_all 이 명시적으로 "fleet_full"(그 실패가 차단이 아니라 함대
한도 때문이라는 신호)을 보낼 수도 있다 — 지금의 실제 구현은 보내지
않지만, 더 나은 증거가 생기면 그대로 쓸 자리를 남겨둔다.

관측값은 절대 스스로 오르지 않는다. 되돌리는 길은 reset_observed_cap() 하나이고,
운영자에게는 그것이 GUI 고급 패널의 [슬롯 상한 초기화] 버튼과 헤드리스의
--reset-cap 플래그로 나 있다.
"""
from __future__ import annotations

import json
import os
import time

DEFAULT_SLOT_CAP = 30

def _clean_cond(raw) -> dict:
    """디스크에서 읽은 조건을 쓸 수 있는 모양으로만 남긴다.

    사람이 손댈 수 있는 파일이라 모양을 믿지 않는다. 다만 **버리지도 않는다** —
    이 함수가 생긴 이유가 조건이 조용히 사라지던 것이라, 읽을 수 있는 값은
    최대한 살린다. 못 읽는 항목만 빠진다."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key in ("min", "max"):
        v = raw.get(key)
        if v is None:
            continue
        try:
            out[key] = int(v)
        except (TypeError, ValueError):
            pass
    for key in ("exclude", "extra"):
        v = raw.get(key)
        if isinstance(v, (list, tuple)):
            vals = [str(x) for x in v if str(x).strip()]
            if vals:
                out[key] = vals
        elif isinstance(v, str) and v.strip():
            out[key] = [v.strip()]
    d = raw.get("days")
    if d is not None:
        try:
            d = int(d)
            if d > 0:
                out["days"] = d
        except (TypeError, ValueError):
            pass
    return out


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
    @staticmethod
    def _clean_cond(raw):
        return _clean_cond(raw)

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
                # 조건도 반드시 살려 읽는다. 예전에는 여기서 통째로 버려서
                # **껐다 켜기만 해도** 엑셀 조건이 사라졌다 — 실서버에서
                # 20/20 키워드가 조건 없이 남아 있던 진짜 이유다. 클라는
                # 엑셀을 넣은 적이 있는데도 매번 다시 넣어야 했다.
                cond = _clean_cond(v.get("cond"))
                if cond:
                    e["cond"] = cond
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

    def _observe_cap_full(self, log, why: str = "서버가 등록을 거부함") -> None:
        """'만원'의 유일한 결론 지점 — 이번 거부가 함대 한도 때문이라고 볼
        근거가 있을 때만 호출된다(add·_observe_measured_full 참고).

        그 시점에 app 으로 배정된 키워드 수가 곧 이 라우터가 쓸 수 있는
        슬롯의 전부다: 더 밀어 넣을 수 없다는 게 방금 확인됐으니 남은
        슬롯은 0 이다. 그보다 낮게 다시 관측되지 않는 한 갱신하지
        않는다(오직 하강만)."""
        used = self.capacity()["used"]
        if self._observed_cap is not None and self._observed_cap <= used:
            return
        prev = self._observed_cap if self._observed_cap is not None else self.slot_cap
        self._observed_cap = used
        self._save()
        log(f"  ⚠ 앱 슬롯 상한 관측치 하향: {prev} → {used}"
            f"({why} — 잘못 내려갔으면 고급 패널 [슬롯 상한 초기화],"
            " 서버는 --reset-cap 으로 되돌릴 것)")

    def _observe_measured_full(self, count, used_before: int, log) -> None:
        """실측값(register_all 의 observed_count)이 '함대 한도 도달'의
        근거인지만 판정한다. 근거면 결론은 _observe_cap_full 이 낸다 —
        '만원'의 뜻이 두 갈래로 갈리지 않게 결론 지점은 하나뿐이다.

        add() 가 이 실패를 만나기 직전에 잰 used_before 를 그대로 받는다
        (그 사이 라우트가 바뀌지 않았다).

        차단 키워드인지 한도 초과인지는 register_all 의 반환만으로 절대
        구분이 안 된다(모듈 docstring 참고) — 그래서 실패 사유를 보는 대신
        이 부등식만 본다:

          count < used_before  → 근거 아님, 버림.
            이 계정이 다른 계정만큼 아직 못 따라간 것일 수 있다(막 유효해진
            계정 등). '적게 갖고 있다'는 것 자체는 상한의 근거가 아니다 —
            차단 키워드가 실패한 계정이 겨우 2개를 갖고 있다고 해서 상한이
            2 라는 뜻은 아니다. 뒤처짐과 상한 도달을 구분 못 하면 오탐이다.

          count >= used_before  → 근거. 우리가 이 계정에 밀어 넣었다고 믿는
            만큼은 실제로도 갖고 있는데("따라잡음") 이번 등록은 거부됐다.
            남은 슬롯이 0 이라는 직접 신호이므로 상한을 used 로 내린다.
            count 자체를 상한으로 삼지 않는 이유는 모듈 docstring 참고 —
            그 값에는 라우터가 모르는 키워드가 섞여 있어 수렴하지 않는다.

        used_before<=0(성공 이력이 아예 없음)이면 비교 기준이 없어 건너뛴다."""
        try:
            count = int(count)
        except Exception:
            return
        if used_before <= 0 or count < used_before:
            return
        self._observe_cap_full(
            log, why=f"계정 실 보유수 {count}개 확인, 그런데도 거부됨")

    def reset_observed_cap(self, log=None) -> bool:
        """관측으로 낮아진 유효 상한을 되돌린다 — 일시적 서버 오류·오탐으로
        낮아진 경우 운영자가 빠져나갈 구멍. seed_from_server 는 routes 가
        비어 있을 때만 동작해 관측치가 있는 상태에선 거의 열리지 않으므로,
        평시 탈출 경로는 이 메서드다.

        운영자가 닿는 문은 둘이다: GUI 고급 패널의 [슬롯 상한 초기화] 버튼
        (MainWindow.on_reset_cap_clicked)과 헤드리스의 --reset-cap 플래그."""
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
    # 당근에는 상한을 이 배수만큼 넉넉히 걸어 등록한다. 상한을 그대로 넘기면
    # 지금 비싼 매물은 당근이 알림 자체를 안 보내고, 나중에 값을 내려도 우리
    # 시스템에 존재한 적이 없어 알 방법이 없다. 여유분은 알리지 않고 추적만
    # 하다가, 값이 진짜 조건 안으로 들어오면 그때 처음 알린다.
    WATCH_MARGIN = 2.0

    @classmethod
    def _reg_max(cls, max_price):
        """당근에 실제로 보낼 상한(여유분 포함)."""
        try:
            return int(int(max_price) * cls.WATCH_MARGIN) if max_price else max_price
        except (TypeError, ValueError):
            return max_price

    @staticmethod
    def _cond(min_price, max_price, exclude, extra, days) -> dict:
        """앱 경로 키워드의 조건을 라우트 기록에 함께 남긴다.

        앱 알림은 당근 서버가 판정하고 우리에게는 최소가·최대가·제외어만
        전달된다. 추가키워드·끌올일수는 아예 전달할 방법이 없고, 돌아온
        매칭을 우리 쪽에서 다시 거르지 않으면 엑셀에 적은 조건이 사실상
        무시된다(실측: 20개 브랜드 전부 app 경로였고 추가키워드·끌올일수가
        하나도 안 걸리고 있었다). 그래서 조건을 여기 보존해 두고 알림 직전에
        한 번 더 태운다."""
        c = {}
        if min_price is not None:
            c["min"] = min_price
        if max_price is not None:
            c["max"] = max_price
        if exclude:
            c["exclude"] = [str(x) for x in exclude]
        if extra:
            c["extra"] = [str(x) for x in extra]
        if days:
            c["days"] = int(days)
        return c

    def condition_for(self, keyword) -> dict:
        """키워드에 걸린 조건(없으면 빈 dict). 알림 직전 필터가 쓴다."""
        return dict(((self._routes.get(str(keyword or "").strip()) or {})
                     .get("cond")) or {})

    def add(self, keyword, min_price=None, max_price=None, exclude=None,
            core_only=False, log=None, extra=None, days=None,
            replace_cond=False) -> dict:
        log = log or (lambda m: None)
        keyword = str(keyword or "").strip()
        now = int(time.time())
        if not keyword:
            return {"keyword": keyword, "route": None, "reason": "빈 키워드"}

        # 이미 배정된 키워드를 다시 태우는 경로가 여럿이다 — 일괄등록
        # (add_many 는 배치에 못 넣은 것을 add 로 돌린다), 승격, 재시도.
        # 그 호출들은 조건을 안 넘기므로, 그대로 쓰면 엑셀로 넣어둔 조건이
        # '명품20 전계정등록' 한 번에 지워진다. 그래서 안 넘어온 값은 이전
        # 조건을 잇는다.
        #
        # 예전에는 extra·days 만 이어받고 min·max·exclude 는 흘려보냈다.
        # 그래서 클라가 엑셀을 한 번 넣어도 일괄등록이 한 번 돌면 가격·제외어가
        # 사라졌다 — 실서버에서 20/20 키워드가 조건 없이 남아 있던 이유다.
        # 조건은 프로그램을 껐다 켜도 유지돼야 한다. 이어받는 대상에 전부 넣는다.
        #
        # 조건을 **지우거나 통째로 바꾸는** 유일한 권한은 엑셀을 다시 불러오는
        # 경로에 있다. 그쪽만 replace_cond=True 로 부른다 — 그래야 "엑셀에서
        # 조건을 뺐다"가 실제로 반영된다.
        prev_cond = (self._routes.get(keyword) or {}).get("cond") or {}
        if not replace_cond:
            if min_price is None:
                min_price = prev_cond.get("min")
            if max_price is None:
                max_price = prev_cond.get("max")
            if not exclude:
                exclude = prev_cond.get("exclude")
            if extra is None:
                extra = prev_cond.get("extra")
            if days is None:
                days = prev_cond.get("days")

        cap_now = self.capacity()
        if cap_now["free"] <= 0:
            return self._to_sweep(keyword, min_price, max_price, exclude, now,
                                  f"앱 슬롯 만원({cap_now['cap']})", log,
                                  extra=extra, days=days)
        try:
            res = self.alerts.register_all(
                [keyword], min_price, self._reg_max(max_price), exclude,
                log=log, core_only=core_only) or {}
        except Exception as e:
            return self._to_sweep(keyword, min_price, max_price, exclude, now,
                                  f"등록 실패: {str(e)[:60]}", log, failed=True,
                                  extra=extra, days=days)
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
            # 측정된 신호(우선): register_many 가 실패한 계정의 실제 보유수를
            # 다시 세서 넘겨준 값. 사유 추측 없이 부등식만으로 판단한다 —
            # _observe_measured_count 의 docstring 참고.
            oc = res.get("observed_count")
            if oc is not None:
                self._observe_measured_full(oc, cap_now["used"], log)
            return self._to_sweep(keyword, min_price, max_price, exclude, now,
                                  "앱 등록 실패(차단 키워드·유효 계정 없음)", log,
                                  failed=True, extra=extra, days=days)

        self.queue.remove(keyword)
        self._routes[keyword] = {"route": ROUTE_APP, "reason": "앱 알림 등록",
                                 "at": now,
                                 "cond": self._cond(min_price, max_price,
                                                    exclude, extra, days)}
        self._save()
        return {"keyword": keyword, "route": ROUTE_APP, "reason": "앱 알림 등록"}

    def add_many(self, keywords, min_price=None, max_price=None, exclude=None,
                 core_only=False, log=None, extra=None, days=None,
                 replace_cond=False) -> list[dict]:
        """여러 키워드를 한 번에 배정한다(반환은 키워드별 결과 — 호출자가
        키워드마다 경로를 로그한다).

        슬롯에 들어갈 만큼은 register_all 한 번으로 묶는다. add() 를 키워드
        수만큼 부르면 그 수만큼 '전 계정 목록조회'가 되풀이된다 — 계정
        100개에 브랜드 20개면 부트스트랩 한 번에 수천 요청 차이다."""
        items = [str(k or "").strip() for k in (keywords or [])]
        free = self.capacity()["free"]
        batch, seen = [], set()
        for kw in items:
            if len(batch) >= free:
                break               # 넘치는 몫은 add() 가 요청 없이 스윕으로
            if not kw or kw in seen or kw in self._routes:
                continue            # 빈 값·중복·이미 배정된 것은 개별 처리
            seen.add(kw)
            batch.append(kw)
        done = (self._register_batch(batch, min_price, max_price, exclude,
                                     core_only, log, extra, days)
                if len(batch) > 1 else set())
        return [{"keyword": k, "route": ROUTE_APP, "reason": "앱 알림 등록"}
                if k in done else
                self.add(k, min_price, max_price, exclude, core_only, log,
                         extra, days, replace_cond=replace_cond)
                for k in items]

    def _register_batch(self, batch, min_price, max_price, exclude, core_only,
                        log, extra=None, days=None) -> set:
        """묶음 등록 1회. 전원 성공일 때만 그 키워드들을 app 으로 확정한다.

        register_all 이 계정별 결과를 세 정수로 뭉개므로 부분 실패의 범인을
        지목할 수 없다 — failed 가 하나라도 있으면 배치 결과를 통째로 버리고
        호출자가 키워드별로 다시 태운다(귀속·백오프가 필요한 경우는 개별
        경로뿐이다). 이미 들어간 것은 그 재시도에서 skipped 로 걸러져 등록
        요청을 더 쓰지 않는다.

        배치가 통째로 거부되면(added·skipped 둘 다 0) 개별 재시도에 앞서
        상한부터 관측한다 — 거기서 만원이 확정되면 이어지는 add() 들은
        요청 없이 곧장 스윕으로 간다."""
        cap_now = self.capacity()
        log = log or (lambda m: None)
        try:
            res = self.alerts.register_all(
                batch, min_price, self._reg_max(max_price), exclude,
                log=log, core_only=core_only) or {}
        except Exception:
            return set()            # 사유·백오프 기록은 개별 경로에 맡긴다
        if not (res.get("added") or res.get("skipped")):
            if res.get("failed") and res.get("fleet_full"):
                self._observe_cap_full(log)
            oc = res.get("observed_count")
            if oc is not None:
                self._observe_measured_full(oc, cap_now["used"], log)
            return set()
        if res.get("failed"):
            return set()
        now = int(time.time())
        cond = self._cond(min_price, max_price, exclude, extra, days)
        for kw in batch:
            self.queue.remove(kw)
            self._routes[kw] = {"route": ROUTE_APP, "reason": "앱 알림 등록",
                                "at": now, "cond": cond}
        self._save()
        return set(batch)

    def _to_sweep(self, keyword, min_price, max_price, exclude, now, reason,
                  log, failed: bool = False, extra=None, days=None) -> dict:
        """스윕으로 밀어낸다. 조건은 app 경로와 똑같이 보존한다.

        슬롯이 차서 밀리는 것은 정상 경로다(엑셀 30개 넘기면 바로 여기로 온다).
        여기서 조건을 안 남기면 사용자가 행마다 적은 추가키워드·끌올일수가
        표에서도 사라지고 스윕 필터에도 안 걸린다."""
        prev = self._routes.get(keyword) or {}
        entry = {"route": ROUTE_SWEEP, "reason": reason, "at": now,
                 "cond": self._cond(min_price, max_price, exclude, extra, days)}
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
        self.queue.add(keyword, min_price, max_price, exclude, at=now,
                       extra=extra, days=days)
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
        if self.capacity()["free"] <= 0 or not len(self.queue):
            return []
        now = int(time.time())
        out = []
        for entry in self.queue.oldest(len(self.queue)):
            # 여유는 매 건 다시 본다(로컬 계산, 요청 없음). 승격으로 줄기도
            # 하지만, 실패 한 건이 '함대 만원'을 알려주면 그 자리에서 0 이
            # 된다 — 틱 시작 때의 free 를 붙들고 있으면 이미 만원인 줄
            # 알면서 큐를 끝까지 훑는다(실패 한 건이 곧 전 계정 요청 한 벌).
            if self.capacity()["free"] <= 0:
                break
            kw = entry["keyword"]
            if self.retry_after(kw) > now:
                continue            # 백오프 중 — 이번 틱은 요청을 쓰지 않는다
            # 큐 엔트리가 든 조건을 그대로 되돌린다. 안 넘기면 승격되는
            # 순간 추가키워드·끌올일수가 사라진다.
            res = self.add(kw, entry.get("min"), entry.get("max"),
                           entry.get("exclude"), core_only=core_only, log=log,
                           extra=entry.get("extra"), days=entry.get("days"))
            if res["route"] == ROUTE_APP:
                out.append(res)
            else:
                self.queue.touch(kw)    # 머리를 비켜준다
                continue                # 한 건 실패가 나머지를 막지 않는다
        return out

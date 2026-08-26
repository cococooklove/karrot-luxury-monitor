"""
적응형 감속(AIMD) — 차단 신호가 나오면 스스로 느려지고, 조용하면 스스로 회복한다.

종전에는 요청간격(req_min_ms)이 **고정**이었다. 429/403 이 쏟아져도 같은 속도로 계속
때리니 차단이 가속됐다. 반대로 아무 문제 없을 때도 느린 값을 쓰면 수집이 느려진다.
운영자가 "적당한 속도"를 미리 맞출 방법은 없다 — 프록시 품질·시간대·당근 정책에 따라
매번 달라지기 때문. 그래서 값을 설정으로 빼지 않고 **프로그램이 실측으로 조정**한다.

  차단신호(RATELIMIT/BLOCKED/CHALLENGE) 1회  → 배속 x1.5 (상한 x8)
  깨끗한 성공 20회 연속                      → 배속 x0.9 (하한 x1, 설정값)
  마지막 차단신호 후 120초 무사고            → 배속 x0.9 (성공 카운트와 무관)

시간 기반 회복이 따로 있는 이유: 실측상 응답의 대부분이 빈응답(EMPTY)이라 성공(OK)이
드물게 찍힌다. 성공 카운트만으로 회복시키면 한 번 튄 배속이 몇십 분씩 안 내려온다.

빈응답(EMPTY)·5xx(SERVER)·파싱실패(PARSE)는 감속 사유가 아니다.
  EMPTY  = 시점별 변동(robust 문서 참조). 느리게 해도 안 줄어든다.
  SERVER = 당근 쪽 장애. 우리 속도와 무관.
  PARSE  = HTML 구조변경. IP·속도 문제가 아님.

이 배수는 **이미 존재하던 대기지점에만 곱한다**(프록시별 최소간격·백오프·지역휴식).
새 직렬화 지점을 만들지 않으므로 동시성 구조는 그대로다.

전역 상태 1개를 manual(스레드)·auto(이벤트루프)가 공유한다 — 어느 경로에서 맞았든
같은 프록시 풀을 쓰는 이상 감속은 프로세스 전체에 걸려야 맞다.

고급 조정은 UI 가 아니라 환경변수로만 연다(잘못 만지면 IP 를 태우는 값이라 기본은 숨김):
  DAANGN_THROTTLE=off        완전 비활성(항상 x1)
  DAANGN_THROTTLE_MAX=8      배속 상한
  DAANGN_THROTTLE_UP=1.5     차단 1회당 증가 배수
  DAANGN_THROTTLE_DOWN=0.9   회복 배수
  DAANGN_THROTTLE_RECOVER=20 회복에 필요한 연속 성공 수
  DAANGN_THROTTLE_CALM=120   회복에 필요한 무사고 시간(초)
"""
from __future__ import annotations

import os
import threading
import time

SLOW_KINDS = frozenset({"RATELIMIT", "BLOCKED", "CHALLENGE"})
NEUTRAL_KINDS = frozenset({"EMPTY", "SERVER", "PARSE", "ERROR"})
WINDOW_SEC = 300.0          # "최근" 신호로 셀 시간창(진단표시용)


def _envf(name: str, default: float) -> float:
    try:
        v = float(os.environ.get(name, ""))
        return v if v > 0 else default
    except ValueError:
        return default


ENABLED = os.environ.get("DAANGN_THROTTLE", "").strip().lower() not in ("off", "0", "false")
FACTOR_MAX = _envf("DAANGN_THROTTLE_MAX", 8.0)
UP = _envf("DAANGN_THROTTLE_UP", 1.5)
DOWN = _envf("DAANGN_THROTTLE_DOWN", 0.9)
RECOVER_AFTER = int(_envf("DAANGN_THROTTLE_RECOVER", 20))
CALM_SEC = _envf("DAANGN_THROTTLE_CALM", 120.0)

_lock = threading.Lock()
_factor = 1.0
_ok_streak = 0
_events: list[tuple[float, str]] = []    # (시각, 분류) — 최근 감속 사유
_totals: dict[str, int] = {}             # 분류별 누적 관측수
_last_change = 0.0
_last_slow = 0.0                         # 마지막 차단신호 시각


def observe(kind: str) -> float:
    """robust 가 분류를 낼 때마다 호출. 새 배속 반환."""
    global _factor, _ok_streak, _last_change, _last_slow
    with _lock:
        _totals[kind] = _totals.get(kind, 0) + 1
        if not ENABLED:
            return 1.0
        now = time.time()
        if kind in SLOW_KINDS:
            _events.append((now, kind))
            del _events[:-200]
            _ok_streak = 0
            _last_slow = now
            new = min(_factor * UP, FACTOR_MAX)
            if new != _factor:
                _factor, _last_change = new, now
            return _factor
        if kind == "OK":
            _ok_streak += 1
            if _ok_streak >= RECOVER_AFTER and _factor > 1.0:
                _ok_streak = 0
                _factor = max(1.0, _factor * DOWN)
                _last_change = now
                return _factor
        # NEUTRAL_KINDS 는 감속도 회복도 시키지 않는다(성공 연속도 끊지 않음).
        # 다만 차단신호가 한동안 없으면 관측 종류와 무관하게 한 단계 회복한다.
        if _factor > 1.0 and _last_slow and (now - _last_slow) >= CALM_SEC:
            _factor = max(1.0, _factor * DOWN)
            _last_change = _last_slow = now
        return _factor


def factor() -> float:
    if not ENABLED:
        return 1.0
    with _lock:
        return _factor


def scale(value: float) -> float:
    """대기시간(초/ms 무관)에 현재 배속을 곱한다."""
    return value * factor()


def scale_range(rng):
    """(min,max) 휴식 구간에 배속 적용. None 이면 그대로."""
    if not rng:
        return rng
    f = factor()
    return (rng[0] * f, rng[1] * f)


def recent_slow(window: float = WINDOW_SEC) -> int:
    cut = time.time() - window
    with _lock:
        return sum(1 for t, _ in _events if t >= cut)


def snapshot(base_ms: int | None = None) -> dict:
    """GUI 표시용 — 현재 배속·적용간격·최근 감속사유."""
    with _lock:
        f = _factor if ENABLED else 1.0
        counts: dict[str, int] = {}
        cut = time.time() - WINDOW_SEC
        for t, k in _events:
            if t >= cut:
                counts[k] = counts.get(k, 0) + 1
        return {
            "enabled": ENABLED,
            "factor": round(f, 2),
            "base_ms": base_ms,
            "delay_ms": None if base_ms is None else int(base_ms * f),
            "recent": counts,
            "totals": dict(_totals),
            "since_change": None if not _last_change else round(time.time() - _last_change, 1),
        }


def describe(base_ms: int | None = None) -> str:
    """한 줄 요약."""
    s = snapshot(base_ms)
    if not s["enabled"]:
        return "자동감속 꺼짐"
    if s["delay_ms"] is not None:
        head = f"간격 {s['delay_ms']}ms"
        if s["factor"] > 1.0:
            head += f" (자동감속 x{s['factor']})"
    else:
        head = f"배속 x{s['factor']}"
    if s["recent"]:
        head += " · 최근 " + ", ".join(f"{k} {v}회" for k, v in sorted(s["recent"].items()))
    return head


def reset() -> None:
    """테스트용."""
    global _factor, _ok_streak, _last_change, _last_slow
    with _lock:
        _factor, _ok_streak, _last_change, _last_slow = 1.0, 0, 0.0, 0.0
        _events.clear()
        _totals.clear()

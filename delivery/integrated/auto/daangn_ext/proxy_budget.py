"""
IP 요청예산 관리 — 스로틀 걸린 프록시를 쿨다운시켜 재사용을 막는다.

쿨다운 대상은 **하드 차단·네트워크 오류를 낸 IP 뿐**이다.
빈응답(0건)은 쿨다운 사유가 아니다 — 실환경 실측(2026-08-26)에서 20회 연속 빈응답이던 IP 3개가
몇 분 뒤 각각 1·7·13회만에 성공했다. 빈응답은 그 IP 가 소진됐다는 신호가 아니라 시점별 변동이다.
빈응답에는 쿨다운 대신 **다음 IP 로 즉시 교체**로 대응한다(robust 참조).

robust 가 이 모듈로 프록시를 고르면:
  - 쿨다운 중인 IP 는 후보에서 제외
  - 전부 쿨다운이면 가장 빨리 풀리는 IP 를 반환(정지보다는 진행)
스레드 안전(manual 멀티스레드 / auto 이벤트루프 양쪽에서 공유 가능).
"""
from __future__ import annotations

import random
import threading
import time

COOLDOWN_SEC = 120.0        # 하드차단·네트워크오류 낸 IP 를 쉬게 할 기본 시간
EMPTY_ROTATE_AFTER = 1      # 빈응답 이 횟수마다 IP 교체(실측상 1 = 즉시교체가 최적)

_lock = threading.Lock()
_cooldown: dict[str, float] = {}     # proxy -> 해제 시각(epoch)


def mark_exhausted(proxy: str | None, seconds: float = COOLDOWN_SEC) -> None:
    """이 프록시를 seconds 동안 후보에서 제외. 하드차단·네트워크오류에만 쓸 것
    (빈응답에 쓰면 멀쩡한 IP 가 풀에서 빠져 풀이 말라버린다)."""
    if not proxy:
        return
    with _lock:
        _cooldown[proxy] = max(_cooldown.get(proxy, 0.0), time.time() + seconds)


def is_cooling(proxy: str | None) -> bool:
    if not proxy:
        return False
    with _lock:
        return _cooldown.get(proxy, 0.0) > time.time()


def cooling_until(proxy: str | None) -> float:
    if not proxy:
        return 0.0
    with _lock:
        return _cooldown.get(proxy, 0.0)


def pick(pool: list | None, exclude: str | None = None) -> str | None:
    """쿨다운 아닌 프록시 중 랜덤. exclude 는 우선 회피(방금 소진된 IP)."""
    if not pool:
        return None
    now = time.time()
    with _lock:
        fresh = [p for p in pool if _cooldown.get(p, 0.0) <= now]
    if fresh:
        others = [p for p in fresh if p != exclude]
        return random.choice(others or fresh)
    # 전부 쿨다운 → 가장 빨리 풀리는 것(진행 우선, 단 호출부가 대기 판단 가능)
    with _lock:
        return min(pool, key=lambda p: _cooldown.get(p, 0.0))


def stats() -> list[dict]:
    now = time.time()
    with _lock:
        return [{"proxy": p, "cooling_for": round(t - now, 1)}
                for p, t in sorted(_cooldown.items(), key=lambda kv: -kv[1])
                if t > now]


def pool_status(pool: list | None) -> dict:
    """GUI 표시용 — 풀에서 지금 몇 개가 쓸 수 있는지."""
    pool = pool or []
    now = time.time()
    with _lock:
        cooling = [p for p in pool if _cooldown.get(p, 0.0) > now]
        soonest = min((_cooldown[p] for p in cooling), default=0.0)
    return {"total": len(pool), "cooling": len(cooling),
            "alive": len(pool) - len(cooling),
            "next_free_in": round(soonest - now, 1) if soonest else 0.0}


def reset() -> None:
    """테스트용 — 전체 쿨다운 해제."""
    with _lock:
        _cooldown.clear()

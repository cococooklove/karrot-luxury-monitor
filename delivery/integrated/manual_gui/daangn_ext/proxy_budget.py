"""
IP 요청예산 관리 — 스로틀 걸린 프록시를 쿨다운시켜 재사용을 막는다.

실측(2026-08-26): 한 IP는 세션 워밍 후 ~8~10지역까지 정상 응답하고 그 뒤 스로틀.
그 상태로 계속 쓰면 예산이 더 줄어든다(같은 IP 반복 테스트 실패율 3/12 → 5/12 악화).
따라서 "빈응답이 연속으로 N회" = 워밍이 아니라 **예산 소진**으로 보고 IP를 쉬게 해야 한다.

robust 가 이 모듈로 프록시를 고르면:
  - 쿨다운 중인 IP 는 후보에서 제외
  - 전부 쿨다운이면 가장 빨리 풀리는 IP 를 반환(정지보다는 진행)
스레드 안전(manual 멀티스레드 / auto 이벤트루프 양쪽에서 공유 가능).
"""
from __future__ import annotations

import random
import threading
import time

COOLDOWN_SEC = 300.0        # 예산 소진 판정 시 그 IP 를 쉬게 할 기본 시간
EMPTY_ROTATE_AFTER = 5      # 연속 빈응답 이 횟수 넘으면 예산 소진으로 간주

_lock = threading.Lock()
_cooldown: dict[str, float] = {}     # proxy -> 해제 시각(epoch)


def mark_exhausted(proxy: str | None, seconds: float = COOLDOWN_SEC) -> None:
    """이 프록시를 seconds 동안 후보에서 제외."""
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


def reset() -> None:
    """테스트용 — 전체 쿨다운 해제."""
    with _lock:
        _cooldown.clear()

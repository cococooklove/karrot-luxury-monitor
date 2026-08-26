"""
검색 반복 사이 휴식 — 클라 요구(auto) "검색 반복 전 쉬는 시간 n초~n초 랜덤".

등간격 폴링은 봇 패턴 → 차단. 매 사이클 후 [min,max] 랜덤 대기로 위장.
동기(time.sleep)·비동기(asyncio) 양쪽 제공.
난수는 실행마다 달라야 하므로 os.urandom 기반(재현 불필요).
"""
from __future__ import annotations

import asyncio
import os
import time


def _rand_between(lo: float, hi: float) -> float:
    if hi <= lo:
        return max(lo, 0.0)
    # os.urandom → [0,1) 균등
    r = int.from_bytes(os.urandom(4), "big") / 0xFFFFFFFF
    return lo + (hi - lo) * r


def sleep_between(min_sec: float, max_sec: float) -> float:
    d = _rand_between(min_sec, max_sec)
    time.sleep(d)
    return d


async def asleep_between(min_sec: float, max_sec: float) -> float:
    d = _rand_between(min_sec, max_sec)
    await asyncio.sleep(d)
    return d

"""쿼리 계획 — "이 키워드로 그냥 물어보면 되는가"를 한 곳에서 판단한다.

당근은 일부 브랜드 키워드('샤넬' 등)에 확률적으로 빈 결과를 준다(robust 의 카나리아가
IP·세션 문제와 구분해 `suppressed` 로 표시). 종전 대응에는 구멍이 둘 있었다.

1) 우회가 `adaptive.collect_region` 안에만 있었다.
   동단위 수집(`api.get_products`, GUI 에서 '구단위 고속' 미체크)은 우회 없이 그냥
   예외를 던졌다 — 사용자에겐 "검색 실패"로 보인다.

2) 변형 중 **첫 성공 하나만** 쓰고 멈췄다. 실측(2026-08-27 역삼동)상 변형끼리 결과가
   거의 겹치지 않는다:

     샤넬가방 270 · 샤넬지갑 96 · 샤넬시계 13 · '샤넬 정품' 272 → 합집합 544
     (가방 ↔ 정품 교집합 76건뿐)

   즉 첫 성공만 채택하면 544건 중 272건, 절반을 놓친다. 변형은 **합집합**으로 모은다.

여기서 세 가지를 한다:
  · 억제 판별 결과를 받아 변형들로 재질의하고 id 기준 합집합
  · 어떤 키워드가 억제됐고 어떤 변형이 통했는지 캐시에 학습
  · 다음부터는 처음부터 변형으로 시작 → 카나리아 1요청 + 빈응답 대기를 건너뜀

호출부(`api.get_products`, `adaptive`, `auto_monitor`)는 전부 `fetch_query` 하나만 쓴다.
"""
from __future__ import annotations

import json
import os
import threading
import time

from .robust import robust_fetch_articles

# 억제 키워드를 대체할 변형. 접미어를 붙이면 당근이 응답한다(실측).
# 공백형('샤넬 정품')도 붙임형만큼 잘 나오고 결과 집합이 달라서 함께 쓴다.
VARIANTS = ("가방", "지갑", "시계", " 정품", "신발", "옷", "팔찌", "목걸이")
EXPAND_TRIES = 4        # 억제 시 시도할 변형 개수 상한(요청 비용과 회수율의 절충)
CACHE_PATH = "./suppressed_kw.json"
CACHE_TTL = 7 * 24 * 3600.0     # 학습 결과 유효기간(초). 지나면 원 키워드로 재확인

_lock = threading.Lock()
_cache: dict | None = None
_cache_path = CACHE_PATH


def variants_for(keyword: str, limit: int = EXPAND_TRIES) -> list:
    kw = (keyword or "").strip()
    if not kw:
        return []
    return [f"{kw}{v}" for v in VARIANTS[:max(0, limit)]]


# ── 학습 캐시 ──
def configure_cache(path: str | None) -> None:
    """캐시 파일 경로 지정. None 이면 캐시 비활성(테스트용)."""
    global _cache_path, _cache
    with _lock:
        _cache_path, _cache = path, None


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    data = {}
    if _cache_path:
        try:
            with open(_cache_path, encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            data = {}
    _cache = data
    return _cache


def _save() -> None:
    if not _cache_path or _cache is None:
        return
    try:
        tmp = _cache_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _cache_path)
    except Exception:
        pass        # 캐시는 최적화일 뿐 — 실패해도 수집은 계속된다


def known_suppressed(keyword: str) -> list | None:
    """이 키워드가 억제된 적 있으면 통했던 변형 목록. 없으면 None."""
    with _lock:
        rec = _load().get((keyword or "").strip())
        if not rec:
            return None
        if time.time() - rec.get("at", 0) > CACHE_TTL:
            return None
        return list(rec.get("ok") or []) or None


def remember(keyword: str, ok_variants: list) -> None:
    with _lock:
        c = _load()
        kw = (keyword or "").strip()
        rec = c.setdefault(kw, {"ok": [], "hits": 0})
        rec["at"] = time.time()
        rec["hits"] = rec.get("hits", 0) + 1
        seen = list(rec.get("ok") or [])
        for v in ok_variants:
            if v not in seen:
                seen.append(v)
        rec["ok"] = seen
        _save()


def forget(keyword: str) -> None:
    """더 이상 억제되지 않는 키워드를 캐시에서 제거."""
    with _lock:
        c = _load()
        if c.pop((keyword or "").strip(), None) is not None:
            _save()


# ── 본체 ──
def fetch_query(keyword: str, area_code: str, *, expand: bool = True,
                expand_tries: int = EXPAND_TRIES, **kw) -> tuple[list, dict]:
    """키워드 1건 수집. 억제되면 변형들로 재질의해 **합집합**을 돌려준다.

    반환 meta: robust 의 meta + {"variants_used", "variant_counts", "expanded", "from_cache"}.
    `suppressed` 는 원 키워드가 억제됐다는 뜻이고, 변형으로 건졌으면 articles 는 비지 않는다.
    호출부는 `articles` 가 비었는지와 `exhausted` 만 보면 된다."""
    seen: dict = {}
    used: list = []
    counts: dict = {}
    should_stop = kw.get("should_stop")

    def run(q):
        arts, meta = robust_fetch_articles(q, area_code, **kw)
        counts[q] = len(arts)
        for a in arts:
            seen[a["id"]] = a
        return arts, meta

    cached = known_suppressed(keyword) if expand else None
    if cached:
        # 이미 억제로 확인된 키워드 → 원 키워드를 건너뛰고 바로 변형으로.
        # 카나리아 1요청 + 빈응답 3회 대기를 통째로 절약한다.
        order = cached + [v for v in variants_for(keyword, expand_tries) if v not in cached]
        meta = {}
        for q in order[:expand_tries]:
            arts, meta = run(q)
            if arts:
                used.append(q)
            if should_stop and should_stop():
                break
        meta = dict(meta)
        meta.update(from_cache=True, suppressed=True)
        if used:
            remember(keyword, used)
        return list(seen.values()), _finish(meta, used, counts)

    arts, meta = run(keyword)
    meta = dict(meta)
    if not (expand and meta.get("suppressed")):
        return list(seen.values()), _finish(meta, used, counts)

    # 억제 확정 → 변형 전체를 쏘고 합집합. 첫 성공에서 멈추지 않는다(변형끼리 결과가 다름).
    for q in variants_for(keyword, expand_tries):
        if should_stop and should_stop():
            break
        arts2, _m = run(q)
        if arts2:
            used.append(q)
    if used:
        remember(keyword, used)
    return list(seen.values()), _finish(meta, used, counts)


def _finish(meta: dict, used: list, counts: dict) -> dict:
    meta = dict(meta)
    meta["variants_used"] = list(used)
    meta["variant_counts"] = dict(counts)
    meta["expanded"] = bool(used)
    meta.setdefault("from_cache", False)
    return meta

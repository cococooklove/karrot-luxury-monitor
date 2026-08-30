"""앱 API 슬롯에 못 들어간 키워드의 대기열.

검색 스윕은 슬롯 제한이 없는 대신 느리다. 여기 쌓인 키워드는 스윕 엔진이
커버하고, 앱 슬롯이 비면 KeywordRouter 가 오래된 것부터 앱으로 승격한다.
"""
from __future__ import annotations

import json
import os
import time


class SweepQueue:
    """JSON 한 파일. 키워드 수가 세 자릿수를 넘지 않으므로 sqlite 는 과하다."""

    def __init__(self, path: str = "./data/sweep_queue.json"):
        self.path = path
        self._items = self._load()

    def _load(self) -> list[dict]:
        """없거나 깨졌으면 빈 큐. 예외를 올리지 않는다 — 대기열이 깨졌다고
        감시가 멈추면 안 된다."""
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        out = []
        for it in data:
            if isinstance(it, dict) and it.get("keyword"):
                out.append({"keyword": str(it["keyword"]),
                            "min": it.get("min"),
                            "max": it.get("max"),
                            "exclude": list(it.get("exclude") or []),
                            "at": int(it.get("at") or 0)})
        return out

    def _save(self) -> None:
        try:
            d = os.path.dirname(self.path)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._items, f, ensure_ascii=False)
        except Exception:
            pass

    def add(self, keyword: str, min_price=None, max_price=None,
            exclude=None, at: int | None = None) -> bool:
        keyword = str(keyword or "").strip()
        if not keyword or any(i["keyword"] == keyword for i in self._items):
            return False
        self._items.append({"keyword": keyword, "min": min_price,
                            "max": max_price, "exclude": list(exclude or []),
                            "at": int(at if at is not None else time.time())})
        self._save()
        return True

    def remove(self, keyword: str) -> bool:
        before = len(self._items)
        self._items = [i for i in self._items if i["keyword"] != str(keyword)]
        if len(self._items) == before:
            return False
        self._save()
        return True

    def keywords(self) -> list[str]:
        return [i["keyword"] for i in self._ordered()]

    def entries(self) -> list[dict]:
        return [dict(i) for i in self._ordered()]

    def oldest(self, n: int) -> list[dict]:
        return [dict(i) for i in self._ordered()[:max(0, int(n))]]

    def _ordered(self) -> list[dict]:
        return sorted(self._items, key=lambda i: i.get("at") or 0)

    def __len__(self) -> int:
        return len(self._items)

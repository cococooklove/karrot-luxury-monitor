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
        return [self._norm(it) for it in data
                if isinstance(it, dict) and it.get("keyword")]

    @staticmethod
    def _norm(item: dict, at_default: int = 0) -> dict:
        """엔트리 하나를 정규화한다.

        _load·_copy·add 가 각자 키를 나열하고 있었다. 세 곳 중 하나만
        빠뜨려도 그 키는 조용히 사라진다 — extra·days 가 실제로 그렇게 두 번
        없어졌다(저장은 되는데 읽으면 없고, 고쳤더니 재시작에서 또 없어졌다).
        키를 늘릴 곳은 이제 여기 하나다.

        extra·days 는 값이 있을 때만 싣는다. 없는 것과 빈 것을 구별하지
        않는다 — 스윕 조립이 '없으면 전역 기본값'으로 폴백하기 때문이다."""
        out = {"keyword": str(item.get("keyword") or ""),
               "min": item.get("min"),
               "max": item.get("max"),
               "exclude": [str(x) for x in (item.get("exclude") or [])],
               "at": int(item.get("at") or at_default)}
        if item.get("extra"):
            out["extra"] = [str(x) for x in item["extra"]]
        if item.get("days"):
            out["days"] = int(item["days"])
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
            exclude=None, at: int | None = None, extra=None, days=None) -> bool:
        """대기열에 넣는다.

        추가키워드·끌올일수까지 든다 — 엑셀 행별 조건은 여기 말고 남는 데가
        없다. 안 실으면 스윕이 고급 패널의 전역값을 쓰게 되어, 사용자가 행마다
        적은 조건이 조용히 무시된다. 옛 파일의 엔트리에는 두 키가 없고, 읽는
        쪽은 전부 .get() 이라 그대로 읽힌다.

        이미 있는 키워드면 조건을 **갱신**한다(반환은 그대로 False — 새로
        들어온 게 아니다). 엑셀을 고쳐 다시 불러오는 것은 정상 흐름인데,
        갱신하지 않으면 표는 새 값을 보여주고 스윕은 옛 값으로 도는 상태가
        된다. 갱신은 **넘어온 값만** 덮어쓴다 — 안 넘긴 필드까지 None 으로
        밀면, 조건 없이 부르는 호출 한 번에 기존 조건이 사라진다.

        대기 시각(at)은 처음 것을 지킨다 — 여기서 밀면 큐 맨 뒤로 가서 승격
        순서가 뒤집힌다."""
        keyword = str(keyword or "").strip()
        if not keyword:
            return False
        prev = next((i for i in self._items if i["keyword"] == keyword), None)
        src = dict(prev) if prev else {
            "keyword": keyword,
            "at": at if at is not None else int(time.time())}
        for k, v in (("min", min_price), ("max", max_price), ("exclude", exclude),
                     ("extra", extra), ("days", days)):
            if v is not None:
                src[k] = v
        item = self._norm(src)
        if prev is not None:
            self._items[self._items.index(prev)] = item
            self._save()
            return False
        self._items.append(item)
        self._save()
        return True

    def touch(self, keyword: str, at: int | None = None) -> bool:
        """대기 시각을 지금으로 밀어 맨 뒤로 보낸다.

        add() 는 이미 있는 키워드에 False 만 돌려주고 at 을 갱신하지 않는다.
        승격에 실패한 키워드를 그대로 두면 oldest() 머리에 고정돼 뒤의 키워드가
        승격될 차례를 영영 못 받는다."""
        keyword = str(keyword)
        for i in self._items:
            if i["keyword"] == keyword:
                i["at"] = int(at if at is not None else time.time())
                self._save()
                return True
        return False

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
        return [self._copy(i) for i in self._ordered()]

    def oldest(self, n: int) -> list[dict]:
        return [self._copy(i) for i in self._ordered()[:max(0, int(n))]]

    @staticmethod
    def _copy(item: dict) -> dict:
        """exclude 는 리스트다 — dict(item) 만으로는 내부 상태를 그대로 넘겨준다."""
        return SweepQueue._norm(item)

    def _ordered(self) -> list[dict]:
        return sorted(self._items, key=lambda i: i.get("at") or 0)

    def __len__(self) -> int:
        return len(self._items)

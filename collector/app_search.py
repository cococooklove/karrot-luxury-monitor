"""앱 API 중고거래 검색 — docs/APP_API.md 해독 스펙 구현.

POST https://search-bff.kr.karrotmarket.com/api/v5/fleamarket/search
- spatialContext 를 루트와 fleaMarket.filter 양쪽에 넣어야 한다(하나 빠지면 422).
- 페이징 키는 pageToken. nextToken/cursor 로 보내면 조용히 1페이지가 재반환된다.
- regionId 는 웹 `in=서초동-6128` 의 숫자와 동일.
"""
import json
import random
import time

import httpx

HOST = "search-bff.kr.karrotmarket.com"
PATH = "/api/v5/fleamarket/search"
COORD_TYPE = "USER_COORDINATE_TYPE_REGION_CENTER_COORDINATE"


def build_body(query, region_id, lat, lon, page_token=None,
               without_completed=True):
    spatial = {
        "region": {"regionId": str(region_id)},
        "userCoordinates": [{
            "type": COORD_TYPE,
            "coordinate": {"latitude": lat, "longitude": lon},
        }],
    }
    body = {
        "query": query,
        "fleaMarket": {"filter": {"withoutCompleted": without_completed,
                                  "spatialContext": spatial}},
        "spatialContext": spatial,
    }
    if page_token:
        body["pageToken"] = page_token
    return body


def documents(resp_json):
    """응답 → document dict 리스트."""
    out = []
    for r in resp_json.get("results") or []:
        doc = r.get("document")
        if isinstance(doc, dict):
            out.append(doc)
    return out


class AppSearch:
    def __init__(self, headers, proxy=None, min_gap=1.5, jitter=1.5,
                 worker=None):
        self.headers = dict(headers)
        self.headers.setdefault("content-type", "application/json")
        self.headers["x-search-tab"] = "fleamarket"
        self.min_gap = min_gap
        self.jitter = jitter
        self.worker = worker
        self._last = 0.0
        self._client = httpx.Client(http2=True, timeout=20, proxy=proxy)

    @classmethod
    def from_worker(cls, worker):
        worker.refresh_token()
        return cls(worker.headers, proxy=worker.proxy, worker=worker)

    def _gap(self):
        wait = self._last + self.min_gap - time.time()
        if wait > 0:
            time.sleep(wait)
        time.sleep(random.uniform(0, self.jitter))
        self._last = time.time()

    def search(self, query, region_id, lat, lon, page_token=None):
        body = build_body(query, region_id, lat, lon, page_token)
        self._gap()
        resp = self._client.post(
            f"https://{HOST}{PATH}", headers=self.headers,
            content=json.dumps(body, ensure_ascii=False).encode())
        if self.worker:
            self.worker.note_result(resp.status_code)
        resp.raise_for_status()
        return resp.json()

    def pages(self, query, region_id, lat, lon, max_pages=1):
        """페이지 순회 제너레이터. pageToken 으로만 넘긴다."""
        token = None
        for _ in range(max_pages):
            data = self.search(query, region_id, lat, lon, token)
            yield data
            if not data.get("hasNextPage"):
                return
            token = data.get("nextToken")
            if not token:
                return

    def find_by_title(self, title, region_id, lat, lon, max_pages=3):
        """제목으로 매물 1건을 찾는다(알림 → 매물 해석용)."""
        norm = _norm(title)
        best = None
        for data in self.pages(title, region_id, lat, lon, max_pages):
            for doc in documents(data):
                if _norm(doc.get("title", "")) == norm:
                    return doc
                if best is None and norm and norm in _norm(doc.get("title", "")):
                    best = doc
        return best

    def close(self):
        self._client.close()


def _norm(s):
    return "".join((s or "").split()).lower()

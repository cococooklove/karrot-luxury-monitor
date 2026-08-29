"""매물 워치리스트 테스트 (네트워크 불필요).

    python article_watch_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx

from daangn_ext import article_watch as aw

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


PUBLISHED_ISO = "2026-08-29T21:33:19.375+09:00"
PUBLISHED_EPOCH = 1788006799

ARTICLE_OK = {
    "article": {
        "id": 1236138291,
        "title": "디올 오블리크 카드지갑",
        "price": 410000.0,
        "status": "ongoing",
        "status_name": "판매중",
        "published_at": PUBLISHED_ISO,
        "updated_at": "2026-08-29T21:33:22.493+09:00",
        "republish_count": 0,
        "watches_count": 3,
        "chat_rooms_count": 1,
        "reads_count": 40,
        "destroyed_at": None,
        "is_unpublished": False,
        "visible": True,
        "display_region_name": "평택시 용이동",
        "permalink": "https://www.daangn.com/kr/buy-sell/-1236138291/",
    },
    "meta": {},
}


def fake_client(status_code, payload=None):
    def handler(request):
        return httpx.Response(status_code, json=payload if payload is not None else {})
    return httpx.Client(transport=httpx.MockTransport(handler))


print("=== A. parse_iso ===")
ck("+09:00 파싱", aw.parse_iso(PUBLISHED_ISO) == PUBLISHED_EPOCH, aw.parse_iso(PUBLISHED_ISO))
ck("빈 문자열 → 0", aw.parse_iso("") == 0)
ck("None → 0", aw.parse_iso(None) == 0)
ck("쓰레기 → 0", aw.parse_iso("어제") == 0)

print("=== B. normalize ===")
n = aw.normalize(ARTICLE_OK, "1236138291")
ck("id 문자열", n["id"] == "1236138291", n["id"])
ck("price 정수", n["price"] == 410000 and isinstance(n["price"], int), n["price"])
ck("status", n["status"] == "ongoing")
ck("title", n["title"] == "디올 오블리크 카드지갑")
ck("region", n["region"] == "평택시 용이동")
ck("url", n["url"].endswith("-1236138291/"))
ck("published_at epoch", n["published_at"] == PUBLISHED_EPOCH, n["published_at"])
ck("republish_count", n["republish_count"] == 0)
ck("gone 아님", n["gone"] is False)

print("=== C. ArticleDetailAPI.fetch ===")
api = aw.ArticleDetailAPI("tok", client=fake_client(200, ARTICLE_OK))
got = api.fetch("1236138291")
ck("200 → 정규화 dict", got["price"] == 410000 and got["gone"] is False)
api.close()

api = aw.ArticleDetailAPI("tok", client=fake_client(404))
ck("404 → gone", api.fetch("999") == {"id": "999", "gone": True})
api.close()

api = aw.ArticleDetailAPI("tok", client=fake_client(410))
ck("410 → gone", api.fetch("999")["gone"] is True)
api.close()

api = aw.ArticleDetailAPI("tok", client=fake_client(429))
try:
    api.fetch("1")
    ck("429 → 예외", False)
except httpx.HTTPStatusError as e:
    ck("429 → 예외", e.response.status_code == 429)
api.close()

api = aw.ArticleDetailAPI("tok", client=fake_client(401))
try:
    api.fetch("1")
    ck("401 → 예외", False)
except httpx.HTTPStatusError as e:
    ck("401 → 예외", e.response.status_code == 401)
api.close()

api = aw.ArticleDetailAPI("tok", client=fake_client(200, {
    "article": dict(ARTICLE_OK["article"], destroyed_at="2026-08-29T22:00:00+09:00")}))
ck("destroyed_at 있으면 gone", api.fetch("1")["gone"] is True)
api.close()

api = aw.ArticleDetailAPI("tok", client=fake_client(200, {
    "article": dict(ARTICLE_OK["article"], is_unpublished=True)}))
ck("is_unpublished 면 gone", api.fetch("1")["gone"] is True)
api.close()

api = aw.ArticleDetailAPI("tok", client=fake_client(200, {
    "article": dict(ARTICLE_OK["article"], visible=False)}))
ck("visible False 면 gone", api.fetch("1")["gone"] is True)
api.close()

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

"""매물 워치리스트 테스트 (네트워크 불필요).

    python article_watch_test.py
"""
import os
import sys
import tempfile

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

print("=== D. WatchStore ===")
dbp = os.path.join(tempfile.mkdtemp(), "watch.db")
st = aw.WatchStore(dbp)

st.upsert({"id": "1", "title": "가", "region": "강남", "url": "u1", "price": 1000,
           "status": "ongoing", "republish_count": 0, "published_at": 100,
           "first_seen": 100, "last_check": 100, "next_check": 200,
           "tier": "fresh", "fail": 0})
st.upsert({"id": "2", "title": "나", "region": "서초", "url": "u2", "price": 2000,
           "status": "ongoing", "republish_count": 0, "published_at": 50,
           "first_seen": 100, "last_check": 100, "next_check": 300,
           "tier": "aged", "fail": 0})
st.upsert({"id": "3", "title": "다", "region": "송파", "url": "u3", "price": 3000,
           "status": "closed", "republish_count": 0, "published_at": 10,
           "first_seen": 100, "last_check": 100, "next_check": 150,
           "tier": "dead", "fail": 0})

ck("get 저장값", st.get("1")["price"] == 1000)
ck("get 없는 id → None", st.get("nope") is None)
ck("active_count = 2", st.active_count() == 2, st.active_count())
ck("due(250) → ['1']", st.due(250, 10) == ["1"], st.due(250, 10))
ck("due 는 dead 제외", "3" not in st.due(999, 10))
ck("due 정렬·limit", st.due(999, 1) == ["1"], st.due(999, 1))
ck("oldest_active → ['2','1']", st.oldest_active(2) == ["2", "1"], st.oldest_active(2))
ck("next_due_at = 200", st.next_due_at() == 200, st.next_due_at())

st.upsert({"id": "1", "title": "가", "region": "강남", "url": "u1", "price": 900,
           "status": "ongoing", "republish_count": 0, "published_at": 100,
           "first_seen": 100, "last_check": 400, "next_check": 500,
           "tier": "fresh", "fail": 0})
ck("upsert 갱신", st.get("1")["price"] == 900)
ck("upsert 후에도 2행", st.active_count() == 2)

st.mark("1", tier="dead", fail=3)
ck("mark 부분갱신", st.get("1")["tier"] == "dead" and st.get("1")["fail"] == 3)
ck("mark 후 active_count = 1", st.active_count() == 1)
ck("mark 다른 컬럼 보존", st.get("1")["price"] == 900)
ck("mark 모르는 컬럼 무시", st.mark("1", zzz=1) is None)
st.close()

st2 = aw.WatchStore(dbp)
ck("재열기 영속", st2.get("1")["price"] == 900)
ck("활성 없으면 next_due_at 0", aw.WatchStore(
    os.path.join(tempfile.mkdtemp(), "empty.db")).next_due_at() == 0)
st2.close()

print("=== E. 등급 판정 ===")
NOW = 1_000_000
ck("1시간 전 → fresh", aw.tier_for(NOW - 3600, NOW) == "fresh")
ck("47시간 전 → fresh", aw.tier_for(NOW - 47 * 3600, NOW) == "fresh")
ck("49시간 전 → aged", aw.tier_for(NOW - 49 * 3600, NOW) == "aged")
ck("13일 전 → aged", aw.tier_for(NOW - 13 * 86400, NOW) == "aged")
ck("15일 전 → dead", aw.tier_for(NOW - 15 * 86400, NOW) == "dead")
ck("published_at 0 → fresh", aw.tier_for(0, NOW) == "fresh")
ck("fresh 주기 4시간", aw.interval_for("fresh") == 4 * 3600)
ck("aged 주기 24시간", aw.interval_for("aged") == 24 * 3600)
ck("dead 주기 0", aw.interval_for("dead") == 0)

print("=== F. diff_events ===")
OLD = {"id": "1", "title": "가방", "url": "u", "price": 1000,
       "status": "ongoing", "republish_count": 0}


def newrow(**kw):
    base = {"id": "1", "gone": False, "title": "가방", "url": "u", "price": 1000,
            "status": "ongoing", "republish_count": 0}
    base.update(kw)
    return base


ck("변화 없음 → 이벤트 0", aw.diff_events(OLD, newrow(), NOW) == [])

ev = aw.diff_events(OLD, newrow(price=800), NOW)
ck("가격 인하 1건", len(ev) == 1 and ev[0]["kind"] == "price_down", ev)
ck("인하 old/new", ev[0]["old"] == 1000 and ev[0]["new"] == 800)
ck("이벤트에 url", ev[0]["url"] == "u")
ck("이벤트에 at", ev[0]["at"] == NOW)
ck("이벤트에 id", ev[0]["id"] == "1")

ev = aw.diff_events(OLD, newrow(price=1200), NOW)
ck("가격 인상", len(ev) == 1 and ev[0]["kind"] == "price_up")

ev = aw.diff_events(OLD, newrow(status="closed"), NOW)
ck("판매완료", len(ev) == 1 and ev[0]["kind"] == "sold", ev)

ev = aw.diff_events(OLD, newrow(status="reserved"), NOW)
ck("예약중은 이벤트 아님", ev == [], ev)

ev = aw.diff_events(OLD, {"id": "1", "gone": True}, NOW)
ck("삭제", len(ev) == 1 and ev[0]["kind"] == "deleted", ev)
ck("삭제 이벤트도 title 보존", ev[0]["title"] == "가방", ev[0])

ev = aw.diff_events(OLD, newrow(republish_count=1), NOW)
ck("끌올", len(ev) == 1 and ev[0]["kind"] == "republished")

ev = aw.diff_events(OLD, newrow(price=700, status="closed"), NOW)
kinds = sorted(e["kind"] for e in ev)
ck("동시 변화 2건", kinds == ["price_down", "sold"], kinds)

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

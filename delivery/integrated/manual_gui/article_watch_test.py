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

st.upsert({"id": "4", "title": "라", "region": "마포", "url": "u4", "price": 4000,
           "status": "ongoing", "republish_count": 0, "published_at": 5,
           "first_seen": 100, "last_check": 100, "next_check": 100,
           "tier": aw.TIER_EVICTED, "fail": 0})
ck("evicted 는 active_count 제외", st.active_count() == 1, st.active_count())
ck("evicted 는 due 제외", st.due(999, 10) == ["2"], st.due(999, 10))
ck("evicted 는 oldest_active 제외", "4" not in st.oldest_active(10))
ck("evicted 는 next_due_at 제외", st.next_due_at() == 300, st.next_due_at())
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

print("=== G. parse_price_text ===")
ck("410,000원 → 410000", aw.parse_price_text("410,000원") == 410000)
ck("나눔 → 0", aw.parse_price_text("나눔") == 0)
ck("None → 0", aw.parse_price_text(None) == 0)
ck("정수 그대로", aw.parse_price_text(5000) == 5000)
ck("실수 → 정수", aw.parse_price_text(4100.0) == 4100)
ck("bool → 0", aw.parse_price_text(True) == 0)
ck("285만원 → 2850000", aw.parse_price_text("285만원") == 2850000,
   aw.parse_price_text("285만원"))
ck("100만원 → 1000000", aw.parse_price_text("100만원") == 1000000,
   aw.parse_price_text("100만원"))
ck("1억 → 100000000", aw.parse_price_text("1억") == 100000000,
   aw.parse_price_text("1억"))
ck("1억 2000만원 → 120000000", aw.parse_price_text("1억 2000만원") == 120000000,
   aw.parse_price_text("1억 2000만원"))
ck("130,000원 → 130000", aw.parse_price_text("130,000원") == 130000,
   aw.parse_price_text("130,000원"))
ck("1,000만원 → 10000000", aw.parse_price_text("1,000만원") == 10000000,
   aw.parse_price_text("1,000만원"))

print("=== H. 투입과 상한 ===")
dbp2 = os.path.join(tempfile.mkdtemp(), "w2.db")
store = aw.WatchStore(dbp2)
tr = aw.WatchTracker(store)

MATCHES = [
    {"article_id": "10", "title": "샤넬", "region": "강남", "url": "u10",
     "price": "1,000,000원", "time": str(NOW - 3600)},
    {"article_id": "11", "title": "디올", "region": "서초", "url": "u11",
     "price": "500,000원", "time": str(NOW - 5 * 86400)},
]
ck("신규 2건 투입", tr.add_from_matches(MATCHES, now=NOW) == 2)
ck("중복 투입 0건", tr.add_from_matches(MATCHES, now=NOW) == 0)
ck("가격 파싱 저장", store.get("10")["price"] == 1000000)
ck("fresh 등급", store.get("10")["tier"] == "fresh")
ck("aged 등급", store.get("11")["tier"] == "aged")
ck("next_check 미래", store.get("10")["next_check"] > NOW)
ck("article_id 없으면 무시", tr.add_from_matches([{"title": "x"}], now=NOW) == 0)
ck("15일 지난 매칭은 투입 안 함",
   tr.add_from_matches([{"article_id": "99", "title": "옛것", "region": "r",
                         "url": "u", "price": "1원",
                         "time": str(NOW - 15 * 86400)}], now=NOW) == 0)

for i in range(aw.ACTIVE_CAP + 5):
    store.upsert({"id": f"c{i}", "title": "t", "region": "r", "url": "u",
                  "price": 1, "status": "ongoing", "republish_count": 0,
                  "published_at": NOW - i * 60, "first_seen": NOW,
                  "last_check": NOW, "next_check": NOW + 10, "tier": "fresh",
                  "fail": 0})
before = store.active_count()
dropped = tr.enforce_cap(NOW)
ck("상한까지 강등", store.active_count() == aw.ACTIVE_CAP,
   f"{before} -> {store.active_count()}")
ck("강등 수 반환", dropped == before - aw.ACTIVE_CAP, dropped)
ck("가장 오래된 것부터 evicted",
   store.get("c%d" % (aw.ACTIVE_CAP + 4))["tier"] == aw.TIER_EVICTED,
   store.get("c%d" % (aw.ACTIVE_CAP + 4))["tier"])
ck("상한 축출은 dead 아님",
   store.get("c%d" % (aw.ACTIVE_CAP + 4))["tier"] != aw.TIER_DEAD)
ck("상한 이하면 0", tr.enforce_cap(NOW) == 0)

print("=== I. check_one ===")
dbp3 = os.path.join(tempfile.mkdtemp(), "w3.db")
store3 = aw.WatchStore(dbp3)
tr3 = aw.WatchTracker(store3)
tr3.add_from_matches([{"article_id": "20", "title": "구찌", "region": "강남",
                       "url": "u20", "price": "900,000원",
                       "time": str(NOW - 3600)}], now=NOW)


class FakeAPI:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, 0

    def fetch(self, article_id):
        self.calls += 1
        if self.exc:
            raise self.exc
        return dict(self.result, id=str(article_id))


def http_error(code):
    req = httpx.Request("GET", "https://x/")
    return httpx.HTTPStatusError("boom", request=req,
                                 response=httpx.Response(code, request=req))


# 씨앗값(알림 표시가격 900,000원 / 끌올수 0)과 실측이 둘 다 어긋나는 첫 조회.
# 씨앗은 알림 문자열로 만든 값이라 비교 대상이 아니다 — 기준선만 잡고 침묵해야 한다.
api_seed = FakeAPI({"gone": False, "title": "구찌", "url": "u20", "price": 850000,
                    "status": "ongoing", "republish_count": 2,
                    "published_at": NOW - 3600, "region": "강남"})
ev = tr3.check_one("20", api_seed, NOW + 100)
ck("첫 조회는 기준선 — 이벤트 없음", ev == [], ev)
ck("첫 조회도 실측 가격 저장", store3.get("20")["price"] == 850000,
   store3.get("20")["price"])
ck("첫 조회도 끌올수 저장", store3.get("20")["republish_count"] == 2)
ck("last_check 갱신", store3.get("20")["last_check"] == NOW + 100)
ck("next_check 재계산",
   store3.get("20")["next_check"] == NOW + 100 + aw.FRESH_INTERVAL)

api_ok = FakeAPI({"gone": False, "title": "구찌", "url": "u20", "price": 800000,
                  "status": "ongoing", "republish_count": 2,
                  "published_at": NOW - 3600, "region": "강남"})
ev = tr3.check_one("20", api_ok, NOW + 200)
ck("두 번째 조회부터 인하 이벤트", len(ev) == 1 and ev[0]["kind"] == "price_down", ev)
ck("인하 old/new 는 실측 기준선", ev[0]["old"] == 850000 and ev[0]["new"] == 800000, ev[0])
ck("새 가격 저장", store3.get("20")["price"] == 800000)
ck("변화 없으면 이벤트 없음", tr3.check_one("20", api_ok, NOW + 210) == [])
ck("없는 id 는 조용히 빈 목록", tr3.check_one("없음", api_ok, NOW) == [])

# 상세 응답이 price 0 을 주는 경우가 실제로 있다(라이브 매물인데 0). '0원 인하'가
# 아니라 '모르는 값'으로 다뤄야 한다.
api_zero = FakeAPI({"gone": False, "title": "구찌", "url": "u20", "price": 0,
                    "status": "ongoing", "republish_count": 2,
                    "published_at": NOW - 3600, "region": "강남"})
ck("가격 0 은 이벤트 아님", tr3.check_one("20", api_zero, NOW + 220) == [])
ck("가격 0 이면 저장값 유지", store3.get("20")["price"] == 800000,
   store3.get("20")["price"])
api_noprice = FakeAPI({"gone": False, "title": "구찌", "url": "u20", "price": None,
                       "status": "ongoing", "republish_count": 2,
                       "published_at": NOW - 3600, "region": "강남"})
ck("가격 None 도 이벤트 아님", tr3.check_one("20", api_noprice, NOW + 230) == [])
ck("가격 None 이면 저장값 유지", store3.get("20")["price"] == 800000)

api_closed = FakeAPI({"gone": False, "title": "구찌", "url": "u20", "price": 800000,
                      "status": "closed", "republish_count": 2,
                      "published_at": NOW - 3600, "region": "강남"})
ev = tr3.check_one("20", api_closed, NOW + 250)
ck("판매완료 이벤트", len(ev) == 1 and ev[0]["kind"] == "sold", ev)
ck("판매완료 후 dead", store3.get("20")["tier"] == aw.TIER_DEAD)

tr3.add_from_matches([{"article_id": "22", "title": "루이", "region": "강남",
                       "url": "u22", "price": "1원", "time": str(NOW - 3600)}],
                     now=NOW)
alive22 = FakeAPI({"gone": False, "title": "루이", "url": "u22", "price": 500000,
                   "status": "ongoing", "republish_count": 0,
                   "published_at": NOW - 3600, "region": "강남"})
ck("삭제 판정도 기준선 조회가 먼저", tr3.check_one("22", alive22, NOW + 290) == [])
ev = tr3.check_one("22", FakeAPI({"gone": True}), NOW + 300)
ck("삭제 이벤트", len(ev) == 1 and ev[0]["kind"] == "deleted", ev)
ck("삭제 후 dead", store3.get("22")["tier"] == aw.TIER_DEAD)
ck("dead 는 due 에서 빠짐", store3.due(NOW + 99999, 10) == [])

tr3.add_from_matches([{"article_id": "21", "title": "펜디", "region": "강남",
                       "url": "u21", "price": "100,000원",
                       "time": str(NOW - 3600)}], now=NOW)
api_err = FakeAPI(exc=RuntimeError("boom"))
for i in range(aw.MAX_FAIL):
    ck(f"실패 {i+1}회 이벤트 없음",
       tr3.check_one("21", api_err, NOW + 400 + i) == [])
ck("MAX_FAIL 후 evicted", store3.get("21")["tier"] == aw.TIER_EVICTED,
   store3.get("21")["tier"])
ck("연속 실패는 dead 아님", store3.get("21")["tier"] != aw.TIER_DEAD)
ck("fail 카운터", store3.get("21")["fail"] == aw.MAX_FAIL)
ck("실패는 last_check 를 건드리지 않음",
   store3.get("21")["last_check"] == store3.get("21")["first_seen"],
   (store3.get("21")["last_check"], store3.get("21")["first_seen"]))

# 조회 실패가 기준선 표식(last_check == first_seen)을 깨면 안 된다. 깨지면 첫
# 성공 조회가 씨앗("285만원" / 끌올 0)과 비교돼 수정 1이 없앤 오탐이 되돌아온다.
tr3.add_from_matches([{"article_id": "24", "title": "보테가", "region": "강남",
                       "url": "u24", "price": "285만원",
                       "time": str(NOW - 3600)}], now=NOW)
ck("실패 전 씨앗 파싱", store3.get("24")["price"] == 2850000,
   store3.get("24")["price"])
ck("실패 1회는 이벤트 없음",
   tr3.check_one("24", FakeAPI(exc=RuntimeError("boom")), NOW + 800) == [])
ck("실패 후에도 next_check 는 전진",
   store3.get("24")["next_check"] == NOW + 800 + aw.FRESH_INTERVAL,
   store3.get("24")["next_check"])
api24 = FakeAPI({"gone": False, "title": "보테가", "url": "u24", "price": 2900000,
                 "status": "ongoing", "republish_count": 2,
                 "published_at": NOW - 3600, "region": "강남"})
ev = tr3.check_one("24", api24, NOW + 900)
ck("실패 뒤 첫 성공 조회도 기준선 — 이벤트 없음", ev == [], ev)
ck("실패 뒤 기준선도 실측 가격 저장", store3.get("24")["price"] == 2900000,
   store3.get("24")["price"])
ck("실패 뒤 기준선도 실측 끌올수 저장", store3.get("24")["republish_count"] == 2)
ck("성공하면 fail 초기화", store3.get("24")["fail"] == 0,
   store3.get("24")["fail"])
ck("성공 조회가 last_check 를 옮김",
   store3.get("24")["last_check"] == NOW + 900, store3.get("24")["last_check"])
api24b = FakeAPI({"gone": False, "title": "보테가", "url": "u24", "price": 2500000,
                  "status": "ongoing", "republish_count": 3,
                  "published_at": NOW - 3600, "region": "강남"})
ev = tr3.check_one("24", api24b, NOW + 1000)
kinds24 = sorted(e["kind"] for e in ev)
ck("그 다음 변화는 정상 발화", kinds24 == ["price_down", "republished"], kinds24)
ck("발화 기준은 실측 2900000", ev[0]["old"] == 2900000, ev[0])

tr3.add_from_matches([{"article_id": "23", "title": "에르메스", "region": "강남",
                       "url": "u23", "price": "1원", "time": str(NOW - 3600)}],
                     now=NOW)
try:
    tr3.check_one("23", FakeAPI(exc=http_error(429)), NOW + 500)
    ck("429 → AccountUnavailable", False)
except aw.AccountUnavailable:
    ck("429 → AccountUnavailable", True)
ck("429 는 fail 안 올림", store3.get("23")["fail"] == 0)
ck("429 는 next_check 미룸",
   store3.get("23")["next_check"] == NOW + 500 + aw.RATE_LIMIT_DELAY,
   store3.get("23")["next_check"])

nc_before_401 = store3.get("23")["next_check"]
try:
    tr3.check_one("23", FakeAPI(exc=http_error(401)), NOW + 600)
    ck("401 → AccountUnavailable", False)
except aw.AccountUnavailable:
    ck("401 → AccountUnavailable", True)
ck("401 는 fail 안 올림", store3.get("23")["fail"] == 0)
ck("401 는 next_check 안 건드림",
   store3.get("23")["next_check"] == nc_before_401,
   store3.get("23")["next_check"])

try:
    tr3.check_one("23", FakeAPI(exc=http_error(500)), NOW + 700)
    ck("500 은 일반 실패", store3.get("23")["fail"] == 1, store3.get("23")["fail"])
except aw.AccountUnavailable:
    ck("500 은 일반 실패", False)

print("=== J. sweep ===")
dbp4 = os.path.join(tempfile.mkdtemp(), "w4.db")
store4 = aw.WatchStore(dbp4)
tr4 = aw.WatchTracker(store4)
for i in range(5):
    # first_seen != last_check — 이미 기준선을 잡은 행이어야 diff 가 나온다
    store4.upsert({"id": f"s{i}", "title": "t", "region": "r", "url": "u",
                   "price": 100, "status": "ongoing", "republish_count": 0,
                   "published_at": NOW - 3600, "first_seen": NOW - 1000,
                   "last_check": NOW, "next_check": NOW - 1, "tier": "fresh",
                   "fail": 0})

shared = FakeAPI({"gone": False, "title": "t", "url": "u", "price": 90,
                  "status": "ongoing", "republish_count": 0,
                  "published_at": NOW - 3600, "region": "r"})
evs = tr4.sweep(lambda: (shared, "acc-a"), budget=3, now=NOW)
ck("예산만큼만 조회", shared.calls == 3, shared.calls)
ck("이벤트 3건", len(evs) == 3, len(evs))
ck("남은 2건은 due 유지", len(store4.due(NOW, 10)) == 2)
ck("완주하면 exhausted False", tr4.last_sweep_exhausted is False)
ck("계정 없으면 조회 0", tr4.sweep(lambda: None, budget=10, now=NOW) == [])
ck("처음부터 계정 없으면 exhausted True", tr4.last_sweep_exhausted is True)

# 대기열 중간에 예산이 마르는 경우
dbp4b = os.path.join(tempfile.mkdtemp(), "w4b.db")
store4b = aw.WatchStore(dbp4b)
tr4b = aw.WatchTracker(store4b)
for i in range(3):
    store4b.upsert({"id": f"x{i}", "title": "t", "region": "r", "url": "u",
                    "price": 100, "status": "ongoing", "republish_count": 0,
                    "published_at": NOW - 3600, "first_seen": NOW - 1000,
                    "last_check": NOW, "next_check": NOW - 1, "tier": "fresh",
                    "fail": 0})
one_shot = FakeAPI({"gone": False, "title": "t", "url": "u", "price": 90,
                    "status": "ongoing", "republish_count": 0,
                    "published_at": NOW - 3600, "region": "r"})
dry = [(one_shot, "acc-a")]
evs = tr4b.sweep(lambda: dry.pop(0) if dry else None, budget=3, now=NOW)
ck("마르기 전 처리분은 반환", len(evs) == 1, len(evs))
ck("중간에 마르면 exhausted True", tr4b.last_sweep_exhausted is True)
ck("남은 대상은 due 로 남음", len(store4b.due(NOW, 10)) == 2,
   len(store4b.due(NOW, 10)))

dbp5 = os.path.join(tempfile.mkdtemp(), "w5.db")
store5 = aw.WatchStore(dbp5)
tr5 = aw.WatchTracker(store5)
for i in range(3):
    store5.upsert({"id": f"r{i}", "title": "t", "region": "r", "url": "u",
                   "price": 100, "status": "ongoing", "republish_count": 0,
                   "published_at": NOW - 3600, "first_seen": NOW - 1000,
                   "last_check": NOW, "next_check": NOW - 1, "tier": "fresh",
                   "fail": 0})
bad_api = FakeAPI(exc=http_error(429))
good_api = FakeAPI({"gone": False, "title": "t", "url": "u", "price": 90,
                    "status": "ongoing", "republish_count": 0,
                    "published_at": NOW - 3600, "region": "r"})
seq = [(bad_api, "acc-bad"), (bad_api, "acc-bad"), (good_api, "acc-good"),
       (good_api, "acc-good"), (good_api, "acc-good")]


def provider():
    return seq.pop(0) if seq else None


evs = tr5.sweep(provider, budget=3, now=NOW)
ck("막힌 계정은 이후 건너뜀", bad_api.calls == 1, bad_api.calls)
ck("다른 계정으로 이어감", good_api.calls == 2, good_api.calls)

print("=== K. AccountBudget ===")
import json as _json

acc_fp = os.path.join(tempfile.mkdtemp(), "accounts.json")
_json.dump([{"label": l, "access": "tok-" + l, "proxy": None} for l in ("a", "b")],
           open(acc_fp, "w", encoding="utf-8"))

DAY = {"v": "2026-08-29"}


def fake_factory(token, config_path=None, proxy=None):
    return FakeAPI({"gone": False, "title": "t", "url": "u", "price": 1,
                    "status": "ongoing", "republish_count": 0,
                    "published_at": NOW, "region": "r"})


orig_remaining = aw.token_remaining
aw.token_remaining = lambda t: 9999          # 전부 유효한 토큰으로 취급


def tmp_budget_fp(name="watch_budget.json"):
    return os.path.join(tempfile.mkdtemp(), name)


bud = aw.AccountBudget(acc_fp, daily_cap=2, api_factory=fake_factory,
                       day_fn=lambda: DAY["v"], budget_fp=tmp_budget_fp())
ck("총 예산 = 계정수 x 상한", bud.remaining() == 4, bud.remaining())
got = [bud.next() for _ in range(4)]
ck("4건 모두 발급", all(g is not None for g in got))
ck("라운드로빈", [g[1] for g in got] == ["a", "b", "a", "b"], [g[1] for g in got])
ck("소진 후 None", bud.next() is None)
ck("remaining 0", bud.remaining() == 0)

DAY["v"] = "2026-08-30"
ck("날짜 바뀌면 리셋", bud.remaining() == 4)
ck("리셋 후 발급", bud.next() is not None)

aw.token_remaining = lambda t: 10            # 만료 임박 = 무효
bud2 = aw.AccountBudget(acc_fp, daily_cap=2, api_factory=fake_factory,
                        day_fn=lambda: DAY["v"], budget_fp=tmp_budget_fp())
ck("유효 토큰 없으면 None", bud2.next() is None)
ck("유효 토큰 없으면 remaining 0", bud2.remaining() == 0)

aw.token_remaining = lambda t: 9999
bud3 = aw.AccountBudget(os.path.join(tempfile.mkdtemp(), "없음.json"),
                        daily_cap=2, api_factory=fake_factory,
                        day_fn=lambda: DAY["v"], budget_fp=tmp_budget_fp())
ck("파일 없으면 None", bud3.next() is None)

acc3_fp = os.path.join(tempfile.mkdtemp(), "accounts3.json")
_json.dump([{"label": l, "access": "tok-" + l, "proxy": None}
            for l in ("x", "y", "z")],
           open(acc3_fp, "w", encoding="utf-8"))
aw.token_remaining = lambda t: 9999
bud4 = aw.AccountBudget(acc3_fp, daily_cap=5, api_factory=fake_factory,
                        day_fn=lambda: DAY["v"], budget_fp=tmp_budget_fp())
seq3 = [bud4.next()[1] for _ in range(3)]
ck("3계정 순환", seq3 == ["x", "y", "z"], seq3)
aw.token_remaining = lambda t: 10 if t == "tok-y" else 9999   # y 만 만료
after = bud4.next()[1]
ck("목록 축소 후 직전 계정 반복 없음", after != "z", after)
ck("축소 후에도 유효 계정만", after in ("x",), after)

aw.token_remaining = lambda t: 9999
print("=== L. 예산 영속 ===")
persist_fp = tmp_budget_fp()
DAY2 = {"v": "2026-09-01"}
budp = aw.AccountBudget(acc_fp, daily_cap=2, api_factory=fake_factory,
                        day_fn=lambda: DAY2["v"], budget_fp=persist_fp)
for _ in range(3):
    budp.next()                              # a=2, b=1
ck("사용량 파일 생성", os.path.exists(persist_fp))
saved = _json.load(open(persist_fp, encoding="utf-8"))
ck("파일에 날짜", saved.get("day") == "2026-09-01", saved)
ck("파일에 계정별 사용량", saved.get("used", {}).get("a") == 2, saved)

budp2 = aw.AccountBudget(acc_fp, daily_cap=2, api_factory=fake_factory,
                         day_fn=lambda: DAY2["v"], budget_fp=persist_fp)
ck("재시작해도 사용량 유지", budp2.remaining() == 1, budp2.remaining())
ck("남은 1건 발급", budp2.next() is not None)
ck("그 다음은 None", budp2.next() is None)

DAY2["v"] = "2026-09-02"
budp3 = aw.AccountBudget(acc_fp, daily_cap=2, api_factory=fake_factory,
                         day_fn=lambda: DAY2["v"], budget_fp=persist_fp)
ck("날짜 다르면 파일 무시", budp3.remaining() == 4, budp3.remaining())

bad_fp = tmp_budget_fp("bad.json")
with open(bad_fp, "w", encoding="utf-8") as f:
    f.write("{ 이건 json 이 아님")
budp4 = aw.AccountBudget(acc_fp, daily_cap=2, api_factory=fake_factory,
                         day_fn=lambda: DAY2["v"], budget_fp=bad_fp)
ck("깨진 파일이면 0부터", budp4.remaining() == 4, budp4.remaining())

junk_fp = tmp_budget_fp("junk.json")
_json.dump({"day": "2026-09-02", "used": "이상함"}, open(junk_fp, "w", encoding="utf-8"))
budp5 = aw.AccountBudget(acc_fp, daily_cap=2, api_factory=fake_factory,
                         day_fn=lambda: DAY2["v"], budget_fp=junk_fp)
ck("used 형식 이상하면 0부터", budp5.remaining() == 4, budp5.remaining())

nodir_fp = os.path.join(tempfile.mkdtemp(), "없는하위", "watch_budget.json")
budp6 = aw.AccountBudget(acc_fp, daily_cap=2, api_factory=fake_factory,
                         day_fn=lambda: DAY2["v"], budget_fp=nodir_fp)
budp6.next()
ck("상위 폴더 없으면 만들어 저장", os.path.exists(nodir_fp))

aw.token_remaining = orig_remaining

print("=== M. evicted 재등록 ===")
dbp6 = os.path.join(tempfile.mkdtemp(), "w6.db")
store6 = aw.WatchStore(dbp6)
tr6 = aw.WatchTracker(store6)
M30 = [{"article_id": "30", "title": "샤넬", "region": "강남", "url": "u30",
        "price": "285만원", "time": str(NOW - 3600)}]
ck("최초 투입", tr6.add_from_matches(M30, now=NOW) == 1)
ck("만 단위 씨앗 파싱", store6.get("30")["price"] == 2850000,
   store6.get("30")["price"])
ck("추적 중이면 재투입 안 함", tr6.add_from_matches(M30, now=NOW + 10) == 0)

store6.mark("30", tier=aw.TIER_EVICTED)
ck("evicted 는 active 아님", store6.active_count() == 0, store6.active_count())
ck("evicted 는 due 없음", store6.due(NOW + 99999, 10) == [])
ck("상한 축출분은 다시 매칭되면 재등록",
   tr6.add_from_matches(M30, now=NOW + 20) == 1)
ck("재등록 후 다시 fresh", store6.get("30")["tier"] == "fresh",
   store6.get("30")["tier"])
ck("재등록 후 다시 기준선부터",
   store6.get("30")["first_seen"] == store6.get("30")["last_check"])

store6.mark("30", tier=aw.TIER_DEAD)
ck("판매완료·삭제(dead)는 재등록 안 함",
   tr6.add_from_matches(M30, now=NOW + 30) == 0)

# ── seen_key: article_id 없는 매치의 영속 중복 판정 ──
# 옛 match_seen.json 이 하던 일이다. 파일을 되살리는 대신 watch.db 안의 별도
# 테이블로 둔다 — 매물이 아니므로 watch 행이 되면 안 된다.
print("=== seen_key ===")
_sk_path = os.path.join(tempfile.mkdtemp(), "watch.db")
sk = aw.WatchStore(_sk_path)
ck("처음 보는 키는 True", sk.seen_key_add("inbox-1", now=NOW) is True)
ck("같은 키는 False", sk.seen_key_add("inbox-1", now=NOW + 1) is False)
ck("다른 키는 True", sk.seen_key_add("inbox-2", now=NOW + 1) is True)
ck("has 로 조회", sk.seen_key_has("inbox-1") and not sk.seen_key_has("inbox-9"))
ck("빈 키는 기록 안 함",
   sk.seen_key_add("") is False and sk.seen_key_count() == 2)
ck("seen_key 는 watch 행이 아니다",
   sk.get("inbox-1") is None and sk.listing_rows() == [],
   str(sk.listing_rows()))
ck("seen_key 는 조회 대상도 아니다",
   sk.due(NOW + 99999, 10) == [] and sk.active_count() == 0)
sk.close()

# 재시작: 같은 파일을 다시 열어도 기억한다(이게 이 테이블의 존재 이유다).
sk2 = aw.WatchStore(_sk_path)
ck("재시작해도 기억한다", sk2.seen_key_add("inbox-1", now=NOW + 5) is False)
ck("재시작 후 건수 유지", sk2.seen_key_count() == 2, sk2.seen_key_count())

# 상한: 무한히 자라면 옛 파일과 같은 문제가 된다.
for _i in range(12):
    sk2.seen_key_add(f"k-{_i}", now=NOW + 100 + _i, cap=5)
ck("상한을 넘지 않는다", sk2.seen_key_count() == 5, sk2.seen_key_count())
ck("오래된 것부터 버린다",
   sk2.seen_key_has("k-11") and not sk2.seen_key_has("k-0"))
ck("버려진 키는 다시 신규가 된다", sk2.seen_key_add("k-0", now=NOW + 200, cap=5))
ck("기본 상한은 옛 파일과 같다", aw.SEEN_KEY_CAP == 5000)
sk2.close()

ck("백필 묘비 출처 상수", aw.SOURCE_MATCH_SEEN == "match_seen")

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

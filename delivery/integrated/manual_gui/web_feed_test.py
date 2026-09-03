"""웹 동 피드 파서·워터마크 (네트워크 없음, 픽스처만)."""
import json, os, sys, tempfile, time
app_dir = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, app_dir); os.chdir(app_dir)
R = []
def ck(name, cond, extra=""):
    R.append((name, bool(cond))); print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")

from daangn_ext import web_feed as W
FX = os.path.join(app_dir, "tests", "fixtures")

print("=== A. URL ===")
u = W.feed_url("역삼동", 6035, 31)
ck("동 이름 인코딩 + id + 카테고리 + _data 로더",
   u == "https://www.daangn.com/kr/buy-sell/?in=%EC%97%AD%EC%82%BC%EB%8F%99-6035&category_id=31&_data=routes%2Fkr.buy-sell._index", u)
ck("카테고리 없음·HTML 모드", W.feed_url("역삼동", "6035", None, data=False)
   == "https://www.daangn.com/kr/buy-sell/?in=%EC%97%AD%EC%82%BC%EB%8F%99-6035")

print("=== B. JSON 파서 ===")
j = json.load(open(os.path.join(FX, "web_feed_loader.json"), encoding="utf-8"))
arts = W.parse_feed_json(j)
ck("40건", len(arts) == 40, str(len(arts)))
a = arts[0]
ck("키 모양", set(a) >= {"href", "title", "content", "price", "status", "boosted_at", "created_at", "region", "category", "thumbnail"}, str(sorted(a)))
ck("href 절대 URL", a["href"].startswith("https://www.daangn.com/kr/buy-sell/"), a["href"])
ck("가격 int", isinstance(a["price"], int) and a["price"] > 0, str(a["price"]))
ck("status 소문자", a["status"] in ("ongoing", "reserved", "closed"), a["status"])
ck("boosted_at epoch", a["boosted_at"] > 1_700_000_000, str(a["boosted_at"]))
ck("본문 있음", any(x["content"] for x in arts))
ck("region 이름", a["region"] == "역삼동", a["region"])
ck("빈 로더는 빈 목록", W.parse_feed_json({}) == [] and W.parse_feed_json({"allPage": {}}) == [])

print("=== C. HTML 폴백 파서 ===")
html = open(os.path.join(FX, "web_feed_page.html"), encoding="utf-8").read()
h = W.parse_feed_html(html)
ck("ld+json ItemList 에서 매물", len(h) > 100, str(len(h)))
ck("본문·가격·href", h[0]["content"] and isinstance(h[0]["price"], int) and h[0]["href"].startswith("https://"))
ck("시각 없음 → 0", h[0]["boosted_at"] == 0)
ck("ld+json 없는 HTML 은 빈 목록", W.parse_feed_html("<html></html>") == [])

print("=== D. 워터마크 ===")
d = tempfile.mkdtemp(); cp = os.path.join(d, "feed_cursor.json")
cur = W.FeedCursor(cp)
key = W.cursor_key(6035, 31)
now = max(x["boosted_at"] for x in arts) + 60

# Append synthetic articles (controller resolution + status filter validation)
old_art = dict(arts[0]); old_art["href"] = "https://www.daangn.com/kr/buy-sell/x-old/"; old_art["boosted_at"] = now - 3*3600; old_art["status"] = "ongoing"
reserved_art = dict(arts[0]); reserved_art["href"] = "https://www.daangn.com/kr/buy-sell/x-reserved/"; reserved_art["boosted_at"] = now - 3600; reserved_art["status"] = "reserved"
closed_art = dict(arts[0]); closed_art["href"] = "https://www.daangn.com/kr/buy-sell/x-closed/"; closed_art["boosted_at"] = now - 1800; closed_art["status"] = "closed"
arts_with_all = arts + [old_art, reserved_art, closed_art]

first = cur.new_articles(key, arts_with_all, now)
ongoing_recent = [x for x in arts_with_all if x["status"] == "ongoing" and now - x["boosted_at"] <= W.FIRST_VISIT_WINDOW_SEC]
ck("첫 방문은 최근 2시간만", first == ongoing_recent and len(first) < len(arts_with_all), f"{len(first)}/{len(arts_with_all)}")
ck("판매중 아닌 것 제외", all(x["status"] == "ongoing" for x in first) and "x-reserved" not in [x["href"] for x in first] and "x-closed" not in [x["href"] for x in first])
cur.advance(key, arts, now); cur.save()
cur2 = W.FeedCursor(cp)
ck("워터마크 저장·복원", cur2.get(key)["boosted_at"] == max(x["boosted_at"] for x in arts))
ck("같은 목록 다시 → 신규 0", cur2.new_articles(key, arts, now + 10) == [])
newer = dict(arts[0]); newer["href"] = "https://www.daangn.com/kr/buy-sell/x-new1/"; newer["boosted_at"] = now + 5
ck("워터마크 뒤 것만 신규", [x["href"] for x in cur2.new_articles(key, arts + [newer], now + 10)] == [newer["href"]])
same_ts = dict(newer); same_ts["href"] = "https://www.daangn.com/kr/buy-sell/x-new2/"; same_ts["boosted_at"] = cur2.get(key)["boosted_at"]
ck("워터마크와 같은 시각이라도 안 본 href 면 신규", same_ts["href"] in [x["href"] for x in cur2.new_articles(key, [same_ts], now + 10)])
ck("advance 는 실패(빈 목록)에 워터마크를 안 올린다",
   (cur2.advance(key, [], now + 999) or True) and cur2.get(key)["boosted_at"] == max(x["boosted_at"] for x in arts))
ck("폴백(시각 0)은 href 만으로 판정",
   W.FeedCursor(os.path.join(d, "c2.json")).new_articles("k", h[:3], now) == [x for x in h[:3] if x["status"] == "ongoing"])
# Degraded cursor file (missing "seen" key) should not crash
degraded_cp = os.path.join(d, "degraded.json")
with open(degraded_cp, "w", encoding="utf-8") as f:
    json.dump({"6035:31": {"boosted_at": 0}}, f)
degraded_cur = W.FeedCursor(degraded_cp)
degraded_result = degraded_cur.new_articles("6035:31", arts[:3], now)
ck("손상된 커서(missing seen)는 안전하게 처리", degraded_result == [x for x in arts[:3] if x["status"] == "ongoing" and now - x["boosted_at"] <= W.FIRST_VISIT_WINDOW_SEC])

n_ok = sum(1 for _, c in R if c); print(f"\n{n_ok}/{len(R)} PASS"); sys.exit(0 if n_ok == len(R) else 1)

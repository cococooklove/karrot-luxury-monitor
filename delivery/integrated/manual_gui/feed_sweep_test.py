# feed_sweep_test.py
"""피드 스윕 엔진 — 가짜 fetch 로 레인·속도·쿨다운·매칭·알림 규약 (네트워크 없음)."""
import json, os, sys, tempfile, threading, time
app_dir = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, app_dir); os.chdir(app_dir)
R = []
def ck(name, cond, extra=""):
    R.append((name, bool(cond))); print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")

from daangn.feed_sweep import FeedSweep
from daangn_ext import web_feed as W

d = tempfile.mkdtemp()
rules_fp = os.path.join(d, "alert_rules.json")
json.dump({"rules": [
    {"keyword": "루이비통 오버 더 문", "brand": "루이비통", "product": "오버 더 문", "min": 500000, "max": 1500000, "exclude": ["레플리카"]},
    {"keyword": "샤넬", "brand": "샤넬", "min": 1000000, "max": 3000000}],
    "applied_at": 1}, open(rules_fp, "w", encoding="utf-8"), ensure_ascii=False)
NOW = int(time.time())
def art(href, title, price, content="", ts=None, status="ongoing"):
    return {"href": href, "title": title, "content": content, "price": price, "status": status,
            "boosted_at": NOW - 60 if ts is None else ts, "created_at": NOW - 60, "region": "역삼동", "category": "31", "thumbnail": ""}
FEED = {
    ("6035", 31): [art("https://d/a1", "루이비통 오버더 문 팝니다", 900000),      # HIT (띄어쓰기 무시)
                   art("https://d/a2", "루이비통 오버 더 문 레플리카", 900000),  # CUT (제외어)
                   art("https://d/a3", "샤넬 클래식", 5000000),                  # WATCH (상한 초과)
                   art("https://d/a4", "가방", 900000, content="루이비통 오버 더 문 본문에만")],  # HIT (본문)
    ("6035", 14): [art("https://d/b1", "샤넬 지갑", 1500000)],                   # HIT
    ("382", 31): [], ("382", 14): [],
}
calls, blocked_once = [], {"n": 0}
def fake_fetch(name, rid, cat, proxy=None, get=None, timeout=25):
    calls.append((rid, cat, proxy, time.monotonic()))
    if proxy == "http://bad" and blocked_once["n"] == 0:
        blocked_once["n"] += 1; return None, "BLOCK"
    arts = FEED.get((str(rid), cat), [])
    return (arts, "OK") if arts else ([], "EMPTY")
slept = []
found, logs = [], []
cfg = {"regions": ["역삼동-6035", "신사동-382"], "categories": [31, 14], "proxies": ["http://good", "http://bad"],
       "rps": 100.0, "rest_min": 0, "rules_path": rules_fp, "cursor_fp": os.path.join(d, "feed_cursor.json"),
       "tg_token": None, "tg_chat": None, "already_notified": lambda href: href == "https://d/b1",
       "fetch": fake_fetch, "sleep": lambda s: slept.append(s)}
eng = FeedSweep(cfg, on_log=logs.append, on_found=found.append)
st = eng.cycle_once()

print("=== A. 한 사이클 ===")
ck("동×카테고리 4쌍 + 차단 재시도 1 = 요청 5", st["requests"] == 5, str(st))
ck("차단 프록시는 쿨다운·다른 프록시로 재시도", any(c[2] == "http://bad" for c in calls) and st["blocked"] == 1)
ids = sorted(p["id"] for p in found)
ck("HIT 2건(제목·본문) + WATCH 1건, CUT·중복 제외", ids == ["https://d/a1", "https://d/a3", "https://d/a4"], str(ids))
ck("verdict 표기", {p["id"]: p["verdict"] for p in found}["https://d/a3"] == "watch"
   and {p["id"]: p["verdict"] for p in found}["https://d/a1"] == "hit")
ck("payload 규약", set(found[0]) >= {"id", "region", "title", "price", "url", "image", "desc", "boostedAt", "status", "keyword", "verdict"})
ck("keyword = 걸린 조건 라벨", "오버 더 문" in {p["id"]: p["keyword"] for p in found}["https://d/a1"])
ck("앱이 이미 알린 매물은 안 낸다(b1)", "https://d/b1" not in ids)
ck("통계", st["hit"] == 2 and st["watch"] == 1 and st["new"] == 3, str(st))

print("=== B. 두 번째 사이클 ===")
found.clear(); calls.clear()
FEED[("6035", 31)].append(art("https://d/a5", "샤넬 보이백", 2000000, ts=NOW))
st2 = eng.cycle_once()
ck("워터마크 뒤 신규만", [p["id"] for p in found] == ["https://d/a5"], str([p["id"] for p in found]))
ck("커서 파일 저장", os.path.exists(cfg["cursor_fp"]))

print("=== C. 속도·레인 ===")
calls.clear()
slow = dict(cfg, rps=2.0, proxies=["http://p1"], fetch=lambda *a, **k: ([], "EMPTY"), sleep=lambda s: slept.append(s))
slept.clear()
FeedSweep(slow, on_log=logs.append).cycle_once()
ck("레인당 rps 준수 — 요청 사이 0.5s sleep", slept and abs(min(slept) - 0.5) < 0.01, str(slept[:3]))
ck("레인 수 = 프록시 수(직결이면 1)", FeedSweep(dict(cfg, proxies=[]), on_log=logs.append)._lanes() == 1
   and FeedSweep(cfg, on_log=logs.append)._lanes() == 2)

print("=== D. 전멸·중단 ===")
dead = dict(cfg, proxies=["http://x"], fetch=lambda *a, **k: (None, "BLOCK"))
e2 = FeedSweep(dead, on_log=logs.append); s3 = e2.cycle_once()
ck("전 프록시 차단 → 사이클 중단 + 로그", s3["blocked"] >= 1 and any("프록시" in m and "정지" in m for m in logs))
e3 = FeedSweep(dict(cfg, rest_min=0.001), on_log=logs.append)
th = threading.Thread(target=e3.run, daemon=True); th.start(); time.sleep(0.3); e3.stop(); th.join(3)
ck("run/stop 수명", not th.is_alive())
ck("토큰이 헤더에 없다(요청 함수가 web_feed 것)", eng._fetch is fake_fetch and "authorization" not in {k.lower() for k in W.DEFAULT_HEADERS})

logs.clear()
err_cfg = dict(cfg, proxies=[], fetch=lambda *a, **k: (None, "ERR"))
e4 = FeedSweep(err_cfg, on_log=logs.append)
s4 = e4.cycle_once()
ck("요청 에러 전량 err 로 집계 + 로더 경로 변경 의심 로그",
   s4["err"] == s4["requests"] and any("로더 경로 변경 의심" in m for m in logs), str(s4))

logs.clear()
block_cfg = dict(cfg, proxies=["http://a", "http://b"], fetch=lambda *a, **k: (None, "BLOCK"))
e5 = FeedSweep(block_cfg, on_log=logs.append)
s5 = e5.cycle_once()
ck("이중 차단은 err 아님 — 로더 이상으로 오판하지 않는다",
   s5["err"] == 0 and s5["blocked"] >= 2 and not any("로더 경로 변경 의심" in m for m in logs), str(s5))

n_ok = sum(1 for _, c in R if c); print(f"\n{n_ok}/{len(R)} PASS"); sys.exit(0 if n_ok == len(R) else 1)

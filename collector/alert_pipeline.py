"""알림 → 매물 해석 파이프라인.

notification_listener 가 쌓은 알림(제목/본문)을 실제 매물 레코드로 바꾼다.
알림을 보낸 계정의 동네 좌표로 앱 API 검색을 걸어 제목이 일치하는 문서를 찾는다.
알림이 딥링크에 매물 id 를 실어 오면 검색 없이 그대로 쓴다.

요청량 = 신규 매물 수. 폴링(지역×키워드×주기)과 달리 daily_cap 을 거의 안 먹는다.

입력: data/alert_hits.jsonl, data/accounts.json
산출: data/listings_luxury.jsonl (parse_luxury 정규화 + 리셀 지표)

accounts.json 에 계정별 동네가 필요하다:
  {"name":"acc1", ..., "region_id":"6128", "lat":37.498, "lon":127.026}

용법:
  python3 collector/alert_pipeline.py --once
  python3 collector/alert_pipeline.py                 # 상시 (listener 와 같이 띄움)
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app_search import AppSearch  # noqa: E402
from parse_luxury import normalize  # noqa: E402
from pool import Worker  # noqa: E402

HITS = "data/alert_hits.jsonl"
ACCOUNTS = "data/accounts.json"
OUT = "data/listings_luxury.jsonl"
STATE = "data/alert_resolved.json"


def load_state(path=STATE):
    if os.path.exists(path):
        try:
            return set(json.load(open(path, encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_state(done, path=STATE):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(done), f)


def read_hits(path=HITS):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        if line.strip():
            out.append(json.loads(line))
    return out


class Resolver:
    """계정별 AppSearch 를 재사용한다(계정=동네=좌표)."""

    def __init__(self, accounts_path=ACCOUNTS, use_frida=False):
        if not os.path.exists(accounts_path):
            raise SystemExit(f"{accounts_path} 없음")
        self.specs = {s["name"]: s
                      for s in json.load(open(accounts_path, encoding="utf-8"))}
        self.use_frida = use_frida
        self._cache = {}

    def _for(self, account):
        if account in self._cache:
            return self._cache[account]
        spec = self.specs.get(account)
        if not spec:
            return None
        worker = Worker(spec, use_frida=self.use_frida)
        search = AppSearch.from_worker(worker)
        self._cache[account] = (worker, search, spec)
        return self._cache[account]

    def resolve(self, hit):
        """알림 1건 → 매물 document. 못 찾으면 None."""
        got = self._for(hit.get("account"))
        if not got:
            return None, "계정 미등록"
        worker, search, spec = got
        region = spec.get("region_id")
        lat, lon = spec.get("lat"), spec.get("lon")
        if not (region and lat and lon):
            return None, f"{hit.get('account')} 에 region_id/lat/lon 없음"
        # 알림 본문이 매물 제목인 경우가 많다. 제목줄이 키워드면 본문을 쓴다.
        query = hit.get("text") or hit.get("title")
        if not query:
            return None, "제목/본문 없음"
        try:
            doc = search.find_by_title(query, region, lat, lon)
        except Exception as e:
            return None, f"검색 실패 {str(e)[:80]}"
        return doc, None if doc else "매물 미발견"

    def close(self):
        for worker, search, _ in self._cache.values():
            search.close()
            worker.close()


def to_record(doc, hit):
    """앱 API document → 표준 레코드. 앱 스키마 필드명을 맞춰 넣는다."""
    src = {
        "id": doc.get("id"),
        "title": doc.get("title"),
        "content": doc.get("content") or doc.get("body") or "",
        "price": doc.get("price"),
        "status": doc.get("status"),
        "region_name": doc.get("regionName"),
        "images": ([doc["firstImage"]["url"]]
                   if isinstance(doc.get("firstImage"), dict)
                   and doc["firstImage"].get("url") else []),
        "viewCount": doc.get("viewCount"),
        "chatCount": doc.get("chatRoomsCount"),
        "createdAt": doc.get("createdAt"),
        "republishedAt": doc.get("publishedAt"),
        "href": f"https://www.daangn.com/kr/buy-sell/-{doc.get('id')}/",
        "user": doc.get("user") or {},
    }
    rec = normalize(src)
    rec["watch_count"] = doc.get("watchesCount")
    rec["source"] = "keyword_alert"
    rec["alert_account"] = hit.get("account")
    rec["alert_ts"] = hit.get("ts")
    rec.pop("_raw", None)
    return rec


def run_once(resolver, done, out_path=OUT, verbose=True):
    hits = read_hits()
    pending = [h for h in hits if h.get("fp") and h["fp"] not in done]
    if not pending:
        return 0, 0
    saved = failed = 0
    for h in pending:
        doc, err = resolver.resolve(h)
        done.add(h["fp"])
        if not doc:
            failed += 1
            if verbose:
                print(f"  ✗ {h.get('text', '')[:40]} — {err}")
            continue
        rec = to_record(doc, h)
        if rec.get("crawl_blocked"):
            if verbose:
                print(f"  · 크롤거부 판매자 — 제외 {rec.get('id')}")
            continue
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        saved += 1
        if verbose:
            print(f"  ✓ [{rec.get('brand')}] {rec.get('title')} "
                  f"{rec.get('price_num')} resell_ok={rec.get('resell_ok')}")
    save_state(done)
    return saved, failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=float, default=30.0)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    resolver = Resolver()
    done = load_state()
    print(f"해석 대기 감시 시작 (기해석 {len(done)}건)")
    try:
        while True:
            saved, failed = run_once(resolver, done, args.out)
            if saved or failed:
                print(f"저장 {saved} · 미해석 {failed} → {args.out}")
            if args.once:
                return
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n중단.")
    finally:
        save_state(done)
        resolver.close()


if __name__ == "__main__":
    main()

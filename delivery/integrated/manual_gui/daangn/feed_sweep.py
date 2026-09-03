# daangn/feed_sweep.py
"""피드 스윕 — 동×카테고리 최신 피드를 돌며 조건표로 거른다. 계정 없음.

SweepEngine(키워드 검색) 과 콜백 규약이 같다(on_log/on_found/on_status) —
GUI 는 QThread 어댑터, 헤드리스는 plain Thread 로 같은 cfg 를 돌린다.
레인 = 프록시 수(직결이면 1), 레인당 초당 요청은 cfg["rps"] 로 고정한다.
"""
from __future__ import annotations

import queue
import threading
import time
from datetime import datetime

from daangn.notify import TelegramSender, item_block, match_line
from daangn_ext import web_feed as W
from daangn_ext.alert_rules import HIT, WATCH, RuleTable


def _noop(*a, **k):
    pass


def _region_pair(code: str):
    """'역삼동-6035' → ('역삼동', '6035'). 이름에 '-' 가 있어도 마지막 것만 자른다."""
    name, _, rid = str(code).rpartition("-")
    return (name or code), rid


class FeedSweep:
    def __init__(self, cfg: dict, on_log=None, on_found=None, on_status=None):
        self.cfg = cfg
        self.on_log = on_log or _noop
        self.on_found = on_found or _noop
        self.on_status = on_status or _noop
        self._stop = False
        self._fetch = cfg.get("fetch") or W.fetch_feed
        self._sleep = cfg.get("sleep") or time.sleep
        self._rules_path = cfg.get("rules_path", "./data/alert_rules.json")
        self._rules_mtime = None
        self._rules = None
        self._pool = W.ProxyPool(cfg.get("proxies") or [])
        self._cursor = W.FeedCursor(cfg.get("cursor_fp", "./data/feed_cursor.json"))
        self._tg = TelegramSender(cfg.get("tg_token"), cfg.get("tg_chat"),
                                  log=self._log, should_stop=lambda: self._stop)
        self._lock = threading.Lock()

    # ── 공통 ──
    def _log(self, m):
        self.on_log(m)

    def stop(self):
        self._stop = True

    def _lanes(self) -> int:
        return max(1, len(self.cfg.get("proxies") or []))

    def _rules_now(self) -> RuleTable:
        import os
        try:
            mt = os.path.getmtime(self._rules_path)
        except OSError:
            mt = None
        if self._rules is None or mt != self._rules_mtime:
            self._rules_mtime, self._rules = mt, RuleTable.load(self._rules_path)
        return self._rules

    def _pairs(self):
        cats = [int(c) for c in (self.cfg.get("categories") or W.DEFAULT_CATEGORIES)]
        for code in self.cfg.get("regions") or []:
            name, rid = _region_pair(code)
            for c in cats:
                yield name, rid, c

    # ── 한 사이클 ──
    def cycle_once(self) -> dict:
        stat = {"requests": 0, "new": 0, "hit": 0, "watch": 0, "blocked": 0, "err": 0, "seconds": 0.0}
        t0 = time.monotonic()
        q: queue.Queue = queue.Queue()
        for p in self._pairs():
            q.put(p)
        total = q.qsize()
        rps = float(self.cfg.get("rps") or 1.0)
        gap = 1.0 / rps if rps > 0 else 0.0
        already = self.cfg.get("already_notified") or (lambda _h: False)
        rules = self._rules_now()
        now = int(time.time())
        done = [0]

        def lane():
            while not self._stop:
                try:
                    name, rid, cat = q.get_nowait()
                except queue.Empty:
                    return
                for attempt in range(2):
                    proxy = self._pool.pick()
                    if proxy is None and self._pool.all_blocked():
                        with self._lock:
                            stat["blocked"] += 1
                        self._log("[피드] 프록시 전멸 — 피드 정지, 프록시를 확인하세요")
                        self._stop = True
                        return
                    with self._lock:
                        stat["requests"] += 1
                    arts, kind = self._fetch(name, rid, cat, proxy=proxy)
                    if kind == "BLOCK":
                        with self._lock:
                            stat["blocked"] += 1
                        self._pool.block(proxy)
                        self._log(f"[피드] {name} 차단 신호 — 프록시 교체 ({proxy or '직결'})")
                        continue
                    break
                if gap:
                    self._sleep(gap)
                if arts is None:
                    with self._lock:
                        stat["err"] += 1
                    continue                     # ERR: 워터마크 안 올림, 다음 사이클
                key = W.cursor_key(rid, cat)
                with self._lock:
                    fresh = self._cursor.new_articles(key, arts, now)
                    if arts:
                        self._cursor.advance(key, arts, now)
                for a in fresh:
                    if already(a["href"]):
                        continue
                    verdict, rule = rules.verdict(a["title"], a["price"], a["content"])
                    if verdict not in (HIT, WATCH):
                        continue
                    with self._lock:
                        stat["new"] += 1
                        stat["hit" if verdict == HIT else "watch"] += 1
                    self._emit(a, name, rule, verdict)
                with self._lock:
                    done[0] += 1
                    self.on_status(f"피드 {done[0]}/{total} · {name}")

        threads = [threading.Thread(target=lane, name=f"feed-{i}", daemon=True)
                   for i in range(self._lanes())]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self._cursor.save()
        self._flush()
        if stat["requests"] > 0 and stat["err"] / stat["requests"] > 0.5:
            self._log(f"[피드] 로더 경로 변경 의심 — 실패 {stat['err']}/{stat['requests']}")
        stat["seconds"] = round(time.monotonic() - t0, 1)
        return stat

    def _emit(self, a, region, rule, verdict):
        label = rule.label() if rule else ""
        url = a["href"]
        stamp = datetime.fromtimestamp(a["boosted_at"]).isoformat() if a.get("boosted_at") else ""
        if verdict == HIT:
            self._log(match_line(label, a["title"], a["price"], region, source="동 피드", url=url))
            self._tg.enqueue_item(item_block("신규 매물", region, a["title"], a["price"], url,
                                             stamp=stamp or None, stamp_label="등록"))
        self.on_found({
            "id": url, "region": region, "title": a["title"], "price": a["price"], "url": url,
            "image": a.get("thumbnail", ""), "desc": a.get("content", ""),
            "boostedAt": stamp, "status": "신규", "keyword": label,
            "verdict": "hit" if verdict == HIT else "watch",
        })

    def _flush(self, final=False):
        if self._tg.pending():
            if final:
                self._tg.flush(deadline=time.monotonic() + 30, ignore_stop=True)
            else:
                self._tg.flush()

    # ── 수명 ──
    def run(self):
        rest = float(self.cfg.get("rest_min", 2)) * 60.0
        n = 0
        self._log(f"[피드] 시작 — 동 {len(self.cfg.get('regions') or [])}곳 × 카테고리 "
                  f"{list(self.cfg.get('categories') or W.DEFAULT_CATEGORIES)} · 레인 {self._lanes()}")
        try:
            while not self._stop:
                n += 1
                st = self.cycle_once()
                self._log(f"[피드] 사이클 {n}: 요청 {st['requests']} · 신규 {st['new']} "
                          f"(알림 {st['hit']} · 추적 {st['watch']}) · 차단 {st['blocked']} · {st['seconds']}s")
                if self._stop:
                    break
                for _ in range(int(rest * 10)):
                    if self._stop:
                        break
                    self._sleep(0.1)
        finally:
            self._flush(final=True)
            self._log("[피드] 정지")

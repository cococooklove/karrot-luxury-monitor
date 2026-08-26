"""
auto 독립 러너 — aiohttp 레인 병렬로 전국을 돌며 신규 매물만 뽑아낸다.

`delivery/integrated/auto/` 는 클라 프로젝트에 얹는 드롭인 패키지(`daangn.model` 필요)라
그 자체로는 못 돈다. 이 파일은 그 의존 없이 `daangn_ext` 만으로 도는 실행 가능한 러너다.

동작:
  전국 구 목록 로드 → 조건(키워드/추가/제외/가격)마다 레인 병렬 수집
  → 지역이 끝나는 즉시 sqlite 중복제거 → 신규/가격변동만 JSONL 적재 + 콘솔 출력
  → 사이클 사이 랜덤 휴식 → 반복 (Ctrl-C 로 안전 종료)

핵심 제약(실측):
  - 같은 IP 동시요청 = 전멸(8/8 빈응답) → 레인은 프록시를 샤딩해 쓴다
  - 레인당 IP 가 1개면 빈응답 시 교체할 곳이 없다 → 레인당 최소 MIN_IP_PER_LANE 개

용법:
    python delivery/auto_runner.py --config auto_config.json
    python delivery/auto_runner.py --keyword "샤넬 가방" --proxies proxies.txt \\
        --regions OUT.json --lanes 4 --once

config(JSON) 예:
{
  "regions": "delivery/integrated/manual_gui/OUT.json",
  "proxies": "delivery/integrated/manual_gui/proxies.txt",
  "lanes": 0,                      // 0 = 자동(프록시 수 기준)
  "rest": [30, 90],                // 사이클 사이 휴식(초)
  "gap":  [0.4, 1.2],              // 지역 사이 휴식(초)
  "db":   "data/auto_seen.db",
  "out":  "data/auto_new.jsonl",
  "conditions": [
    {"keyword": "샤넬", "extra": ["정품"], "exclude": ["레플", "가품"],
     "min": 500000, "max": 30000000}
  ]
}
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sqlite3
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from daangn_ext.adaptive import collect_lanes_async, load_gu_regions   # noqa: E402
from daangn_ext.rest_scheduler import asleep_between                   # noqa: E402
from daangn_ext.search_filters import KeywordRule                      # noqa: E402
from daangn_ext import throttle                                        # noqa: E402

MIN_IP_PER_LANE = 3       # 레인당 최소 전용 IP (이하면 빈응답 교체 여지가 없다)
MAX_LANES = 16


class _P:
    """KeywordRule 이 기대하는 객체 형태로 감싸는 어댑터."""
    def __init__(self, a: dict):
        self.name = a.get("title", "")
        self.description = a.get("content", "")


def plan_lanes(n_proxy: int, want: int = 0) -> int:
    """레인 수. 프록시 수를 넘을 수 없고, 레인당 IP 를 MIN_IP_PER_LANE 이상 유지."""
    if n_proxy <= 1:
        return 1
    cap = max(1, n_proxy // MIN_IP_PER_LANE)
    return max(1, min(want or cap, cap, MAX_LANES))


class Store:
    """중복제거 + 가격변동 감지. id 기준, 가격이 바뀌면 '변동'으로 다시 알린다."""

    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS seen("
                        "id TEXT PRIMARY KEY, price INTEGER, region TEXT, title TEXT)")
        self.db.commit()

    def classify(self, art: dict, region: str) -> tuple[str, int | None]:
        """('new'|'changed'|'dup', 이전가격) 반환 후 상태를 갱신."""
        aid = str(art.get("id"))
        try:
            price = int(float(art.get("price") or 0))
        except (TypeError, ValueError):
            price = 0
        cur = self.db.execute("SELECT price FROM seen WHERE id=?", (aid,)).fetchone()
        if cur is None:
            self.db.execute("INSERT INTO seen VALUES(?,?,?,?)",
                            (aid, price, region, art.get("title", "")))
            return "new", None
        if cur[0] != price:
            self.db.execute("UPDATE seen SET price=? WHERE id=?", (price, aid))
            return "changed", cur[0]
        return "dup", cur[0]

    def commit(self):
        self.db.commit()

    def close(self):
        try:
            self.db.commit()
            self.db.close()
        except Exception:
            pass


def load_cfg(args) -> dict:
    cfg = {}
    if args.config:
        with open(args.config, encoding="utf-8") as f:
            cfg = json.load(f)
    if args.keyword:
        cfg["conditions"] = [{"keyword": args.keyword}]
    for k, v in (("regions", args.regions), ("proxies", args.proxies),
                 ("db", args.db), ("out", args.out)):
        if v:
            cfg[k] = v
    if args.lanes is not None:
        cfg["lanes"] = args.lanes
    cfg.setdefault("regions", "delivery/integrated/manual_gui/OUT.json")
    cfg.setdefault("db", "data/auto_seen.db")
    cfg.setdefault("out", "data/auto_new.jsonl")
    cfg.setdefault("rest", [30, 90])
    cfg.setdefault("gap", [0.4, 1.2])
    cfg.setdefault("lanes", 0)
    if not cfg.get("conditions"):
        raise SystemExit("조건 없음 — --keyword 또는 config 의 conditions 를 지정하라")
    return cfg


async def run(cfg: dict, once: bool = False, limit: int = 0) -> int:
    regions = load_gu_regions(cfg["regions"])
    if limit:
        regions = regions[:limit]
    proxies = []
    if cfg.get("proxies"):
        with open(cfg["proxies"], encoding="utf-8") as f:
            proxies = [l.strip() for l in f if l.strip()]
    lanes = plan_lanes(len(proxies), int(cfg.get("lanes") or 0))
    store = Store(cfg["db"])
    os.makedirs(os.path.dirname(cfg["out"]) or ".", exist_ok=True)
    out = open(cfg["out"], "a", encoding="utf-8")

    stop = {"flag": False}

    def _sig(*_):
        if stop["flag"]:                       # 두 번 누르면 즉시
            raise KeyboardInterrupt
        stop["flag"] = True
        print("\n[정지 요청] 진행 중인 지역까지 마치고 종료…", flush=True)

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(s, _sig)
        except Exception:
            pass

    print(f"지역 {len(regions)}개 · 프록시 {len(proxies)}개 · 레인 {lanes}"
          + (f" (레인당 IP {len(proxies)//lanes}개)" if lanes > 1 else " (순차)")
          + f" · 조건 {len(cfg['conditions'])}개", flush=True)

    cycle = 0
    total_new = 0
    try:
        while not stop["flag"]:
            cycle += 1
            print(f"\n── 사이클 {cycle} ──", flush=True)
            for cond in cfg["conditions"]:
                if stop["flag"]:
                    break
                rule = KeywordRule(required=[cond["keyword"]],
                                   extra=cond.get("extra") or None, extra_mode="and",
                                   exclude=cond.get("exclude") or None)
                kw = cond["keyword"]
                done = [0]
                new_n = [0]
                chg_n = [0]
                missed = [0]

                def on_result(reg, arts, st, _rule=rule, _cond=cond, _kw=kw):
                    done[0] += 1
                    # missed = 재시도 소진으로 "확인 못 한" 구간. 진짜 0건과 반드시 구분.
                    if st.get("missed"):
                        missed[0] += len(st["missed"])
                        print(f"   ⚠️ [{reg['in']}] 가격구간 {len(st['missed'])}개 확인 실패"
                              " (IP/세션) — 다음 사이클 재시도. 프록시 부족 의심", flush=True)
                    # 브랜드 단독 키워드가 억제되는 경우(실측: '샤넬' 0건 ↔ '샤넬가방' 11건)
                    if st.get("expanded"):
                        print(f"   [우회] '{_kw}' 응답 억제 → '{st['expanded'][0]}' 로 대체 수집",
                              flush=True)
                    elif st.get("suppressed"):
                        print(f"   [억제] '{_kw}' @ {reg['in']} 응답 억제 확인 "
                              "(대체 키워드도 실패) — 진짜 0건이 아닐 수 있음", flush=True)
                    keep = [a for a in arts if _rule.match(_P(a))]
                    lo, hi = _cond.get("min"), _cond.get("max")
                    if lo is not None or hi is not None:
                        def inrange(a):
                            try:
                                p = int(float(a.get("price") or 0))
                            except (TypeError, ValueError):
                                return False
                            return (lo is None or p >= lo) and (hi is None or p <= hi)
                        keep = [a for a in keep if inrange(a)]
                    r_new = r_chg = 0
                    for a in keep:
                        kind, prev = store.classify(a, reg["in"])
                        if kind == "dup":
                            continue
                        if kind == "new":
                            new_n[0] += 1
                            r_new += 1
                        else:
                            chg_n[0] += 1
                            r_chg += 1
                        rec = {"ts": datetime.now().isoformat(timespec="seconds"),
                               "kind": kind, "prev_price": prev, "region": reg["in"],
                               "keyword": _kw, "id": a.get("id"),
                               "title": a.get("title"), "price": a.get("price"),
                               "href": a.get("href")}
                        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        mark = "🆕" if kind == "new" else f"💱{prev}→"
                        print(f"   {mark} [{reg['in']}] {a.get('title','')[:38]} "
                              f"{a.get('price')}", flush=True)
                    if r_new or r_chg:
                        store.commit()
                        out.flush()
                    print(f"[{done[0]}/{len(regions)}] {reg['in']} '{_kw}' "
                          f"수집 {len(keep)} · 신규 {r_new}"
                          + (f" · 변동 {r_chg}" if r_chg else "")
                          + f"  (누적 신규 {new_n[0]})", flush=True)

                t0 = time.time()
                _, sm = await collect_lanes_async(
                    kw, regions, proxies=proxies or None, lanes=lanes,
                    only_on_sale=True, access_token=cfg.get("access_token"),
                    should_stop=lambda: stop["flag"],
                    rest_range=tuple(cfg["gap"]), on_result=on_result)
                total_new += new_n[0]
                el = time.time() - t0
                print(f"[완료] '{kw}' {sm['unique']}건 · 신규 {new_n[0]} 변동 {chg_n[0]} "
                      f"· 요청 {sm['requests']} · {el:.0f}s"
                      + (f" · 미처리 {sm['skipped']}개" if sm.get("skipped") else "")
                      + (f" · ⚠️확인실패 구간 {missed[0]}개" if missed[0] else ""),
                      flush=True)
            if once or stop["flag"]:
                break
            d = await asleep_between(*throttle.scale_range(tuple(cfg["rest"])))
            print(f"[휴식] {d:.0f}s", flush=True)
    except KeyboardInterrupt:
        print("\n[강제 종료]", flush=True)
    finally:
        store.close()
        out.close()
    print(f"\n[종료] 사이클 {cycle} · 누적 신규 {total_new}건 → {cfg['out']}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="당근 중고 명품 자동 모니터(레인 병렬)")
    ap.add_argument("--config", help="JSON 설정 파일")
    ap.add_argument("--keyword", help="단일 키워드(설정 파일 없이 빠른 실행)")
    ap.add_argument("--regions", help="OUT.json 경로")
    ap.add_argument("--proxies", help="프록시 목록 파일(1줄 1개)")
    ap.add_argument("--lanes", type=int, help="레인 수. 0/미지정이면 자동")
    ap.add_argument("--db", help="중복제거 sqlite 경로")
    ap.add_argument("--out", help="신규/변동 JSONL 출력 경로")
    ap.add_argument("--once", action="store_true", help="1사이클만")
    ap.add_argument("--limit", type=int, default=0, help="지역 앞 N개만(시험용)")
    args = ap.parse_args()
    sys.exit(asyncio.run(run(load_cfg(args), once=args.once, limit=args.limit)))


if __name__ == "__main__":
    main()

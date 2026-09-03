# -*- coding: utf-8 -*-
"""서버 실측 — 프록시 1개·초당 1요청으로 1시간 피드를 돌려 200 비율·응답시간·크기를 기록한다.

    python tools/feed_smoke.py [--proxy http://...] [--minutes 60] [--rps 1]
결과: data/feed_smoke.json + 표준출력 요약. 계정 토큰은 쓰지 않는다.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from daangn_ext import web_feed as W

DEFAULT_SWEEP_SIDO = ("서울특별시", "경기도")  # main.DEFAULT_SWEEP_SIDO 와 같은 값


def _default_sweep_regions_fallback(out_json="./OUT.json"):
    """main.default_sweep_regions 와 같은 규칙 — PyQt 없는 서버에서 main 을 못
    불러올 때 이걸로 대신한다(코드 모양 '이름-id' 는 그대로다)."""
    try:
        with open(out_json, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    out, seen = [], set()
    for block in data or []:
        if block.get("name1") not in DEFAULT_SWEEP_SIDO:
            continue
        for loc in block.get("locations") or []:
            code = f"{loc.get('name')}-{loc.get('id')}"
            if code in seen:
                continue
            seen.add(code)
            out.append(code)
    return out


def load_sweep_regions(out_json="./OUT.json"):
    """main.default_sweep_regions 를 쓰되, PyQt 임포트 실패 시 직접 읽는다.

    main 을 임포트하면 PyQt 가 딸려 온다 — GUI 없는 서버에도 이 도구는 돌아야
    하므로 임포트를 지연시키고, 실패하면 OUT.json 을 직접 읽는다."""
    try:
        from main import default_sweep_regions
        return default_sweep_regions(out_json)
    except Exception:
        return _default_sweep_regions_fallback(out_json)


ap = argparse.ArgumentParser()
ap.add_argument("--proxy")
ap.add_argument("--minutes", type=int, default=60)
ap.add_argument("--rps", type=float, default=1.0)
a = ap.parse_args()
regions = load_sweep_regions("./OUT.json")
stat = {"ok": 0, "empty": 0, "block": 0, "err": 0, "fallback": 0, "bytes": 0, "sec": []}
t_end = time.time() + a.minutes * 60
i = 0


def timed_get(url, proxy, timeout):
    from curl_cffi import requests
    t0 = time.monotonic()
    r = requests.get(url, headers=W.DEFAULT_HEADERS, impersonate="safari_ios",
                     timeout=timeout, proxy=proxy)
    stat["sec"].append(round(time.monotonic() - t0, 2))
    stat["bytes"] += len(r.content)
    return r.status_code, r.text


while time.time() < t_end:
    if not regions:
        print("지역 목록이 비었습니다 — OUT.json 을 확인하세요")
        break
    code = regions[i % len(regions)]
    i += 1
    name, _, rid = code.rpartition("-")
    arts, kind = W.fetch_feed(name, rid, 31, proxy=a.proxy, get=timed_get)
    stat[kind.lower()] = stat.get(kind.lower(), 0) + 1
    if i % 50 == 0:
        print(f"{i}회 ok={stat['ok']} empty={stat['empty']} block={stat['block']} err={stat['err']} "
              f"평균 {sum(stat['sec'])/len(stat['sec']):.2f}s 평균크기 {stat['bytes']//max(1,i)//1024}KB", flush=True)
    time.sleep(1.0 / a.rps)

os.makedirs("./data", exist_ok=True)
json.dump(stat, open("./data/feed_smoke.json", "w"), ensure_ascii=False)
print("done", {k: v for k, v in stat.items() if k != "sec"})

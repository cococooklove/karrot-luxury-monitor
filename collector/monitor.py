"""
신규 매물 모니터 — 지역 목록 주기 폴링 + 이전 스냅샷 diff → 신규만 알림.

용법:
  python collector/monitor.py --path "/api/v1/listings" \
      --region-param region_id --regions 1234 5678 \
      --interval 300

상태: data/seen_<region>.json (이미 본 매물 id 집합)
신규 감지 시 콘솔 출력 + data/new_listings.jsonl 적재.
알림 연동(텔레그램/슬랙 등)은 notify() 채우면 됨.
"""
import argparse
import json
import os
import random
import time
from karrot_api import KarrotClient
from parse import extract
from token_source import access_provider

STATE = "data"
NEWLOG = "data/new_listings.jsonl"


def load_seen(region):
    p = os.path.join(STATE, f"seen_{region}.json")
    if os.path.exists(p):
        return set(json.load(open(p, encoding="utf-8")))
    return set()


def save_seen(region, ids):
    p = os.path.join(STATE, f"seen_{region}.json")
    json.dump(sorted(ids, key=str), open(p, "w", encoding="utf-8"))


def notify(item):
    # TODO: 텔레그램/슬랙 웹훅 연결. 지금은 콘솔.
    print(f"  [신규] {item.get('title')} | {item.get('price')} | {item.get('region')}")


def poll_once(client, region, region_param):
    params = dict(client.tpl.get("query", {}))
    params[region_param] = region
    resp = client.request(params=params)
    if resp.status_code != 200:
        print(f"  region {region}: {resp.status_code} 실패")
        return
    items = extract(resp.text)
    seen = load_seen(region)
    fresh = [it for it in items if str(it["id"]) not in seen]
    if fresh:
        with open(NEWLOG, "a", encoding="utf-8") as f:
            for it in fresh:
                notify(it)
                f.write(json.dumps({"region": region, **it}, ensure_ascii=False) + "\n")
                seen.add(str(it["id"]))
        save_seen(region, seen)
    print(f"  region {region}: 총 {len(items)}, 신규 {len(fresh)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True)
    ap.add_argument("--region-param", default="region_id")
    ap.add_argument("--regions", nargs="+", required=True)
    ap.add_argument("--interval", type=int, default=300, help="폴링 주기 초")
    ap.add_argument("--once", action="store_true", help="1회만")
    ap.add_argument("--accounts", help="accounts.json 경로. 주면 최신 access 를 매 요청 주입"
                                        "(온디바이스 수확 연동). 미지정 시 캡처 박제 헤더 사용")
    ap.add_argument("--code", help="특정 계정 code 만 사용. 미지정 시 남은 수명 최장 계정")
    args = ap.parse_args()

    os.makedirs(STATE, exist_ok=True)
    provider = None
    if args.accounts:
        provider = access_provider(args.accounts, args.code)
        code, _, exp_in = provider.info()
        print(f"[token] accounts={args.accounts} code={code or '(auto)'} "
              f"남은수명={exp_in}s" + (" ⚠️만료" if exp_in <= 0 else ""))
    client = KarrotClient(args.path, token_provider=provider)
    try:
        while True:
            ts = time.strftime("%H:%M:%S")
            print(f"[{ts}] poll {len(args.regions)} regions")
            for region in args.regions:
                poll_once(client, region, args.region_param)
            if args.once:
                break
            # 주기 + 지터 (등간격 패턴 회피)
            time.sleep(args.interval + random.uniform(0, args.interval * 0.3))
    except KeyboardInterrupt:
        print("중단.")
    finally:
        client.close()


if __name__ == "__main__":
    main()

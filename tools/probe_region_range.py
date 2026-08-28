#!/usr/bin/env python3
"""알림 반경(range) 탐색 — 계정당 커버 지역 늘리기.

발견 엔드포인트:
  GET  webapp/api/v24/keyword/user_preferences/region_ranges/{regionId}.json
  GET  .../location_range_levels/{h3Index}.json
계정당 ranged_regions_count 를 최대로 키우면 전국에 필요한 계정 수 감소.
"""
import base64, json, sys
import httpx

WEBAPP = "webapp.kr.karrotmarket.com"
UA = "Karrot/26.34.0 (com.towneers.www; build:263400; Android 33)"


def freshest(fp="data/accounts.json"):
    def exp(t):
        try:
            p = t.split(".")[1]; p += "=" * (-len(p) % 4)
            return json.loads(base64.urlsafe_b64decode(p)).get("exp", 0)
        except Exception:
            return 0
    best = None
    for a in json.load(open(fp, encoding="utf-8")):
        acc = a.get("access") or ""
        if acc and (best is None or exp(acc) > exp(best)):
            best = acc
    return best


def main():
    token = freshest()
    if not token:
        print("❌ 토큰 없음"); sys.exit(2)
    h = {"accept": "application/json", "x-user-agent": UA, "authorization": f"Bearer {token}"}
    try:
        cfg = json.load(open("data/config.json", encoding="utf-8")).get("headers", {})
        for k in ("x-user-agent", "x-device-identity", "x-ad-id", "x-country-code",
                  "x-karrot-session-id"):
            if k in cfg:
                h[k] = cfg[k]
    except Exception:
        pass
    c = httpx.Client(http2=True, timeout=15)

    # 현재 구독 동네(regionId) 확인
    r = c.get(f"https://{WEBAPP}/api/v24/keyword/user_keywords.json", headers=h)
    subs = r.json().get("subscription_infos", []) if r.status_code == 200 else []
    print("구독 동네:", [(s.get("id"), s.get("name"), s.get("ranged_regions_count"),
                      s.get("range_level_distance")) for s in subs])

    for s in subs:
        rid = s.get("id")
        print(f"\n── region {rid} ({s.get('name')}) ──")
        for path in [
            f"/api/v24/keyword/user_preferences/region_ranges/{rid}.json",
            f"/api/v24/keyword/user_preferences/region_ranges/{rid}/map_data.json",
        ]:
            try:
                rr = c.get(f"https://{WEBAPP}{path}", headers=h)
                print(f"GET {path} → {rr.status_code}")
                if rr.status_code == 200 and "map_data" in path:
                    d = rr.json()
                    print(f"  현재range={d.get('range')} default={d.get('default_range')}")
                    for lv in d.get("region_ranges", []):
                        ids = lv.get("region_ids") or lv.get("regions") or lv.get("region_range") or []
                        print(f"    · name={lv.get('name')} distance={lv.get('distance')} "
                              f"지역수={len(ids) if isinstance(ids, list) else ids} 키={list(lv)}")
                elif rr.status_code == 200:
                    print("  ", rr.text[:300].replace("\n", " "))
            except Exception as e:
                print(f"  ERR {str(e)[:60]}")


if __name__ == "__main__":
    main()

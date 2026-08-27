"""계정별 키워드 알림 등록 — 상한 도달하면 다음 계정으로 넘긴다.

전제: docs/KEYWORD_ALERT_CAPTURE.md 로 등록 엔드포인트가 확정돼 있어야 한다
      (`python3 -m collector.keyword_alert learn`).
입력: data/keywords_screened.json (tools/screen_keywords.py 산출)
      data/accounts.json
산출: data/alert_assignments.json  — 계정 ↔ 키워드 배정표, 계정당 실측 상한

용법:
  python3 tools/setup_keyword_alerts.py --dry-run   # 등록 안 하고 배정만 계산
  python3 tools/setup_keyword_alerts.py             # 실제 등록
  python3 tools/setup_keyword_alerts.py --probe-cap # 1계정으로 상한만 실측
"""
import argparse
import json
import os
import sys

sys.path.insert(0, "collector")
from keyword_alert import (KeywordAlertClient, EndpointUnknown,  # noqa: E402
                           load_spec, save_spec)
from pool import Worker  # noqa: E402

SCREENED = "data/keywords_screened.json"
ACCOUNTS = "data/accounts.json"
OUT = "data/alert_assignments.json"

# 상한 초과로 판정할 응답 신호
CAP_STATUS = {400, 403, 409, 422, 429}
CAP_HINT = ("max", "limit", "exceed", "초과", "최대", "가득", "더 이상")


def is_cap_error(resp):
    if resp.status_code not in CAP_STATUS:
        return False
    text = (resp.text or "").lower()
    return any(h.lower() in text for h in CAP_HINT)


def load_keywords(path):
    data = json.load(open(path, encoding="utf-8"))
    items = data["ok"] if isinstance(data, dict) else data
    return [i["keyword"] if isinstance(i, dict) else i for i in items]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", default=SCREENED)
    ap.add_argument("--accounts", default=ACCOUNTS)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--probe-cap", action="store_true",
                    help="첫 계정에만 계속 등록해 상한을 실측")
    ap.add_argument("--per-account", type=int, default=None,
                    help="계정당 등록 개수 강제(상한 이미 알 때)")
    args = ap.parse_args()

    keywords = load_keywords(args.keywords)
    if not os.path.exists(args.accounts):
        raise SystemExit(f"{args.accounts} 없음 — accounts.example.json 참고")
    specs = json.load(open(args.accounts, encoding="utf-8"))
    spec = load_spec()
    cap = args.per_account or spec.get("max_keywords")

    print(f"키워드 {len(keywords)} · 계정 {len(specs)} · "
          f"계정당 상한 {cap if cap else '미확인(실측)'}")

    if args.dry_run:
        if not cap:
            print("상한 미확인 → --probe-cap 으로 1계정 실측 먼저.")
            need = "?"
        else:
            need = -(-len(keywords) // cap)
        print(f"필요 계정 수: {need}")
        for i, s in enumerate(specs):
            chunk = keywords[i * cap:(i + 1) * cap] if cap else []
            print(f"  {s['name']}: {len(chunk)}개 "
                  f"{chunk[:4]}{'…' if len(chunk) > 4 else ''}")
        return

    assignments, idx = {}, 0
    measured_cap = cap
    for s in specs:
        if idx >= len(keywords):
            break
        worker = Worker(s, use_frida=False)
        client = KeywordAlertClient.from_worker(worker, spec=spec)
        got = []
        try:
            # 이미 등록된 것은 슬롯을 차지하므로 먼저 반영
            try:
                existing = client.list_keywords()
                got.extend(existing)
                print(f"[{s['name']}] 기존 등록 {len(existing)}개")
            except EndpointUnknown:
                pass
            except Exception as e:
                print(f"[{s['name']}] 목록 조회 실패(무시): {str(e)[:80]}")

            while idx < len(keywords):
                if cap and len(got) >= cap and not args.probe_cap:
                    break
                kw = keywords[idx]
                if kw in got:
                    idx += 1
                    continue
                try:
                    r = client.register(kw)
                except EndpointUnknown as e:
                    raise SystemExit(str(e))
                if is_cap_error(r):
                    measured_cap = len(got)
                    print(f"[{s['name']}] 상한 도달 {measured_cap}개 "
                          f"(status {r.status_code}) — 응답: {r.text[:160]}")
                    break
                if r.status_code >= 400:
                    print(f"[{s['name']}] {kw} 등록 실패 {r.status_code}: "
                          f"{r.text[:120]}")
                    idx += 1
                    continue
                got.append(kw)
                idx += 1
                print(f"[{s['name']}] +{kw}  ({len(got)})")
                if args.probe_cap and len(got) >= 500:
                    print("500개까지 상한 없음 — 사실상 무제한으로 간주")
                    measured_cap = None
                    break
        finally:
            client.close()
            worker.close()
        assignments[s["name"]] = got
        if args.probe_cap:
            break

    if measured_cap and not spec.get("max_keywords"):
        spec["max_keywords"] = measured_cap
        save_spec(spec)
        print(f"실측 상한 {measured_cap} → 스펙 저장")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(assignments, f, ensure_ascii=False, indent=1)
    done = sum(len(v) for v in assignments.values())
    print(f"\n등록 {done}/{len(keywords)} → {args.out}")
    if done < len(keywords):
        print(f"미배정 {len(keywords)-done}개 — 계정 추가 필요")


if __name__ == "__main__":
    main()

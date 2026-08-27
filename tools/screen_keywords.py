"""키워드셋을 알림 등록 가능 여부로 선별한다.

확정 엔드포인트(info)만 쓰므로 **지금 바로 실행 가능**하다.
응답의 isBannedKeyword / isNotificationBannedKeyword 로 거른다.
등록 상한이 빡센데 금지 키워드를 등록 시도하면 슬롯만 버린다.

용법:
  python3 tools/screen_keywords.py                       # data/keywords_luxury.json 선별
  python3 tools/screen_keywords.py --limit 20            # 소량 검증
산출: data/keywords_screened.json
"""
import argparse
import json
import os
import sys

sys.path.insert(0, "collector")
from keyword_alert import KeywordAlertClient  # noqa: E402

IN = "data/keywords_luxury.json"
OUT = "data/keywords_screened.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default=IN)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--min-gap", type=float, default=1.5)
    args = ap.parse_args()

    if not os.path.exists(args.src):
        raise SystemExit(f"{args.src} 없음 — 먼저 tools/build_keyword_set.py")
    items = json.load(open(args.src, encoding="utf-8"))
    if args.limit:
        items = items[:args.limit]

    client = KeywordAlertClient(min_gap=args.min_gap)
    ok, banned, already, failed = [], [], [], []
    try:
        for i, it in enumerate(items, 1):
            kw = it["keyword"]
            try:
                d = client.info(kw)
            except Exception as e:
                failed.append({**it, "error": str(e)[:120]})
                print(f"[{i}/{len(items)}] {kw:16s} 실패 {str(e)[:60]}")
                continue
            rec = {**it,
                   "banned": bool(d.get("isBannedKeyword")),
                   "notification_banned": bool(d.get("isNotificationBannedKeyword")),
                   "registered": bool(d.get("isRegistered"))}
            if rec["banned"] or rec["notification_banned"]:
                banned.append(rec)
                mark = "🚫 금지"
            elif rec["registered"]:
                already.append(rec)
                ok.append(rec)
                mark = "· 이미등록"
            else:
                ok.append(rec)
                mark = "✅ 가능"
            print(f"[{i}/{len(items)}] {kw:16s} {mark}")
    finally:
        client.close()

    result = {"ok": ok, "banned": banned, "failed": failed}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f"\n등록가능 {len(ok)} · 이미등록 {len(already)} · "
          f"금지 {len(banned)} · 실패 {len(failed)} → {args.out}")
    if banned:
        print("금지 키워드:", ", ".join(b["keyword"] for b in banned[:20]))


if __name__ == "__main__":
    main()

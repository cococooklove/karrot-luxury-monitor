"""당근 앱 푸시 알림 수신기 — 키워드 알림을 매물 신호로 바꾼다.

푸시는 FCM 채널로 오므로 **mitmproxy 로는 안 잡힌다.** 기기 알림함을 읽는다.
    adb -s <serial> shell dumpsys notification --noredact

에뮬레이터는 토큰 자체갱신 때문에 어차피 상시 구동이므로 추가 비용이 없다.

용법:
  python3 tools/notification_listener.py --account acc1 --once
  python3 tools/notification_listener.py --account acc1            # 상시 폴링
  python3 tools/notification_listener.py --all                     # accounts.json 전체
산출: data/alert_hits.jsonl  (1줄 = 알림 1건)
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

ACCOUNTS = "data/accounts.json"
OUT = "data/alert_hits.jsonl"
SEEN = "data/alert_seen.json"
# 실기기 실측(SM-N950N/Android 9): 실제 패키지는 com.towneers.www.
# kr.co.towneers.www 는 존재하지 않는다 — 이 값으로 두면 조용히 0건이 된다.
PKG = "com.towneers.www"
PKG_ALIASES = ("com.towneers.www", "kr.co.towneers.www")

REC_SPLIT = re.compile(r"NotificationRecord\(")
RE_PKG = re.compile(r"pkg=([\w.]+)")
# 헤더 줄의 key= 뒤에는 appImportanceLocked 가 공백 없이 붙는 ROM 이 있다.
# 독립된 key= 줄을 우선 쓰고, 없을 때만 헤더에서 잘라 쓴다.
RE_KEY_LINE = re.compile(r"^\s*key=(\S+)\s*$", re.M)
RE_KEY = re.compile(r"key=([^\s:]+)")
RE_WHEN = re.compile(r"\bwhen=(\d+)")
# Android 9 삼성 ROM 등 when= 을 안 찍는 경우의 대체 타임스탬프
RE_CREATED = re.compile(r"mCreationTimeMs=(\d+)")
RE_TITLE = re.compile(r"android\.title=String\s*\((.*?)\)\s*$", re.M)
RE_TEXT = re.compile(r"android\.text=String\s*\((.*?)\)\s*$", re.M)
# 알림 본문에 매물 id 가 실려 오면 그대로 쓴다(스킴/딥링크)
RE_ID = re.compile(r"(?:articles?|buy-sell)[/_-]?(?:id=)?(\d{6,})")


def dumpsys(serial):
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += ["shell", "dumpsys", "notification", "--noredact"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
    if r.returncode != 0:
        raise RuntimeError(f"adb 실패: {r.stderr.strip()[:200]}")
    return r.stdout


def parse(dump, pkg=None):
    """dumpsys 출력 → 당근 알림 레코드 목록. pkg 미지정이면 별칭 전부 허용."""
    allowed = (pkg,) if pkg else PKG_ALIASES
    out = []
    for chunk in REC_SPLIT.split(dump)[1:]:
        m = RE_PKG.search(chunk)
        if not m or m.group(1) not in allowed:
            continue
        title = RE_TITLE.search(chunk)
        text = RE_TEXT.search(chunk)
        if not (title or text):
            continue
        key = RE_KEY_LINE.search(chunk) or RE_KEY.search(chunk)
        when = RE_WHEN.search(chunk) or RE_CREATED.search(chunk)
        body = text.group(1).strip() if text else ""
        rec = {
            "key": key.group(1) if key else None,
            "when": int(when.group(1)) if when else None,
            "title": title.group(1).strip() if title else "",
            "text": body,
        }
        aid = RE_ID.search(chunk)
        if aid:
            rec["article_id"] = aid.group(1)
        out.append(rec)
    return out


def fingerprint(rec):
    raw = f"{rec.get('key')}|{rec.get('when')}|{rec['title']}|{rec['text']}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def load_seen(path=SEEN):
    if os.path.exists(path):
        try:
            return set(json.load(open(path, encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_seen(seen, path=SEEN):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f)


def collect(targets, seen, out_path=OUT):
    """계정별 1회 수집. 새 알림 수 반환."""
    new = 0
    for name, serial in targets:
        try:
            dump = dumpsys(serial)
        except Exception as e:
            print(f"[{name}] {e}")
            continue
        for rec in parse(dump):
            fp = fingerprint(rec)
            if fp in seen:
                continue
            seen.add(fp)
            rec.update({"fp": fp, "account": name, "serial": serial,
                        "ts": round(time.time(), 3)})
            with open(out_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            new += 1
            print(f"[{name}] 🔔 {rec['title']} | {rec['text'][:60]}")
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", help="accounts.json 의 name")
    ap.add_argument("--serial", help="adb serial 직접 지정")
    ap.add_argument("--all", action="store_true", help="accounts.json 전체")
    ap.add_argument("--interval", type=float, default=20.0)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    targets = []
    if args.serial:
        targets = [(args.account or args.serial, args.serial)]
    else:
        if not os.path.exists(ACCOUNTS):
            raise SystemExit(f"{ACCOUNTS} 없음 — --serial 로 직접 지정하거나 계정 구성")
        specs = json.load(open(ACCOUNTS, encoding="utf-8"))
        for s in specs:
            if args.all or s["name"] == args.account:
                targets.append((s["name"], s.get("serial")))
    if not targets:
        raise SystemExit("대상 없음 — --account / --serial / --all 중 하나")

    seen = load_seen()
    print(f"수신 대상: {[t[0] for t in targets]} (기존 {len(seen)}건 기억)")
    try:
        while True:
            n = collect(targets, seen)
            if n:
                save_seen(seen)
            if args.once:
                print(f"신규 {n}건 → {OUT}")
                return
            time.sleep(args.interval)
    except KeyboardInterrupt:
        save_seen(seen)
        print("\n중단. 상태 저장됨.")


if __name__ == "__main__":
    main()

"""
캡처 자동 분석 — mine.json 없이도 "차단 트리거 후보"를 한 눈에.

성공(2xx) 요청 헤더를 버킷 분류하고, 요청마다 변하는 값(동적 서명 후보)과
디바이스/무결성/인증 헤더 존재를 리포트. Phase 0 결론 자동화.

용법:
  python tools/analyze_capture.py
"""
import base64
import json
import math
import re
from collections import defaultdict

CAP = "data/capture.jsonl"

DEVICE_KEYS = re.compile(r"(device|udid|uuid|installation|instance|advertis|android[-_]?id)", re.I)
INTEGRITY_KEYS = re.compile(r"(integrity|attest|safetynet|nonce|recaptcha|playintegrity)", re.I)
SIGN_KEYS = re.compile(r"(sign|signature|hmac|hash|mac|digest|checksum)", re.I)
AUTH_KEYS = re.compile(r"(authorization|auth[-_]?token|x[-_]?auth|access[-_]?token|bearer)", re.I)
VERSION_KEYS = re.compile(r"(user-agent|x[-_]?app|version|build|client)", re.I)
IGNORE = {"content-length", "date", "accept-encoding", "connection"}


def load():
    rows = []
    try:
        with open(CAP, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except FileNotFoundError:
        raise SystemExit(
            f"{CAP} 없음. 먼저 캡처하라:\n"
            "  mitmdump -s capture/karrot_dump.py --listen-port 8080\n"
            "  → LD플레이어 프록시+인증서 설정 후 앱으로 매물조회 (SETUP_LDPLAYER.md)")
    return rows


def entropy(s):
    if not s:
        return 0
    freq = defaultdict(int)
    for ch in s:
        freq[ch] += 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def looks_signed(v):
    """고엔트로피 + base64/hex 형태 = 서명값 냄새."""
    v = v.strip()
    if len(v) < 16:
        return False
    b64 = bool(re.fullmatch(r"[A-Za-z0-9+/=_\-]{16,}", v))
    hexlike = bool(re.fullmatch(r"[0-9a-fA-F]{32,}", v))
    return (b64 or hexlike) and entropy(v) > 3.5


def main():
    rows = load()
    ok = [r for r in rows if r["status"] and 200 <= r["status"] < 300]
    blocked = [r for r in rows if r["status"] in (401, 403, 429)]
    print(f"총 {len(rows)}건 / 성공 {len(ok)} / 차단 {len(blocked)}\n")

    if blocked:
        print("[차단된 path]")
        seen = set()
        for r in blocked:
            if r["path"] not in seen:
                print(f"  {r['status']} {r['method']} {r['path']}")
                seen.add(r["path"])
        print()

    if not ok:
        print("성공 요청 없음 — 앱 조회가 캡처됐는지, pinning 우회됐는지 확인.")
        return

    # path별 성공요청 헤더 분석
    by_path = defaultdict(list)
    for r in ok:
        by_path[r["path"]].append(r)

    for path, reqs in by_path.items():
        print(f"=== {path}  (성공 {len(reqs)}건) ===")
        # 버킷: 마지막 요청 헤더 기준
        h = {k.lower(): v for k, v in reqs[-1]["req_headers"].items()}
        buckets = defaultdict(list)
        for k, v in h.items():
            if k in IGNORE:
                continue
            if AUTH_KEYS.search(k):
                buckets["인증"].append(k)
            elif DEVICE_KEYS.search(k):
                buckets["디바이스"].append(k)
            elif INTEGRITY_KEYS.search(k):
                buckets["무결성"].append(k)
            elif SIGN_KEYS.search(k) or looks_signed(v):
                buckets["서명추정"].append(k)
            elif VERSION_KEYS.search(k):
                buckets["앱버전/UA"].append(k)
        for name in ("인증", "디바이스", "무결성", "서명추정", "앱버전/UA"):
            if buckets[name]:
                print(f"  [{name}] {', '.join(sorted(set(buckets[name])))}")

        # 가변성 (동적 서명 판정) — 2건 이상일 때
        if len(reqs) >= 2:
            vals = defaultdict(set)
            for r in reqs:
                for k, v in r["req_headers"].items():
                    kl = k.lower()
                    if kl not in IGNORE:
                        vals[kl].add(v)
            volatile = [k for k, s in vals.items() if len(s) > 1]
            if volatile:
                print(f"  [매번 변함 → 동적서명 의심] {', '.join(sorted(volatile))}")
        else:
            print("  (같은 조회 2회+ 캡처하면 동적서명 판정 가능)")
        print()

    print("→ 내 프로그램에 '디바이스/서명추정/무결성/앱버전' 헤더가 빠졌으면 그게 차단 원인.")
    print("→ '매번 변함' 헤더 있으면 정적 복제 불가 → Frida sign_hook 필요.")


if __name__ == "__main__":
    main()

"""
code:z 토큰(HS256) 발급/refresh 서버 특정 — 광역 URL/IP/경로 스캔.

1차 스캔은 karrot/daangn 호스트만 봐서 커스텀 서버를 놓쳤다.
이번엔 디스크의 모든 URL·IP:port·API경로를 뽑되 구글/안드로이드 노이즈만 제외.
이미 추출된 /tmp/ldbk_disk/*.vmdk 재사용. strings 1회 캐시 후 다중 grep.

용법:  .venv/bin/python tools/scan_token_endpoint.py
"""
import os
import re
import subprocess

DISKS = ["/tmp/ldbk_disk/data.vmdk", "/tmp/ldbk_disk/sdcard.vmdk"]
CACHE = "/tmp/ldbk_strings.txt"

# 노이즈 호스트 (플랫폼/구글/표준)
NOISE = re.compile(
    r"(google|gstatic|googleapis|ggpht|gvt1|android\.com|schemas\.android|"
    r"firebase|crashlytics|w3\.org|apache\.org|mozilla|bumptech|squareup|"
    r"jetbrains|kotlinlang|gradle|githubusercontent/.*android|ns\.adobe)",
    re.I,
)


def build_cache():
    if os.path.exists(CACHE) and os.path.getsize(CACHE) > 0:
        print(f"[cache] 재사용 {CACHE} ({os.path.getsize(CACHE)/1e6:.0f}MB)")
        return
    with open(CACHE, "wb") as out:
        for d in DISKS:
            if not os.path.exists(d):
                print(f"[skip] {d} 없음")
                continue
            print(f"[strings] {d} …")
            subprocess.run(["strings", "-n", "6", d], stdout=out)
    print(f"[cache] 생성 {os.path.getsize(CACHE)/1e6:.0f}MB")


def grep(pat, flags="-aoE"):
    r = subprocess.run(["grep", flags, pat, CACHE],
                       capture_output=True, text=True)
    return sorted(set(l for l in r.stdout.splitlines() if l.strip()))


def show(title, hits, limit, denoise=False):
    if denoise:
        hits = [h for h in hits if not NOISE.search(h)]
    print(f"\n===== {title} ({len(hits)} 유니크) =====")
    for h in hits[:limit]:
        print(f"   {h[:180]}")


def main():
    build_cache()

    # 1) 모든 URL (노이즈 제외) — 커스텀 서버 후보
    urls = grep(r"https?://[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]{6,}")
    show("모든 URL (구글/안드 제외)", urls, 80, denoise=True)

    # 2) IP:port — 커스텀 서버가 IP 직결일 경우
    ips = grep(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}:[0-9]{2,5}\b")
    show("IP:port", ips, 60)

    # 3) API 경로 (호스트 없이 저장된 경우) — token/refresh/auth/login
    paths = grep(r'/(?:api|token|refresh|auth|login|oauth|user|session|verify|code)'
                 r'[A-Za-z0-9/_.-]{0,60}')
    show("API 경로 (token/auth/refresh/login/...)", paths, 80, denoise=True)

    # 4) code 토큰 저장 컨텍스트 — 토큰 담은 xml/json 라인
    ctx = grep(r'[^\n]{0,60}"?(?:code|type)"?\s*[:=]\s*"?(?:z|access|refresh)"?[^\n]{0,60}')
    show("code/type 토큰 컨텍스트", ctx, 40)

    # 5) 도메인만 (호스트 리스트업)
    hosts = grep(r'\b[a-z0-9][a-z0-9.-]{3,}\.(?:com|net|io|kr|co|app|dev|xyz|cn|shop)\b')
    show("호스트 도메인 (구글/안드 제외)", hosts, 100, denoise=True)


if __name__ == "__main__":
    main()

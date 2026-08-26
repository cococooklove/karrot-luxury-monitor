"""
당근 실제 API 엔드포인트 정밀 추출 — 캐시된 strings 재사용(빠름).

1차 광역스캔은 protobuf 타입명/통신사MMS 노이즈에 묻혔다.
이번엔 karrotmarket 호스트의 full path 와 인증/매물 관련 경로만 콕 집는다.
목표: (1) 인증 검색 엔드포인트 (2) 토큰 refresh/verify 엔드포인트.

용법:  .venv/bin/python tools/scan_karrot_api.py
"""
import re
import subprocess

CACHE = "/tmp/ldbk_strings.txt"


def grep(pat):
    r = subprocess.run(["grep", "-aoE", pat, CACHE], capture_output=True, text=True)
    return sorted(set(l for l in r.stdout.splitlines() if l.strip()))


def show(title, hits, limit=60):
    print(f"\n===== {title} ({len(hits)}) =====")
    for h in hits[:limit]:
        print(f"   {h[:200]}")


def main():
    # 1) karrotmarket 호스트 full URL (경로 포함)
    show("karrotmarket URL (full path)",
         grep(r"https?://[a-z0-9.-]*karrotmarket\.com/[A-Za-z0-9/_.:?=&%-]{2,80}"))

    # 2) towneers/daangn 호스트 full URL
    show("towneers/daangn URL",
         grep(r"https?://[a-z0-9.-]*(?:towneers|daangn)[a-z0-9.-]*\.[a-z]{2,}/"
              r"[A-Za-z0-9/_.:?=&%-]{2,80}"))

    # 3) 매물/피드/검색 관련 경로 (HTTP path, protobuf . 제외)
    show("매물/검색 경로 (/fleamarket /article /search /feed)",
         grep(r"/(?:fleamarket|flea-market|article|articles|search|feed|filter|"
              r"buy-sell)[a-z0-9/_-]{0,50}"))

    # 4) 인증/토큰 경로 (슬래시 경로만, . 타입명 제외)
    show("인증/토큰 경로 (/user /auth /oauth /token /verification /session)",
         grep(r"/(?:user|auth|oauth|token|verifications?|session|login|refresh)"
              r"/[a-z0-9/_-]{2,50}"))

    # 5) Authorization 헤더 형태 흔적
    show("Authorization/헤더 키 흔적",
         grep(r"(?:[Aa]uthorization|x-[a-z-]*token|x-auth[a-z-]*|bearer)"
              r"[\":= ]{0,3}[A-Za-z0-9 ._-]{0,20}"))


if __name__ == "__main__":
    main()

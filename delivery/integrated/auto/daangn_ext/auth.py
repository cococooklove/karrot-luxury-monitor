"""
토큰 주입 어댑터 — 검색 요청에 access 토큰을 실어주는 지점.

당근 요청에 토큰이 실제로 어떻게 들어가는지(헤더명/prefix/대상 호스트)는
캡처로 확정 후 아래 CONFIG 만 바꾸면 됨. 코드 수정 불필요.

두 시나리오 지원:
  - 인증 API(api.kr.karrotmarket.com) 로 전환: TARGET_HOSTS 에 해당 호스트, HEADER=authorization
  - 기존 웹 SSR 유지 + 토큰 실험: 그대로 두고 host 만 추가

주의: 토큰이 그 요청을 실제로 인증하는지는 응답으로 검증(build_headers 는 무해).
"""
from __future__ import annotations

from urllib.parse import urlparse

# ── 캡처 후 확정할 값 ──
HEADER_NAME = "authorization"     # 토큰 헤더 키
HEADER_PREFIX = "Bearer "         # 값 접두 ("" 가능)
# 토큰을 실을 호스트(부분일치). 비우면 모든 요청에 실음.
TARGET_HOSTS: tuple[str, ...] = ("karrotmarket.com",)
# 쿠키로 실어야 하면 여기에 쿠키명 (헤더 대신). 예 "_karrot_session"
COOKIE_NAME: str | None = None


def _host_match(url: str) -> bool:
    if not TARGET_HOSTS:
        return True
    host = (urlparse(url).hostname or "").lower()
    return any(h in host for h in TARGET_HOSTS)


def build_headers(url: str, access_token: str | None,
                  base: dict | None = None) -> dict:
    """대상 호스트면 토큰 헤더를 병합해 반환. 아니면 base 그대로."""
    headers = dict(base or {})
    if access_token and _host_match(url):
        if COOKIE_NAME:
            cookie = headers.get("cookie", "")
            sep = "; " if cookie else ""
            headers["cookie"] = f"{cookie}{sep}{COOKIE_NAME}={access_token}"
        else:
            headers[HEADER_NAME] = f"{HEADER_PREFIX}{access_token}"
    return headers

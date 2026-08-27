"""
파일 기반 토큰 소스 — 온디바이스(에뮬/폰) 수확 루프가 갱신한 accounts.json 에서
가장 신선한 access 를 읽어 제공한다.

무인 구조에서 refresh(교환)는 앱이 하고(WAF/피닝 자체처리), Mac/PC 파이썬은
회전된 결과만 accounts.json 에서 읽는다. 그래서 여기엔 네트워크 갱신이 없다.
token_manager._default_refresh 는 WAF 403 으로 죽으므로 이 경로가 대체한다.

용법:
    provider = access_provider("data/accounts.json", code="530029...")
    access = provider()          # 최신 access 문자열 (없으면 "")

KarrotClient(token_provider=provider) 로 주입하면 매 요청 authorization 이 갱신된다.
"""
import json
import os
import time

from token_manager import token_exp, token_code


def _load_rows(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def freshest(path, code=None):
    """accounts.json 에서 (code, access, expires_in) 반환.

    code 지정 시 그 계정만. 미지정 시 남은 수명이 가장 긴 계정을 고른다.
    후보가 전부 만료됐어도 가장 덜 만료된 access 를 돌려준다(수확 루프가 곧 갱신).
    유효 access 가 하나도 없으면 (code, "", 0).
    """
    rows = _load_rows(path)
    now = int(time.time())
    best = None  # (expires_in, code, access)
    for r in rows:
        acc = r.get("access") or ""
        if not acc:
            continue
        c = r.get("code") or token_code(acc) or ""
        if code is not None and c != code:
            continue
        exp_in = token_exp(acc) - now
        if best is None or exp_in > best[0]:
            best = (exp_in, c, acc)
    if best is None:
        return (code or "", "", 0)
    return (best[1], best[2], best[0])


class _Provider:
    """mtime 캐시로 파일 재파싱을 줄이는 access 제공자(호출 가능)."""

    def __init__(self, path, code=None):
        self.path = path
        self.code = code
        self._mtime = None
        self._cache = ("", "", 0)  # (code, access, expires_in)

    def _refresh_cache(self):
        try:
            m = os.path.getmtime(self.path)
        except OSError:
            m = None
        if m != self._mtime:
            self._mtime = m
            self._cache = freshest(self.path, self.code)
        return self._cache

    def info(self):
        """(code, access, expires_in) — 로깅용."""
        return self._refresh_cache()

    def __call__(self):
        return self._refresh_cache()[1]


def access_provider(path="data/accounts.json", code=None):
    """KarrotClient(token_provider=...) 에 넣을 호출가능 provider 를 만든다."""
    return _Provider(path, code)

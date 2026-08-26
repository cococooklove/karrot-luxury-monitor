"""
토큰 매니저 — "검색 전 토큰 갱신 후 시작" 기능의 심장.

클라 요구:
  - access 토큰 30분 만료 → 검색 중 만료로 데이터 누락 방지
  - 계정+프록시 직접 추가
실측(정지 계정 .ldbk):
  - access:  HS256 {iat,exp,code,type:"access"}   exp-iat=1800s(30분)
  - refresh: HS256 {iat,exp,code,type:"refresh"}  exp-iat=21600s(6시간)
  - 계정 식별 = payload["code"] (예 "z")

동작:
  ensure(account) → access 만료 임박(<skew)이면 refresh 로 재발급 후 유효 토큰 반환.
  검색 워커가 요청 직전 호출 → 항상 살아있는 토큰 사용. 스레드세이프(계정별 락).

REFRESH_URL 은 발급 서버 확정 후 채운다(scan_token_endpoint 결과). 그전엔 refresh_fn 주입 가능.
manual(curl_cffi)·auto(aiohttp) 양쪽에서 import 해 쓰는 공용 모듈.
"""
from __future__ import annotations

import base64
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

# 발급/refresh 서버 — scan 결과로 확정 후 기입
REFRESH_URL = ""            # 예: "https://<vendor-host>/auth/refresh"
REFRESH_SKEW_SEC = 90       # 만료 이 초 전이면 미리 갱신 (검색 중 만료 방지)


def _jwt_payload(token: str) -> dict:
    """JWT 페이로드 디코드(검증 없음, 만료시각 확인용)."""
    try:
        p = token.split(".")[1]
        p += "=" * (-len(p) % 4)                      # base64url 패딩 복구
        return json.loads(base64.urlsafe_b64decode(p))
    except Exception:
        return {}


def token_exp(token: str) -> int:
    return int(_jwt_payload(token).get("exp", 0))


def token_code(token: str) -> str | None:
    return _jwt_payload(token).get("code")


@dataclass
class Account:
    code: str                         # payload.code (계정 식별)
    access: str = ""
    refresh: str = ""
    proxy: str | None = None
    label: str = ""                   # UI 표시용(전화/별칭)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def expires_in(self) -> int:
        return max(0, token_exp(self.access) - int(time.time()))


# refresh 구현: (account) -> (new_access, new_refresh|None). 서버별로 교체.
RefreshFn = Callable[["Account"], "tuple[str, str | None]"]


def _default_refresh(acc: Account) -> tuple[str, str | None]:
    """REFRESH_URL 로 refresh 토큰 제출 → 새 access(+refresh) 수신.
    발급서버 스펙 확정 후 body/헤더/응답키만 맞추면 됨."""
    if not REFRESH_URL:
        raise RuntimeError("REFRESH_URL 미설정 — scan_token_endpoint 결과로 채워라")
    from curl_cffi import requests                    # manual 스택과 동일
    r = requests.post(
        REFRESH_URL,
        json={"refresh_token": acc.refresh, "code": acc.code},
        headers={"authorization": f"Bearer {acc.refresh}"},
        impersonate="chrome",
        proxy=acc.proxy,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    # 응답 키는 서버 확정 후 조정 (access_token/accessToken/token 등)
    new_access = data.get("access_token") or data.get("accessToken") or data.get("access")
    new_refresh = data.get("refresh_token") or data.get("refreshToken")
    if not new_access:
        raise RuntimeError(f"refresh 응답에 access 없음: {list(data)}")
    return new_access, new_refresh


class TokenManager:
    def __init__(self, refresh_fn: RefreshFn | None = None, skew: int = REFRESH_SKEW_SEC):
        self.accounts: dict[str, Account] = {}
        self.refresh_fn = refresh_fn or _default_refresh
        self.skew = skew
        self._reg_lock = threading.Lock()

    # ── 계정 관리 (UI "계정+프록시 추가") ──
    def add(self, refresh: str, access: str = "", proxy: str | None = None,
            label: str = "") -> Account:
        code = token_code(refresh) or token_code(access) or refresh[:8]
        acc = Account(code=code, access=access, refresh=refresh, proxy=proxy, label=label)
        with self._reg_lock:
            self.accounts[code] = acc
        return acc

    def add_many(self, rows: list[dict]) -> None:
        """rows: [{"refresh":..,"access":..,"proxy":..,"label":..}, ...]"""
        for r in rows:
            self.add(r.get("refresh", ""), r.get("access", ""),
                     r.get("proxy"), r.get("label", ""))

    def remove(self, code: str) -> None:
        with self._reg_lock:
            self.accounts.pop(code, None)

    # ── 핵심: 검색 전 갱신 ──
    def ensure(self, acc: Account) -> str:
        """만료 임박이면 갱신 후 유효 access 반환. 계정별 직렬화."""
        with acc._lock:
            if acc.access and acc.expires_in() > self.skew:
                return acc.access
            new_access, new_refresh = self.refresh_fn(acc)
            acc.access = new_access
            if new_refresh:
                acc.refresh = new_refresh
            return acc.access

    def ensure_by_code(self, code: str) -> str:
        return self.ensure(self.accounts[code])

    def refresh_all(self) -> dict[str, str]:
        """일괄 사전갱신(검색 배치 시작 전 호출). {code: 상태}."""
        out = {}
        for code, acc in list(self.accounts.items()):
            try:
                self.ensure(acc)
                out[code] = f"ok (+{acc.expires_in()}s)"
            except Exception as e:
                out[code] = f"fail: {e}"
        return out

    def status(self) -> list[dict]:
        return [{"code": a.code, "label": a.label, "proxy": a.proxy,
                 "expires_in": a.expires_in()} for a in self.accounts.values()]


if __name__ == "__main__":
    # 스모크: 실측 토큰 형식으로 exp/code 디코드 검증 (네트워크 없음)
    sample_access = ("eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9."
                     "eyJpYXQiOjE3ODc0MDUwOTksImV4cCI6MTc4NzQwNjg5OSwiY29kZSI6InoiLCJ0eXBlIjoiYWNjZXNzIn0."
                     "sig")
    print("code =", token_code(sample_access))
    print("exp  =", token_exp(sample_access))
    p = _jwt_payload(sample_access)
    print("ttl  =", p.get("exp", 0) - p.get("iat", 0), "초 (1800=30분 기대)")

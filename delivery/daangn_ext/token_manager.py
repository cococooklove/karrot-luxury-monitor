"""
토큰 매니저 — "검색 전 토큰 갱신 후 시작"의 심장.

실측(정지 계정 .ldbk data.vmdk):
  access:  HS256 {iat,exp,code,type:"access"}   exp-iat=1800s(30분)
  refresh: HS256 {iat,exp,code,type:"refresh"}  exp-iat=21600s(6시간)
  계정 식별 = payload["code"]  (LD 복원시 넣은 "코드: z" 와 동일)

ensure(account) → access 만료 임박(<skew)이면 refresh 로 재발급 후 유효 토큰 반환.
검색 워커가 요청 직전 호출 → 검색 중 만료로 인한 데이터 누락 방지. 계정별 직렬화.

REFRESH_URL·요청형식은 발급서버 확정 후 _default_refresh 만 맞추면 됨.
"""
from __future__ import annotations

import base64
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

REFRESH_URL = ""            # 발급/refresh 서버 (캡처로 확정 후 기입)
REFRESH_SKEW_SEC = 90       # 만료 이 초 전 미리 갱신


def _jwt_payload(token: str) -> dict:
    try:
        p = token.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p))
    except Exception:
        return {}


def token_exp(token: str) -> int:
    return int(_jwt_payload(token).get("exp", 0))


def token_code(token: str) -> str | None:
    return _jwt_payload(token).get("code")


@dataclass
class Account:
    code: str
    access: str = ""
    refresh: str = ""
    proxy: str | None = None
    label: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def expires_in(self) -> int:
        return max(0, token_exp(self.access) - int(time.time()))


RefreshFn = Callable[["Account"], "tuple[str, str | None]"]


def _default_refresh(acc: Account) -> tuple[str, str | None]:
    if not REFRESH_URL:
        raise RuntimeError("REFRESH_URL 미설정 — 발급서버 확정 후 기입")
    from curl_cffi import requests
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

    def add(self, refresh: str, access: str = "", proxy: str | None = None,
            label: str = "") -> Account:
        code = token_code(refresh) or token_code(access) or (refresh or access)[:8]
        acc = Account(code=code, access=access, refresh=refresh, proxy=proxy, label=label)
        with self._reg_lock:
            self.accounts[code] = acc
        return acc

    def add_many(self, rows: list[dict]) -> None:
        for r in rows:
            self.add(r.get("refresh", ""), r.get("access", ""),
                     r.get("proxy"), r.get("label", ""))

    def remove(self, code: str) -> None:
        with self._reg_lock:
            self.accounts.pop(code, None)

    def ensure(self, acc: Account) -> str:
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

    def ensure_safe(self, acc: Account) -> str | None:
        """갱신 실패(엔드포인트 미설정·서버 오류)여도 크래시 없이:
        아직 살아있는 access 있으면 그걸, 없으면 None(익명 진행) 반환.
        → REFRESH_URL 미확정 상태에서도 수집기는 그대로 동작."""
        try:
            return self.ensure(acc)
        except Exception:
            return acc.access or None

    def refresh_all(self) -> dict[str, str]:
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

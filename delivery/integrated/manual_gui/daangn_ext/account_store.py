"""
계정+프록시 저장/관리 — 클라 요구 "계정+프록시 직접 추가 기능".

1계정 : 1프록시 : 1토큰 페어를 파일로 관리. UI 에서 add/remove 호출.
TokenManager 와 결합해 검색 전 자동 갱신.

파일: accounts.json (브랜드 폴더마다 독립 — 기존 폴더별 설정 방식과 동일)
  [{"code":"z","refresh":"<jwt>","access":"<jwt>","proxy":"http://user:pass@host:port","label":"010-xxxx"}]
"""
from __future__ import annotations

import json
import os
import threading

DEFAULT_PATH = "accounts.json"


class AccountStore:
    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path
        self._lock = threading.Lock()
        self.rows: list[dict] = []
        self.load()

    def load(self) -> None:
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.rows = json.load(f)
        else:
            self.rows = []

    def save(self) -> None:
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.rows, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)

    # ── UI 연동 ──
    def add(self, refresh: str, proxy: str | None = None,
            access: str = "", label: str = "") -> dict:
        row = {"refresh": refresh, "access": access, "proxy": proxy, "label": label}
        with self._lock:
            # 중복(같은 refresh) 갱신
            self.rows = [r for r in self.rows if r.get("refresh") != refresh]
            self.rows.append(row)
        self.save()
        return row

    def add_pair(self, refresh: str, proxy: str, label: str = "") -> dict:
        """계정+프록시 한 쌍 추가 (1:1 페어링)."""
        return self.add(refresh=refresh, proxy=proxy, label=label)

    def remove(self, refresh_or_label: str) -> None:
        with self._lock:
            self.rows = [r for r in self.rows
                         if r.get("refresh") != refresh_or_label
                         and r.get("label") != refresh_or_label]
        self.save()

    def proxies(self) -> list[str]:
        return [r["proxy"] for r in self.rows if r.get("proxy")]

    def __len__(self) -> int:
        return len(self.rows)


def bind_to_token_manager(store: AccountStore, tm) -> None:
    """저장된 계정 전량을 TokenManager 에 등록 (검색 전 갱신 대상)."""
    tm.add_many(store.rows)

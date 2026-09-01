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

    def set_proxy(self, key: str, proxy: str | None) -> bool:
        """이 계정에 프록시를 지정한다. 성공하면 True.

        `key` 는 code / label / refresh 중 아무거나 — 화면에 보이는 것이 code 라
        그걸로도 찾을 수 있어야 한다.

        **파일 전체를 덮어쓰지 않고, 락을 잡고 다시 읽어서 그 줄만 고친다.**
        accounts.json 은 이 기계에서 재발급할 수 없는 세션 토큰의 유일한 사본이고,
        수확기가 같은 파일을 병합하며 쓴다. 여기서 메모리에 들고 있던 옛 내용을
        통째로 쓰면 그 사이 수확된 토큰이 사라진다 — 복구 경로는 폰 앱 스택뿐이다.
        그래서 수확기와 **같은** 프로세스 간 파일락(ld_autoharvest)을 탄다.

        락 모듈을 못 불러오면(다른 배포 형태) 락 없이 진행한다. 프록시 하나를
        못 바꾸는 것보다 낫고, 최악이 lost update 로 되돌아갈 뿐이다.
        """
        key = str(key or "").strip()
        if not key:
            return False
        proxy = (proxy or "").strip() or None
        try:
            from ld_autoharvest import _file_lock
        except Exception:
            import contextlib

            @contextlib.contextmanager
            def _file_lock(_fp, log=None):
                yield False

        with self._lock:
            with _file_lock(self.path):
                try:
                    with open(self.path, encoding="utf-8") as f:
                        rows = json.load(f)
                except FileNotFoundError:
                    rows = []
                except Exception:
                    return False
                hit = None
                for r in rows:
                    if key in (str(r.get("code") or ""), str(r.get("label") or ""),
                               str(r.get("refresh") or "")):
                        hit = r
                        break
                if hit is None:
                    return False
                if proxy:
                    hit["proxy"] = proxy
                else:
                    hit.pop("proxy", None)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(rows, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
                self.rows = rows
        return True

    def proxies(self) -> list[str]:
        return [r["proxy"] for r in self.rows if r.get("proxy")]

    def __len__(self) -> int:
        return len(self.rows)


def bind_to_token_manager(store: AccountStore, tm) -> None:
    """저장된 계정 전량을 TokenManager 에 등록 (검색 전 갱신 대상)."""
    tm.add_many(store.rows)

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

ROLE_ALERT = "alert"      # 앱 알림 받기·브랜드 등록·수확. 검색 API 호출 없음
ROLE_SWEEP = "sweep"      # 앱 키워드 스윕(검색) 전용 — 버려도 되는 계정
ROLES = (ROLE_ALERT, ROLE_SWEEP)


def account_role(row: dict) -> str:
    """역할 필드. 없거나 모르는 값이면 alert — 기존 계정이 전부 알림 계정이 된다."""
    r = str((row or {}).get("role") or "").strip().lower()
    return r if r in ROLES else ROLE_ALERT


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
            access: str = "", label: str = "", role: str = ROLE_ALERT) -> dict:
        row = {"refresh": refresh, "access": access, "proxy": proxy, "label": label,
               "role": role}
        with self._lock:
            # 중복(같은 refresh) 갱신
            self.rows = [r for r in self.rows if r.get("refresh") != refresh]
            self.rows.append(row)
        self.save()
        return row

    def add_pair(self, refresh: str, proxy: str, label: str = "") -> dict:
        """계정+프록시 한 쌍 추가 (1:1 페어링)."""
        return self.add(refresh=refresh, proxy=proxy, label=label)

    def remove(self, key: str) -> bool:
        """계정 한 줄을 지운다. 지웠으면 True.

        `key` 는 code / label / refresh 중 아무거나 — 화면 목록에 보이는 것이
        code 다. 종전에는 refresh/label 만 봐서, 수확으로 들어온 계정(label 이
        비고 code 만 있다)은 화면에서 골라도 지워지지 않았다.

        **set_proxy 와 같은 이유로 파일락을 잡고 다시 읽어서 그 줄만 뺀다.**
        종전에는 메모리 사본을 통째로 덮어써서, 그 사이 수확기가 넣은 토큰이
        옛 값으로 되돌아가거나 새로 들어온 계정이 통째로 사라졌다. refresh
        토큰은 이 기계에서 재발급할 수 없다 — 당근 WAF 가 PC 갱신을 막아
        복구 경로는 폰 앱 스택이나 `.ldbk` 복원뿐이다.

        지운 줄은 `accounts.json.deleted` 에 쌓아 둔다. 되돌릴 길이 하나도
        없는 것과, 파일에서 도로 옮겨 붙이면 되는 것은 사고의 무게가 다르다.
        """
        key = str(key or "").strip()
        if not key:
            return False
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
                    return False
                except Exception:
                    return False
                keep, gone = [], []
                for r in rows:
                    if key in (str(r.get("code") or ""), str(r.get("label") or ""),
                               str(r.get("refresh") or "")):
                        gone.append(r)
                    else:
                        keep.append(r)
                if not gone:
                    return False
                self._bury(gone)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(keep, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
                self.rows = keep
        return True

    def _bury(self, gone: list[dict]) -> None:
        """지운 계정을 무덤 파일에 쌓는다. 실패해도 삭제 자체는 진행한다 —
        무덤을 못 쓴다고 사용자가 시킨 삭제를 막을 이유는 없다."""
        path = self.path + ".deleted"
        try:
            try:
                with open(path, encoding="utf-8") as f:
                    old = json.load(f)
                if not isinstance(old, list):
                    old = []
            except Exception:
                old = []
            with open(path, "w", encoding="utf-8") as f:
                json.dump(old + list(gone), f, ensure_ascii=False, indent=2)
        except Exception:
            pass

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

    def set_role(self, key, role: str) -> bool:
        """이 계정의 역할(alert/sweep)을 지정한다. 성공하면 True.

        `key` 는 code / label / refresh 중 아무거나 — set_proxy 와 같은 방식.

        **set_proxy 와 같은 이유로 파일락을 잡고 다시 읽어서 그 줄만 고친다.**
        수확기가 같은 파일에 새 계정·갱신 토큰을 병합해 쓴다 — 메모리 사본을
        통째로 덮어쓰면 그 사이 들어온 계정/토큰이 사라진다.
        """
        if role not in ROLES:
            return False
        key = str(key or "").strip()
        if not key:
            return False
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
                hit["role"] = role
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

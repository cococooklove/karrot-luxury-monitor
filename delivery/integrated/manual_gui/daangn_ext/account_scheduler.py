"""계정 안정화 스케줄러 — 밴회피 계정레벨 게이팅 (자동 모니터에 주입).

문제: 기존 자동검색은 freshest 1계정 + 프록시풀 로테이션 → 한 계정이 여러 IP로 검색
      = 핑거프린트 이상. 계정레벨 밴회피(일일캡/워밍업/분산) 없음.
해결: 사이클마다 계정을 라운드로빈으로 골라, 그 계정의 고정 프록시(없으면 네이티브)로만 검색.
      daily_cap 으로 계정별 일일 요청 상한, warmup_days 로 신/휴면 계정 점진 증량.

상태(일일 카운트·최초관측일)는 accounts.json 옆 account_state.json 에 보존.
"""
from __future__ import annotations

import json
import os
import time

STATE_FILE = "./account_state.json"


def _today():
    return time.strftime("%Y-%m-%d")


class AccountScheduler:
    def __init__(self, accounts_fp="./accounts.json", state_fp=STATE_FILE,
                 daily_cap=300, warmup_days=3, cooldown_sec=1800, log=None):
        self.accounts_fp = accounts_fp
        self.state_fp = state_fp
        self.daily_cap = int(daily_cap)
        self.warmup_days = max(1, int(warmup_days))
        self.cooldown_sec = cooldown_sec
        self.log = log or (lambda m: None)
        self._rr = 0
        self.state = self._load_state()

    # ── 계정 로드 (accounts.json: code, access, proxy) ──
    def _accounts(self):
        try:
            rows = json.load(open(self.accounts_fp, encoding="utf-8"))
        except Exception:
            return []
        out = []
        for r in rows:
            acc = r.get("access") or ""
            if not acc:
                continue
            out.append({"code": str(r.get("code") or ""),
                        "access": acc, "proxy": r.get("proxy") or None})
        return out

    def _load_state(self):
        try:
            return json.load(open(self.state_fp, encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self):
        try:
            tmp = self.state_fp + ".tmp"
            json.dump(self.state, open(tmp, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
            os.replace(tmp, self.state_fp)
        except Exception:
            pass

    def _st(self, code):
        s = self.state.get(code)
        if not s:
            s = {"first_seen": _today(), "date": _today(), "count": 0, "cooldown_until": 0}
            self.state[code] = s
        if s.get("date") != _today():        # 날짜 바뀌면 일일카운트 리셋
            s["date"] = _today(); s["count"] = 0
        return s

    def _warmup_cap(self, code):
        """최초관측 후 경과일에 비례해 상한을 선형 증량(신계정 급증 방지)."""
        s = self._st(code)
        try:
            d0 = time.mktime(time.strptime(s["first_seen"], "%Y-%m-%d"))
            days = int((time.time() - d0) // 86400) + 1
        except Exception:
            days = self.warmup_days
        frac = min(1.0, days / self.warmup_days)
        return max(10, int(self.daily_cap * frac))

    # ── 다음 사용할 계정 선택 (라운드로빈 + 캡/워밍업/쿨다운 통과) ──
    def pick(self):
        accs = self._accounts()
        if not accs:
            return None
        n = len(accs)
        now = time.time()
        for i in range(n):
            a = accs[(self._rr + i) % n]
            s = self._st(a["code"])
            if s.get("cooldown_until", 0) > now:
                continue
            if s["count"] >= self._warmup_cap(a["code"]):
                continue
            self._rr = (self._rr + i + 1) % n
            return {"code": a["code"], "access": a["access"], "proxy": a["proxy"],
                    "remaining": self._warmup_cap(a["code"]) - s["count"]}
        self.log("[스케줄러] 사용가능 계정 없음 (전부 캡도달/쿨다운) — 다음 리셋/사이클 대기")
        return None

    def note(self, code, requests=1):
        s = self._st(code)
        s["count"] += max(1, int(requests))
        self._save_state()

    def note_block(self, code):
        s = self._st(code)
        s["cooldown_until"] = time.time() + self.cooldown_sec
        self._save_state()
        self.log(f"[스케줄러] {code} 차단신호 → {self.cooldown_sec//60}분 격리")

    def status(self):
        out = []
        for a in self._accounts():
            s = self._st(a["code"])
            out.append(f"{a['code'][:6]}:{s['count']}/{self._warmup_cap(a['code'])}")
        return " ".join(out)

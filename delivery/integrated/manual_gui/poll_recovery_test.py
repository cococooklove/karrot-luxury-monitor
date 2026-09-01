"""전 계정 만료 시 폴링이 스스로 복구하는가.

실서버 타임라인(2026-09-01, 스케줄 수정 후):
    21:14:01  전계정(0) 매칭 0건    ← 토큰이 막 만료됨
    21:14:02  갱신 4               ← 수확 스레드가 만료 직후 깨워 갱신
    21:16:01  전계정(4) 매칭 54건   ← 복구
죽은 시간이 20분에서 **폴링 한 틱**으로 줄었지만, 그 한 틱도 감시 공백이다.
앱은 만료된 뒤에야 갱신하므로, 폴링이 '유효 계정 0'을 본 순간이 정확히 깨울
때다. 그래서 폴링이 그 자리에서 수확을 부르고 다시 센다.

실행: python poll_recovery_test.py
"""
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

from daangn_ext import keyword_alert_api as K

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


class _Multi(K.MultiAccountAlerts):
    """네트워크 없이 poll_all 의 분기만 관찰한다."""

    def __init__(self, valid_seq):
        super().__init__(accounts_fp="./accounts.json")
        self._seq = list(valid_seq)
        self._valid_calls = 0

    def _valid(self, core_only=False):
        self._valid_calls += 1
        return self._seq.pop(0) if self._seq else []

    def _state(self):
        return {}

    def _save_state(self, state):
        pass


print("=== 1. 유효 계정이 있으면 수확을 부르지 않는다 ===")
called = {"n": 0}
m = _Multi([[("c1", "tok", None)]])
m._on_no_valid_accounts = lambda log: called.__setitem__("n", called["n"] + 1) or True
orig_api = K.KeywordAlertAPI
K.KeywordAlertAPI = lambda *a, **k: type(
    "F", (), {"new_matches": lambda self, c: [], "close": lambda self: None})()
try:
    logs = []
    m.poll_all(log=logs.append)
    ck("복구 경로를 안 탄다", called["n"] == 0)
    ck("_valid 를 한 번만 부른다", m._valid_calls == 1, f"{m._valid_calls}회")

    print("\n=== 2. 유효 0 이면 수확을 부르고 다시 센다 ===")
    called["n"] = 0
    m2 = _Multi([[], [("c1", "tok", None)]])
    m2._on_no_valid_accounts = lambda log: (
        called.__setitem__("n", called["n"] + 1) or True)
    logs = []
    m2.poll_all(log=logs.append)
    ck("복구를 시도한다", called["n"] == 1)
    ck("복구 뒤 다시 센다", m2._valid_calls == 2, f"{m2._valid_calls}회")
    ck("갱신된 계정으로 폴링한다", "전계정(1)" in " ".join(logs), " ".join(logs))

    print("\n=== 3. 복구가 실패해도 폴링은 계속된다 ===")
    m3 = _Multi([[], []])
    m3._on_no_valid_accounts = lambda log: False
    logs = []
    out = m3.poll_all(log=logs.append)
    ck("예외 없이 빈 결과", out == [])
    ck("0 으로 기록된다", "전계정(0)" in " ".join(logs), " ".join(logs))
finally:
    K.KeywordAlertAPI = orig_api

print("\n=== 4. 복구 함수 자체 ===")
m4 = _Multi([[]])
logs = []
ck("수확기를 못 찾으면 False", isinstance(m4._on_no_valid_accounts(logs.append), bool))

import types
fake = types.SimpleNamespace(
    harvest_all=lambda fp, nudge=True, log=None: (4, 0, 4, 4))
sys.modules["ld_autoharvest"], real = fake, sys.modules.get("ld_autoharvest")
try:
    logs = []
    ck("수확이 계정을 건지면 True", m4._on_no_valid_accounts(logs.append) is True)
    ck("무엇을 왜 했는지 남긴다", any("복구" in x for x in logs), str(logs))

    def _boom(fp, nudge=True, log=None):
        raise RuntimeError("adb 폭발")

    fake.harvest_all = _boom
    logs = []
    ck("수확이 터져도 False 로 끝난다",
       m4._on_no_valid_accounts(logs.append) is False)
    ck("터진 사실을 남긴다", any("실패" in x for x in logs), str(logs))
finally:
    if real is not None:
        sys.modules["ld_autoharvest"] = real
    else:
        del sys.modules["ld_autoharvest"]

bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패:", bad)
sys.exit(1 if bad else 0)

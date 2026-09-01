"""게스트 프록시가 수확 흐름에 실제로 물려 있는가.

모듈만 있고 아무도 안 부르면 계정은 계속 미국 IP 로 붙는다. 그리고 순서가
중요하다 — 프록시를 **먼저** 걸어야 이어지는 앱 콜드스타트(nudge)가 그 프록시로
나간다. 반대면 갱신 한 번을 직결로 흘린다.

실행: python guest_proxy_wire_test.py
"""
import os
import sys
import tempfile

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


src = open("main.py", encoding="utf-8").read()

print("=== 1. 두 런타임 모두 수확 전에 부른다 ===")
ck("GUI 수확 스레드가 부른다", "guest_proxy_sync(self.accounts" in src)
ck("헤드리스가 부른다", 'guest_proxy_sync("./accounts.json"' in src)

gui = src.index("guest_proxy_sync(self.accounts")
gui_harvest = src.index("ld_autoharvest.harvest_all(\n                    self.accounts")
ck("GUI: 프록시 → 수확 순서", gui < gui_harvest,
   "먼저 걸어야 콜드스타트가 프록시로 나간다")

hl = src.index('guest_proxy_sync("./accounts.json"')
hl_harvest = src.index('ld_autoharvest.harvest_all(\n                        "./accounts.json"')
ck("헤드리스: 프록시 → 수확 순서", hl < hl_harvest)

print("\n=== 2. 릴레이는 루프백에만 연다 ===")
# 인증 없는 릴레이를 공개 IP 서버에 0.0.0.0 으로 열면 오픈 프록시가 된다.
ck("bind 가 127.0.0.1", 'ProxyRelay(bind="127.0.0.1"' in src)
ck("0.0.0.0 으로 안 연다", 'ProxyRelay(bind="0.0.0.0"' not in src)

print("\n=== 3. 자격증명이 있을 때만 릴레이를 띄운다 ===")
ck("자격증명 유무로 가른다", 'if "@" in px' in src or '"@" not in px' in src)

print("\n=== 4. 함수 자체 동작 (모듈 스텁) ===")
ns = {}
start = src.index("_GUEST_RELAY = None")
end = src.index("def mirror_app_keywords_to_sweep(")
exec(src[start:end], ns)
sync = ns["guest_proxy_sync"]

import types

tmp = tempfile.mkdtemp()
ACC = os.path.join(tmp, "accounts.json")
import json

calls = {}


class _FakeRelay:
    def __init__(self, bind="127.0.0.1", log=None):
        calls["bind"] = bind
        self.keys = []

    def start(self):
        calls["started"] = True
        return self

    def add(self, key, url):
        self.keys.append(key)
        return True

    def endpoint(self, key):
        return "127.0.0.1:19999" if key in self.keys else None


fake_ldp = types.SimpleNamespace(
    _account_proxies=lambda fp: json.load(open(fp, encoding="utf-8")),
    apply_account_proxies=lambda fp, log=None, endpoint_for=None: {
        1: endpoint_for("http://u:p@1.1.1.1:8000") if endpoint_for else None,
        2: endpoint_for("http://2.2.2.2:9000") if endpoint_for else None,
    })
sys.modules["ld_proxy"] = fake_ldp
sys.modules["daangn_ext.proxy_relay"] = types.SimpleNamespace(ProxyRelay=_FakeRelay)

json.dump({"a": "http://u:p@1.1.1.1:8000", "b": "http://2.2.2.2:9000"},
          open(ACC, "w", encoding="utf-8"))
logs = []
out = sync(ACC, log=logs.append)
ck("자격증명 있는 것은 릴레이 주소", out.get(1) == "127.0.0.1:19999", str(out))
ck("자격증명 없는 것은 그대로", out.get(2) == "2.2.2.2:9000", str(out))
ck("릴레이를 루프백으로 띄웠다", calls.get("bind") == "127.0.0.1" and calls.get("started"))

print("\n=== 5. 자격증명이 없으면 릴레이를 안 띄운다 ===")
ns["_GUEST_RELAY"] = None
calls.clear()
json.dump({"b": "http://2.2.2.2:9000"}, open(ACC, "w", encoding="utf-8"))
sync(ACC, log=None)
ck("릴레이 미기동", "started" not in calls, str(calls))

print("\n=== 6. 터져도 수확을 막지 않는다 ===")
def _boom(fp, log=None, endpoint_for=None):
    raise RuntimeError("adb 폭발")


fake_ldp.apply_account_proxies = _boom
logs = []
ck("빈 결과로 끝난다", sync(ACC, log=logs.append) == {})
ck("사유를 남긴다", any("실패" in m for m in logs), str(logs))

sys.modules.pop("ld_proxy", None)
sys.modules.pop("daangn_ext.proxy_relay", None)

bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패:", bad)
sys.exit(1 if bad else 0)

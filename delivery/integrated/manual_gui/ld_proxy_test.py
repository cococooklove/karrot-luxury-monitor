"""게스트 앱 트래픽을 계정별 프록시로 내보내는 계약.

토큰을 만드는 건 게스트 안의 당근 앱이고, 그 앱이 접속하는 곳이 곧 그 계정이
로그인한 곳이다. 서버가 미국 IP 라 검색만 KR 프록시로 돌려도 계정은 미국에서
붙는다 — 계정 위험의 근원이 거기다.

실측(2026-09-01): 당근 앱은 안드로이드 전역 프록시를 존중한다. 로깅 프록시를
걸었더니 api.kr.karrotmarket.com(토큰 갱신) 이 그리로 지나갔다.

여기서는 ldconsole 을 가짜로 갈아끼워 **명령의 모양과 판단**만 고정한다.
실기기·실프록시는 서버에서 따로 확인한다.

실행: python ld_proxy_test.py
"""
import base64
import json
import os
import sys
import tempfile

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

import ld_proxy as LP

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


calls = []
state = {}          # index -> 현재 전역 프록시


def fake_adb(console, index, cmd, timeout=LP.CMD_TIMEOUT):
    calls.append((index, cmd))
    if "settings get global http_proxy" in cmd:
        return True, (state.get(index) or "null") + "\n"
    if "settings put global http_proxy" in cmd:
        val = cmd.rsplit(" ", 1)[-1]
        state[index] = None if val == LP.NONE_PROXY else val
        return True, ""
    if "ip route show table all" in cmd:
        return True, ("172.16.1.0/24 dev wlan0 proto kernel scope link\n"
                      "default via 172.16.1.2 dev wlan0 table wlan0\n")
    if "karrot_token.ds" in cmd:
        tok = TOKENS.get(index)
        return (True, tok + "\n") if tok else (True, "")
    return False, ""


def _ds(code):
    """code 를 sub 로 갖는 최소 토큰 파일(base64)."""
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": code}).encode()).decode().rstrip("=")
    jwt = f"aaa.{payload}.bbb"
    body = b"\x0a" + bytes([len(jwt)]) + jwt.encode()      # field1(refresh)
    return base64.b64encode(body).decode()


TOKENS = {1: _ds("452902"), 2: _ds("463777"), 3: None}

LP._adb = fake_adb
LP.find_ldconsole = lambda *a, **k: "ldconsole.exe"
LP.fleet_indexes = lambda app_dir=".", log=None: [1, 2, 3]

tmp = tempfile.mkdtemp()
ACC = os.path.join(tmp, "accounts.json")


def write_accounts(rows):
    json.dump(rows, open(ACC, "w", encoding="utf-8"), ensure_ascii=False)


print("=== 1. 게스트에게 호스트 주소를 물어본다(상수로 안 박는다) ===")
ck("기본 게이트웨이를 읽는다", LP.host_addr_for("c", 1) == "172.16.1.2")

print("\n=== 2. 인덱스 → 계정 code (토큰으로 잇는다) ===")
ck("index 1", LP.index_code("c", 1) == "452902", LP.index_code("c", 1))
ck("index 2", LP.index_code("c", 2) == "463777")
ck("로그아웃 인스턴스는 None", LP.index_code("c", 3) is None)

print("\n=== 3. 설정은 쓰고 나서 다시 읽어 확인한다 ===")
state.clear()
ck("설정 성공", LP.set_guest_proxy("c", 1, "127.0.0.1:9001") is True)
ck("읽어보면 그 값", LP.get_guest_proxy("c", 1) == "127.0.0.1:9001")
ck("해제하면 None", LP.set_guest_proxy("c", 1, None) and
   LP.get_guest_proxy("c", 1) is None)
ck("해제는 :0 으로 쓴다", any(c.endswith(LP.NONE_PROXY) for _i, c in calls
                            if "put global" in c))

# put 이 먹지 않는 판을 흉내낸다 — 종료코드는 0인데 값이 안 바뀐다
orig = LP._adb


def stubborn(console, index, cmd, timeout=LP.CMD_TIMEOUT):
    if "put global" in cmd:
        return True, ""            # 성공이라고 답하지만 값은 안 바뀜
    return orig(console, index, cmd, timeout)


LP._adb = stubborn
state[5] = None
logs = []
ck("안 먹은 설정을 성공으로 보고하지 않는다",
   LP.set_guest_proxy("c", 5, "1.2.3.4:8080", log=logs.append) is False)
ck("왜 실패했는지 남긴다", any("반영 안 됨" in m for m in logs), str(logs))
LP._adb = fake_adb

print("\n=== 4. 계정 프록시를 그 계정이 있는 인스턴스에 건다 ===")
state.clear(); calls.clear()
write_accounts([
    {"code": "452902", "proxy": "http://1.1.1.1:8000"},
    {"code": "463777", "proxy": "http://2.2.2.2:9000"},
])
logs = []
res = LP.apply_account_proxies(ACC, console="c", log=logs.append)
ck("index 1 에 그 계정 프록시", res.get(1) == "1.1.1.1:8000", str(res))
ck("index 2 에 그 계정 프록시", res.get(2) == "2.2.2.2:9000")
ck("로그아웃 인스턴스는 건너뛴다", res.get(3) is None)
ck("건너뛴 이유를 남긴다", any("로그인된 계정이 없어" in m for m in logs))

print("\n=== 5. 같은 값이면 adb 를 더 쓰지 않는다 ===")
calls.clear()
LP.apply_account_proxies(ACC, console="c", log=None)
puts = [c for _i, c in calls if "put global" in c]
ck("put 을 다시 보내지 않는다", puts == [], str(puts))

print("\n=== 6. 프록시를 떼면 게스트도 직결로 되돌린다 ===")
write_accounts([{"code": "452902"}, {"code": "463777", "proxy": "http://2.2.2.2:9000"}])
logs = []
res = LP.apply_account_proxies(ACC, console="c", log=logs.append)
ck("index 1 해제됨", LP.get_guest_proxy("c", 1) is None and res.get(1) is None)
ck("index 2 는 그대로", LP.get_guest_proxy("c", 2) == "2.2.2.2:9000")
ck("해제를 로그로 남긴다", any("해제" in m for m in logs), str(logs))

print("\n=== 7. 자격증명이 있는 프록시는 릴레이 없이 안 건다 ===")
state.clear()
write_accounts([{"code": "452902", "proxy": "http://u:p@3.3.3.3:7000"}])
logs = []
res = LP.apply_account_proxies(ACC, console="c", log=logs.append)
ck("안 건다", res.get(1) is None and LP.get_guest_proxy("c", 1) is None)
ck("이유를 남긴다", any("릴레이 없이는" in m for m in logs), str(logs))

print("\n=== 8. 릴레이가 있으면 그 주소를 건다 ===")
state.clear()
res = LP.apply_account_proxies(ACC, console="c",
                               endpoint_for=lambda px: "127.0.0.1:19001",
                               log=None)
ck("릴레이 주소로 걸린다", res.get(1) == "127.0.0.1:19001",
   LP.get_guest_proxy("c", 1))

print("\n=== 9. 없는/깨진 accounts.json 에도 안 죽는다 ===")
logs = []
r9 = LP.apply_account_proxies(os.path.join(tmp, "없는파일.json"), console="c",
                              log=logs.append)
ck("빈 결과가 아니라 인덱스별 None", set(r9) == {1, 2, 3}, str(r9))
ck("프록시 없음을 알린다", any("지정된 프록시가 없습니다" in m for m in logs))

bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패:", bad)
sys.exit(1 if bad else 0)

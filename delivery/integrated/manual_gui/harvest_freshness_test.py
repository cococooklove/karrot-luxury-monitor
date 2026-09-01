"""수확 주기와 신선도 임계의 불변식 검증 — 토큰이 틱 사이에 죽지 않는가.

실서버에서 4계정 토큰이 만료된 채 방치된 사고의 원인을 고정한다.
access 토큰 TTL 은 1800초(JWT exp-iat 실측)인데, 수확 틱은 1200초 간격이고
신선도 임계는 600초였다. 임계가 틱 간격보다 작으면 이런 구간이 생긴다:

    틱 N   : 잔여 601초 → 임계(600) 초과라 nudge 안 함
    +1200초
    틱 N+1 : 잔여 -599초 → 이미 죽은 지 10분

즉 임계 < 틱 간격이면 만료는 우연이 아니라 **필연**이다. 불변식은
`임계 > 틱 간격 + nudge 소요` 이고, 동시에 `임계 < TTL` 이어야 매 틱마다
헛되이 함대를 깨우지 않는다. 이 파일은 그 두 부등식을 코드 상수로 고정한다.

실행: python harvest_freshness_test.py
"""
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

import ld_autoharvest as LA

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


print("=== 1. 상수 불변식 ===")
ck("HARVEST_INTERVAL 존재", hasattr(LA, "HARVEST_INTERVAL"),
   getattr(LA, "HARVEST_INTERVAL", "-"))
ck("ACCESS_TTL 존재", hasattr(LA, "ACCESS_TTL"), getattr(LA, "ACCESS_TTL", "-"))
ck("MIN_REMAINING 존재", hasattr(LA, "MIN_REMAINING"),
   getattr(LA, "MIN_REMAINING", "-"))

iv = getattr(LA, "HARVEST_INTERVAL", 0)
ttl = getattr(LA, "ACCESS_TTL", 0)
mr = getattr(LA, "MIN_REMAINING", 0)

ck("임계 > 틱 간격 (틱 사이 만료 불가)", mr > iv, f"{mr} > {iv}")
ck("임계 < TTL (매 틱 무조건 nudge 는 아님)", mr < ttl, f"{mr} < {ttl}")
ck("여유가 nudge 최대 소요(24초) 이상", mr - iv >= 24, f"여유 {mr - iv}초")

print("\n=== 2. harvest_one 기본 임계가 상수를 따른다 ===")
import inspect
sig = inspect.signature(LA.harvest_one)
ck("harvest_one(min_remaining) 기본값 = MIN_REMAINING",
   sig.parameters["min_remaining"].default == mr,
   f"{sig.parameters['min_remaining'].default}")

sig_all = inspect.signature(LA.harvest_all)
ck("harvest_all 이 min_remaining 을 받는다", "min_remaining" in sig_all.parameters)
if "min_remaining" in sig_all.parameters:
    ck("harvest_all(min_remaining) 기본값 = MIN_REMAINING",
       sig_all.parameters["min_remaining"].default == mr,
       f"{sig_all.parameters['min_remaining'].default}")

print("\n=== 3. 임계 미만이면 nudge 한다 / 초과면 안 한다 (스텁) ===")
calls = {"force_stop": 0, "reads": 0}
FRESH = "fresh-token"
STALE = "stale-token"


def make_stub(remaining_before, remaining_after):
    """_read_parse 와 _adb 를 갈아끼워 nudge 여부만 관찰한다."""
    state = {"nudged": False}

    def _read_parse(adb_bin, serial):
        calls["reads"] += 1
        return {"code": "c", "refresh": "r",
                "access": FRESH if state["nudged"] else STALE}

    def _access_remaining(tok):
        return remaining_after if tok == FRESH else remaining_before

    def _adb(adb_bin, serial, *args, **kw):
        if "force-stop" in args:
            calls["force_stop"] += 1
            state["nudged"] = True
        return ""

    return _read_parse, _access_remaining, _adb


orig = (LA._read_parse, LA._access_remaining, LA._adb, LA.time.sleep)
try:
    LA.time.sleep = lambda *_a, **_k: None

    # (a) 임계보다 넉넉히 남았으면 함대를 깨우지 않는다
    calls["force_stop"] = 0
    LA._read_parse, LA._access_remaining, LA._adb = make_stub(mr + 1, mr + 1)
    LA.harvest_one("adb", "emulator-5554")
    ck("잔여 > 임계 → nudge 안 함", calls["force_stop"] == 0,
       f"force-stop {calls['force_stop']}회")

    # (b) 임계 아래면 깨운다
    calls["force_stop"] = 0
    LA._read_parse, LA._access_remaining, LA._adb = make_stub(mr - 1, LA.ACCESS_TTL)
    got = LA.harvest_one("adb", "emulator-5554")
    ck("잔여 < 임계 → nudge 함", calls["force_stop"] == 1,
       f"force-stop {calls['force_stop']}회")
    ck("nudge 후 새 토큰을 돌려준다", (got or {}).get("access") == FRESH)

    # (c) 사고 재현: 옛 임계(600)였다면 이 잔여는 그냥 넘어간다
    calls["force_stop"] = 0
    LA._read_parse, LA._access_remaining, LA._adb = make_stub(601, LA.ACCESS_TTL)
    LA.harvest_one("adb", "emulator-5554", min_remaining=600)
    skipped_at_601 = calls["force_stop"] == 0
    calls["force_stop"] = 0
    LA._read_parse, LA._access_remaining, LA._adb = make_stub(601, LA.ACCESS_TTL)
    LA.harvest_one("adb", "emulator-5554")
    ck("잔여 601초: 옛 임계는 건너뛰고 새 임계는 갱신한다",
       skipped_at_601 and calls["force_stop"] == 1,
       f"옛 skip={skipped_at_601}, 새 nudge={calls['force_stop']}")
finally:
    LA._read_parse, LA._access_remaining, LA._adb, LA.time.sleep = orig

print("\n=== 3b. 느린 틱에서도 임계가 따라 올라간다 ===")
# 한 틱은 '간격 + 수확 시간'이다. 수확은 ensure_ldplayer(최대 FLEET_BOOT_BUDGET)를
# 포함하므로 인스턴스가 hang 하면 틱이 1200초가 아니라 1400초가 된다. 임계를
# 1320 으로 고정해 두면 1321초 남은 토큰을 건너뛰고 다음 틱엔 죽어 있다.
slow = LA.HARVEST_INTERVAL + LA.FLEET_BOOT_BUDGET / 3      # 1400초
ck("임계가 실제 주기를 따라간다", LA.min_remaining_for(slow) > slow,
   f"period {slow:.0f} → 임계 {LA.min_remaining_for(slow)}")
ck("느린 틱 임계가 고정 임계보다 크다", LA.min_remaining_for(slow) > mr,
   f"{LA.min_remaining_for(slow)} > {mr}")
ck("임계는 TTL 을 넘지 않는다",
   LA.min_remaining_for(LA.ACCESS_TTL * 3) < LA.ACCESS_TTL,
   f"{LA.min_remaining_for(LA.ACCESS_TTL * 3)} < {LA.ACCESS_TTL}")
ck("막을 수 없는 주기는 안전하지 않다고 답한다",
   not LA.period_is_safe(LA.ACCESS_TTL) and LA.period_is_safe(LA.HARVEST_INTERVAL))

# 사고 재현: 1400초 주기 + 1321초 남은 토큰
calls["force_stop"] = 0
orig2 = (LA._read_parse, LA._access_remaining, LA._adb, LA.time.sleep)
try:
    LA.time.sleep = lambda *_a, **_k: None
    LA._read_parse, LA._access_remaining, LA._adb = make_stub(mr + 1, LA.ACCESS_TTL)
    LA.harvest_one("adb", "e", min_remaining=LA.min_remaining_for(slow))
    ck("느린 틱이면 1321초 남은 토큰도 갱신한다", calls["force_stop"] == 1,
       f"force-stop {calls['force_stop']}회")
finally:
    LA._read_parse, LA._access_remaining, LA._adb, LA.time.sleep = orig2

print("\n=== 4. main.py 가 주기를 따로 적어 두지 않는다 ===")
# 이 사고의 실제 원인은 로직이 아니라 '같은 숫자가 두 파일에 따로 적혀 있던 것'
# 이었다. 그래서 소스 수준에서 막는다 — 런타임 테스트로는 못 잡는 종류다.
src = open("main.py", encoding="utf-8").read()
ck("GUI 수확 스레드가 리터럴 주기를 안 쓴다", "_HarvestThread(interval=1200" not in src)
ck("헤드리스 루프가 리터럴 주기를 안 쓴다", "last_harvest > 1200" not in src)
ck("main.py 가 harvest_interval() 을 쓴다", src.count("harvest_interval()") >= 3,
   f"{src.count('harvest_interval()')}곳")
# 두 런타임 모두 '측정한 주기'로 임계를 정해야 한다. 고정 임계로 돌아가면
# 느린 틱에서 토큰이 다시 죽는다.
ck("GUI·헤드리스가 min_remaining_for 로 임계를 낸다",
   src.count("min_remaining_for(") >= 2, f"{src.count('min_remaining_for(')}곳")
ck("두 런타임이 위험한 주기를 경고한다",
   src.count("period_is_safe(") >= 2, f"{src.count('period_is_safe(')}곳")
ck("GUI 가 수확에 쓴 시간만큼 잠을 줄인다", "self.interval - spent" in src)

bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패:", bad)
sys.exit(1 if bad else 0)

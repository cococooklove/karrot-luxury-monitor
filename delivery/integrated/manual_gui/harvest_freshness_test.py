"""토큰이 만료된 채 방치되지 않는가 — 수확 스케줄 계약.

실서버 4계정이 만료된 채 방치돼 폴링이 "전계정(0)" 으로 헛돈 사고에서 나왔다.
처음에는 "신선도 임계가 수확 간격보다 작아서"라고 보고 임계를 올렸는데, 그건
**틀린 처방이었다**. 실측 로그가 전제를 반증했다:

    20:07:44  갱신 4   ← 만료된 상태에서 nudge → 갱신됨
    20:12:51  갱신 0   ← 잔여 ~1500초에 nudge → 앱이 갱신 안 함
    20:32:51  갱신 0   ← 잔여 ~300초에 nudge → 그래도 안 함
    20:37     만료 → 폴링 "전계정(0)"
    20:45     만료 후 nudge → 갱신 4

**당근 앱은 만료 전에 토큰을 갱신하지 않는다.** 그러니 미리 깨우는 임계를 아무리
올려도 소용없고(앱이 거절), 남는 문제는 "만료된 채 방치되는 시간"뿐이다. 그래서
정책이 바뀌었다 — 고정 주기가 아니라 **가장 먼저 죽는 토큰의 만료 시각에서
역산한 스케줄**이다.

실행: python harvest_freshness_test.py
"""
import inspect
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

import ld_autoharvest as LA

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


print("=== 1. 정책 상수 ===")
ck("ACCESS_TTL 은 실측 1800초", LA.ACCESS_TTL == 1800, str(LA.ACCESS_TTL))
ck("NUDGE_BELOW 는 만료 직전만 노린다", 0 < LA.NUDGE_BELOW <= 60,
   f"{LA.NUDGE_BELOW}초")
ck("심장박동 주기가 TTL 보다 훨씬 짧다", LA.HARVEST_INTERVAL < LA.ACCESS_TTL / 4,
   f"{LA.HARVEST_INTERVAL} < {LA.ACCESS_TTL / 4:.0f}")
ck("최소 수면이 nudge 소요보다 길다", LA.HARVEST_MIN_SLEEP >= LA.NUDGE_WORST,
   f"{LA.HARVEST_MIN_SLEEP} >= {LA.NUDGE_WORST}")

print("\n=== 2. 만료 시각에서 역산한다 ===")
ck("많이 남으면 심장박동까지만 잔다",
   LA.next_harvest_delay(1500) == LA.HARVEST_INTERVAL,
   f"{LA.next_harvest_delay(1500)}초")
ck("곧 만료면 그 직후에 깨어난다",
   LA.next_harvest_delay(120) == 121, f"{LA.next_harvest_delay(120)}초")
ck("이미 만료면 바로 다시 간다",
   LA.next_harvest_delay(-100) == LA.HARVEST_MIN_SLEEP,
   f"{LA.next_harvest_delay(-100)}초")
ck("잔여를 모르면 심장박동", LA.next_harvest_delay(None) == LA.HARVEST_INTERVAL)
ck("망가진 값에도 안 죽는다", LA.next_harvest_delay("몰라") == LA.HARVEST_INTERVAL)
ck("호출자가 상한을 낮출 수 있다",
   LA.next_harvest_delay(9999, ceil=90) == 90)

# 이 사고의 핵심: 고정 1200초 틱이면 최악 얼마나 죽어 있었나 vs 지금은?
old_dead = 1200
new_dead = LA.next_harvest_delay(-1) + LA.NUDGE_WORST
ck("만료 방치 시간이 한 자릿수 분으로 줄었다", new_dead < old_dead / 10,
   f"{old_dead}초 → 최악 {new_dead}초")

print("\n=== 3. 수확 함수 계약 ===")
sig = inspect.signature(LA.harvest_one)
ck("harvest_one 기본 임계 = NUDGE_BELOW",
   sig.parameters["min_remaining"].default == LA.NUDGE_BELOW)
sig_all = inspect.signature(LA.harvest_all)
ck("harvest_all 기본 임계 = NUDGE_BELOW",
   sig_all.parameters["min_remaining"].default == LA.NUDGE_BELOW)
ck("harvest_all 이 stats 를 돌려줄 수 있다", "stats" in sig_all.parameters,
   "다음 수확 시각을 정하려면 최소 잔여가 필요하다")

print("\n=== 4. 임계 위/아래에서 nudge 여부 (스텁) ===")
calls = {"force_stop": 0}
FRESH, STALE = "fresh-token", "stale-token"


def make_stub(before, after):
    st = {"nudged": False}

    def _read_parse(adb_bin, serial):
        return {"code": "c", "refresh": "r",
                "access": FRESH if st["nudged"] else STALE}

    def _access_remaining(tok):
        return after if tok == FRESH else before

    def _adb(adb_bin, serial, *args, **kw):
        if "force-stop" in args:
            calls["force_stop"] += 1
            st["nudged"] = True
        return ""

    return _read_parse, _access_remaining, _adb


orig = (LA._read_parse, LA._access_remaining, LA._adb, LA.time.sleep)
try:
    LA.time.sleep = lambda *_a, **_k: None

    calls["force_stop"] = 0
    LA._read_parse, LA._access_remaining, LA._adb = make_stub(LA.NUDGE_BELOW + 1,
                                                             LA.ACCESS_TTL)
    LA.harvest_one("adb", "emulator-5554")
    ck("아직 안 죽었으면 안 깨운다", calls["force_stop"] == 0,
       "앱이 어차피 갱신을 거절한다 — 깨우면 콜드스타트만 낭비")

    calls["force_stop"] = 0
    LA._read_parse, LA._access_remaining, LA._adb = make_stub(-5, LA.ACCESS_TTL)
    got = LA.harvest_one("adb", "emulator-5554")
    ck("만료됐으면 깨운다", calls["force_stop"] == 1)
    ck("깨운 뒤 새 토큰을 돌려준다", (got or {}).get("access") == FRESH)
finally:
    LA._read_parse, LA._access_remaining, LA._adb, LA.time.sleep = orig

print("\n=== 5. 두 런타임이 같은 규칙을 쓴다 ===")
# 같은 숫자를 두 파일에 따로 적어 두던 것이 원래 사고의 원인이었다.
src = open("main.py", encoding="utf-8").read()
ck("GUI 수확 스레드가 리터럴 주기를 안 쓴다", "_HarvestThread(interval=1200" not in src)
ck("헤드리스가 리터럴 주기를 안 쓴다", "last_harvest > 1200" not in src)
ck("두 런타임 모두 next_harvest_delay 로 다음 시각을 정한다",
   src.count("next_harvest_delay(") >= 2, f"{src.count('next_harvest_delay(')}곳")
ck("두 런타임 모두 stats 로 최소 잔여를 받는다",
   src.count("stats=hstats") >= 2, f"{src.count('stats=hstats')}곳")
ck("옛 모델(고정 임계 계산)이 남아 있지 않다",
   "min_remaining_for(" not in src and "period_is_safe(" not in src)

bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패:", bad)
sys.exit(1 if bad else 0)

"""계정 추가 계약 — .ldbk 복원이 밟는 함정들을 고정한다.

손으로 하다가 다 밟은 것들이라 절차를 코드 한 곳에 모았다. 여기서 지키는 것:
  · 복원이 leidian<N>.config 를 초기화한다 → 미리 백업하고, 작아지면 경고
  · 그 config 를 JSON 으로 읽었다 쓰면 LDPlayer 가 기본값으로 리셋한다 → 텍스트 치환
  · adbDebug=0 백업이 있다 → VM 은 뜨는데 adb 에 안 잡혀 토큰 수확이 영영 안 됨
  · data/fleet.json 에 인덱스를 안 넣으면 새 인스턴스가 조용히 감시에서 빠진다

실행: python ld_instance_test.py
"""
import json
import os
import sys
import tempfile

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

import ld_instance as LI

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


tmp = tempfile.mkdtemp()
VMS = os.path.join(tmp, "LDPlayer9", "vms")
os.makedirs(VMS, exist_ok=True)
CONSOLE = os.path.join(tmp, "LDPlayer9", "ldconsole.exe")
open(CONSOLE, "w").close()

FULL = ('{"propertySettings.phoneIMEI":"86',) # 자리만 채우는 더미
CONFIG_OK = '{"basicSettings.adbDebug":1,' + "x" * 2000 + "}"
CONFIG_OFF = '{"basicSettings.adbDebug":0,' + "x" * 2000 + "}"
CONFIG_TINY = '{"propertySettings.phoneIMEI":"860000"}'


def write_cfg(idx, body):
    p = os.path.join(VMS, f"leidian{idx}.config")
    open(p, "w", encoding="utf-8").write(body)
    return p


print("=== 1. ADB 가 꺼진 백업을 켜 준다 (텍스트 치환) ===")
p = write_cfg(7, CONFIG_OFF)
logs = []
changed, warn = LI.ensure_adb_debug(CONSOLE, 7, logs.append)
body = open(p, encoding="utf-8").read()
ck("adbDebug 가 1 이 된다", '"basicSettings.adbDebug":1' in body)
ck("고쳤다고 보고", changed is True)
ck("백업(.bak)을 남긴다", any(f.startswith("leidian7.config.bak") for f in os.listdir(VMS)))
ck("나머지 내용을 보존한다", len(body) > 2000, f"{len(body)}바이트")
ck("파일을 JSON 으로 다시 쓰지 않는다(원문 유지)", body.startswith("{\"basicSettings"))

print("\n=== 2. 이미 켜져 있으면 건드리지 않는다 ===")
write_cfg(8, CONFIG_OK)
before = open(os.path.join(VMS, "leidian8.config"), encoding="utf-8").read()
changed, warn = LI.ensure_adb_debug(CONSOLE, 8, lambda m: None)
ck("안 고침", changed is False)
ck("내용 그대로", open(os.path.join(VMS, "leidian8.config"), encoding="utf-8").read() == before)

print("\n=== 3. 초기화된 config 를 경고한다 ===")
write_cfg(9, CONFIG_TINY)
changed, warn = LI.ensure_adb_debug(CONSOLE, 9, lambda m: None)
ck("경고가 나온다", bool(warn), str(warn)[:60])
ck("adbDebug 없음을 짚는다", "adbDebug" in (warn or ""))

print("\n=== 4. config 가 아직 없어도 죽지 않는다 ===")
changed, warn = LI.ensure_adb_debug(CONSOLE, 99, lambda m: None)
ck("경고만 하고 넘어간다", changed is False and bool(warn))

print("\n=== 5. 감시 대상(fleet.json)에 넣는다 ===")
app = os.path.join(tmp, "app")
os.makedirs(os.path.join(app, "data"), exist_ok=True)
fleet = os.path.join(app, "data", "fleet.json")
json.dump({"indexes": [1, 2, 3]}, open(fleet, "w", encoding="utf-8"))
vals = LI.add_to_fleet(app, 7, lambda m: None)
ck("인덱스가 들어간다", vals == [1, 2, 3, 7], str(vals))
ck("디스크에도 반영", json.load(open(fleet, encoding="utf-8"))["indexes"] == [1, 2, 3, 7])
ck("백업을 남긴다", any(f.startswith("fleet.json.bak")
                     for f in os.listdir(os.path.join(app, "data"))))
ck("중복은 그대로", LI.add_to_fleet(app, 7, lambda m: None) == [1, 2, 3, 7])

print("\n=== 6. fleet.json 이 없으면 만들지 않는다 ===")
# 없으면 '전체 대상' 이라는 뜻이다. 여기서 만들면 갑자기 범위가 좁아진다.
app2 = os.path.join(tmp, "app2")
os.makedirs(app2, exist_ok=True)
logs = []
ck("None 반환", LI.add_to_fleet(app2, 5, logs.append) is None)
ck("파일을 만들지 않는다", not os.path.exists(os.path.join(app2, "data", "fleet.json")))
ck("이유를 남긴다", any("전체 인스턴스가 대상" in m for m in logs), str(logs))

print("\n=== 7. 입력이 틀리면 만들기 전에 멈춘다 ===")
for bad, why in ((("없는파일.ldbk", "이름"), "파일 없음"),
                 ((__file__, "  "), "이름 없음")):
    try:
        LI.add_from_ldbk(bad[0], bad[1], app_dir=app, console=CONSOLE,
                         log=lambda m: None)
        ck(f"{why} 은 거부", False)
    except LI.AddError as e:
        ck(f"{why} 은 거부", True, str(e)[:50])

print("\n=== 8. 새 인덱스를 못 가리면 진행하지 않는다 ===")
# 이름이 겹쳐 인스턴스가 안 생겼는데도 복원을 밀어붙이면 남의 인스턴스를 덮어쓴다.
LI._run = lambda args, timeout=120: (0, "", "")
LI.ld_rows = lambda console: [{"index": "1"}, {"index": "2"}]
ok = False
try:
    LI.add_from_ldbk(__file__, "이름", app_dir=app, console=CONSOLE, log=lambda m: None)
except LI.AddError as e:
    ok = "특정하지 못했" in str(e)
ck("복원까지 가지 않는다", ok)

print("\n=== 9. 정상 흐름 ===")
seq = {"n": 0}


def fake_rows(console):
    seq["n"] += 1
    return ([{"index": "1"}] if seq["n"] == 1 else [{"index": "1"}, {"index": "4"}])


LI.ld_rows = fake_rows
LI.time.sleep = lambda *_a: None
write_cfg(4, CONFIG_OFF)
logs = []
res = LI.add_from_ldbk(__file__, "강남1", app_dir=app, console=CONSOLE, log=logs.append)
ck("새 인덱스를 돌려준다", res["index"] == "4", str(res))
ck("adbDebug 를 켰다", '"basicSettings.adbDebug":1' in
   open(os.path.join(VMS, "leidian4.config"), encoding="utf-8").read())
ck("감시 대상에 넣었다", 4 in json.load(open(fleet, encoding="utf-8"))["indexes"])
ck("RDP 가 필요하다고 알린다", any("RDP" in m for m in logs), str(logs[-1])[:60])

print("\n=== 10. UI 와 명령줄이 같은 함수를 쓴다 ===")
src = open("main.py", encoding="utf-8").read()
ck("GUI 버튼이 있다", "계정 추가(.ldbk 복원)" in src)
ck("워커 스레드에서 돈다", "class _AddInstanceThread" in src)
ck("같은 모듈을 부른다", "ld_instance.add_from_ldbk(" in src)
ck("명령줄 진입점도 있다", '__name__ == "__main__"' in open("ld_instance.py", encoding="utf-8").read())

bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패:", bad)
sys.exit(1 if bad else 0)

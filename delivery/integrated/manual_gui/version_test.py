"""판 표시(daangn_ext/version.py) — 창 없이 순수 함수만.

    python version_test.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


from daangn_ext import version as V
from datetime import datetime, timezone

print("=== A. local_version ===")
d = tempfile.mkdtemp()
os.makedirs(os.path.join(d, "data"))
with open(os.path.join(d, "data", "deployed.json"), "w", encoding="utf-8") as f:
    json.dump({"sha": "fc020db1234567890abcdef1234567890abcdef1", "short": "fc020db",
               "installed": "2026-09-02T23:39:47Z", "zip_reused": True}, f)
lv = V.local_version(d)
want_local = datetime(2026, 9, 2, 23, 39, 47, tzinfo=timezone.utc).astimezone().strftime("%m/%d %H:%M")
ck("배포 각인 읽기", lv["short"] == "fc020db" and lv["source"] == "deploy", str(lv))
ck("설치 시각 UTC → 현지", lv["installed"] == want_local, lv["installed"])
# BOM 붙은 파일도 읽는다 (PS 5.1 -Encoding UTF8 함정)
with open(os.path.join(d, "data", "deployed.json"), "wb") as f:
    f.write(b"\xef\xbb\xbf" + json.dumps({"sha": "abc1234" + "0" * 33, "short": "abc1234",
                                          "installed": "2026-09-01T00:00:00Z"}).encode())
ck("BOM 있는 각인도 읽음", V.local_version(d)["short"] == "abc1234")
with open(os.path.join(d, "data", "deployed.json"), "w") as f:
    json.dump({"sha": "unknown", "short": "unknown"}, f)
e = tempfile.mkdtemp()
ck("각인 unknown·git 없음 → 판 미상", V.local_version(e)["short"] == "")
here = V.local_version(os.path.dirname(os.path.abspath(__file__)))
ck("개발 PC: git 으로 판 읽음", here["source"] == "git" and len(here["short"]) == 7, str(here))

print("=== B. version_label ===")
loc = {"short": "fc020db", "sha": "fc020db" + "1" * 33, "installed": "09/03 08:39", "source": "deploy"}
t, st = V.version_label(loc, "", checked=False)
ck("확인 전: 확인 중", st == "unknown" and "확인 중" in t and t.startswith("v fc020db · 설치 09/03 08:39"), t)
t, st = V.version_label(loc, "", checked=True)
ck("확인 실패: 확인 못 함", st == "unknown" and "확인 못 함" in t, t)
t, st = V.version_label(loc, "fc020db" + "1" * 33, checked=True)
ck("같은 sha: 최신", st == "latest" and "최신" in t, t)
t, st = V.version_label(loc, "a1b2c3d" + "9" * 33, checked=True)
ck("다른 sha: 새 판 있음 + 앞 7자", st == "outdated" and "새 판 a1b2c3d" in t, t)
t, st = V.version_label({"short": "abc1234", "sha": "", "installed": "", "source": "git"}, "abc1234" + "0" * 33, True)
ck("git 판: '개발 판' 표기·짧은 sha 로 비교", st == "latest" and "개발 판" in t, t)
t, st = V.version_label({"short": "", "sha": "", "installed": "", "source": ""}, "x", True)
ck("판 미상", st == "none" and t == "판 미상", t)

print("=== C. fetch_latest_sha 는 예외를 안 낸다 ===")
V.LATEST_URL = "http://127.0.0.1:9/nope"
ck("연결 실패 → ''", V.fetch_latest_sha(timeout=2) == "")

print("\n" + "=" * 46)
bad = [n for n, c in R if not c]
print(f"{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("FAIL:", *bad, sep="\n  - ")
sys.exit(1 if bad else 0)

"""지역 순회 커서 — 완주 못 하는 스코프에서도 전 지역이 결국 방문되는가.

실서버는 `sweep_regions` 에 동 6537개가 들어 있다. 한 지역을 최대 200페이지까지
파므로 사이클 1회는 몇 달짜리다. 그런데 앱은 배포·재부팅으로 훨씬 자주 재시작되고,
재시작할 때마다 지역 0번부터 다시 시작했다 — 즉 **앞쪽 지역만 반복 수집되고
뒤쪽은 영원히 방문되지 않는다**. 커서는 그 불공평을 없앤다.

실행: python sweep_cursor_test.py
"""
import json
import os
import sys
import tempfile

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

from daangn.sweep_engine import _RegionCursor

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


tmp = tempfile.mkdtemp()
FP = os.path.join(tmp, "sweep_cursor.json")
REGIONS = [f"동{i}-{i}" for i in range(10)]

print("=== 1. 첫 실행은 전 지역이 대기 ===")
c = _RegionCursor(FP)
ck("전 지역 반환", c.order(REGIONS) == REGIONS, f"{len(c.order(REGIONS))}개")

print("\n=== 2. 중단 후 재시작이 앞쪽을 다시 훑지 않는다 ===")
for r in REGIONS[:3]:
    c.mark(r)
c.flush()
c2 = _RegionCursor(FP)                      # 프로세스 재시작 흉내
pending = c2.order(REGIONS)
ck("완료분은 빠진다", pending == REGIONS[3:], f"{pending[:2]}…")
ck("남은 개수", len(pending) == 7, f"{len(pending)}개")

print("\n=== 3. 한 바퀴 다 돌면 새 패스로 리셋 ===")
for r in pending:
    c2.mark(r)
c2.flush()
c3 = _RegionCursor(FP)
ck("전부 방문 뒤엔 다시 전 지역", c3.order(REGIONS) == REGIONS)
ck("패스 번호가 오른다", c3.passes >= 2, f"pass={c3.passes}")

print("\n=== 4. 지역 목록이 바뀌어도 깨지지 않는다 ===")
c4 = _RegionCursor(FP)
c4.mark(REGIONS[0])
c4.flush()
changed = ["새동-99"] + REGIONS[:5]         # 일부 제거 + 신규 추가
pend = _RegionCursor(FP).order(changed)
ck("사라진 지역은 무시", all(r in changed for r in pend))
ck("새 지역은 대기에 포함", "새동-99" in pend)
ck("이미 한 지역은 제외", REGIONS[0] not in pend, f"{pend}")

print("\n=== 5. 저장 파일이 깨져 있어도 진행한다 ===")
with open(FP, "w", encoding="utf-8") as f:
    f.write("{ 깨진 json")
c5 = _RegionCursor(FP)
ck("깨진 파일 → 처음부터", c5.order(REGIONS) == REGIONS)

print("\n=== 6. 쓸 수 없는 경로여도 죽지 않는다 ===")
try:
    c6 = _RegionCursor(os.path.join(tmp, "없는디렉터리", "x", "cur.json"))
    c6.order(REGIONS)
    c6.mark(REGIONS[0])
    c6.flush()
    ck("예외 없이 동작", True)
except Exception as e:
    ck("예외 없이 동작", False, f"{type(e).__name__}: {e}")

print("\n=== 7. mark 가 잦아도 파일 쓰기는 드물다 ===")
c7 = _RegionCursor(FP, save_every=5)
writes = {"n": 0}
orig = c7._write
c7._write = lambda: (writes.__setitem__("n", writes["n"] + 1), orig())[1]
c7.order(REGIONS)
for r in REGIONS:
    c7.mark(r)
ck("10회 mark 에 쓰기 2회", writes["n"] == 2, f"{writes['n']}회")

print("\n=== 8. 엔진이 실제로 커서를 쓴다(통합) ===")
# 클래스만 있고 run() 이 안 쓰면 아무 소용이 없다. collect_lanes 를 갈아끼워
# 지역을 '끝난 것처럼' 통보하고, 재시작 시 그 지역을 건너뛰는지 본다.
from daangn import sweep_engine as SE

CUR = os.path.join(tmp, "engine_cursor.json")
DB = os.path.join(tmp, "seen.db")
seen_regions = []


def fake_collect_lanes(keyword, regions, **kw):
    """레인 대신: 받은 지역을 그대로 완료 처리하고 요약을 돌려준다."""
    seen_regions.append([r["in"] for r in regions])
    on_result = kw.get("on_result")
    for r in regions:
        if on_result:
            on_result(r, [], {"requests": 1, "saturated": False, "missed": []})
    return [], {"regions": len(regions), "requests": len(regions), "skipped": 0}


def run_once(stop_after):
    eng = SE.SweepEngine({"keyword": "샤넬", "scope": "regions",
                          "regions": REGIONS[:4], "db_path": DB,
                          "cursor_fp": CUR, "rest_min": 10, "rest_max": 10})
    orig_lanes = SE.collect_lanes
    n = {"i": 0}

    def counting(*a, **kw):
        out = fake_collect_lanes(*a, **kw)
        n["i"] += 1
        if n["i"] >= stop_after:
            eng.stop()
        return out

    SE.collect_lanes = counting
    try:
        eng.run()
    finally:
        SE.collect_lanes = orig_lanes


run_once(stop_after=1)
ck("1회차가 전 지역을 받았다", seen_regions and seen_regions[0] == REGIONS[:4],
   f"{seen_regions[:1]}")
ck("커서 파일이 생겼다", os.path.exists(CUR))
if os.path.exists(CUR):
    saved = json.load(open(CUR, encoding="utf-8"))
    ck("완료가 (조건,지역) 쌍으로 기록된다",
       any(s.startswith("샤넬") and s.endswith("\t동0-0")
           for s in saved.get("done", [])),
       f"{saved.get('done', [])[:1]}")

print("\n=== 9. 같은 키워드 다른 조건은 서로를 건너뛰지 않는다 ===")
# 엑셀 조건표는 같은 키워드를 가격대·추가어만 달리해 여러 줄로 넣는다. 키가
# 키워드뿐이면 조건 A 가 끝낸 지역을 조건 B 가 통째로 건너뛴다 — 본 적도 없는데.
a = {"keyword": "샤넬", "min": 100, "max": 200}
b = {"keyword": "샤넬", "min": 300, "max": 400}
ck("조건이 다르면 키가 다르다", SE._ckey(a, "동1-1") != SE._ckey(b, "동1-1"),
   f"{SE._ckey(a, '동1-1')!r}")
ck("같은 조건·같은 지역이면 키가 같다", SE._ckey(a, "동1-1") == SE._ckey(dict(a), "동1-1"))
ck("지역이 다르면 키가 다르다", SE._ckey(a, "동1-1") != SE._ckey(a, "동2-2"))

cA = _RegionCursor(os.path.join(tmp, "two_cond.json"))
cA.order([SE._ckey(a, r) for r in REGIONS[:3]] + [SE._ckey(b, r) for r in REGIONS[:3]])
for r in REGIONS[:3]:
    cA.mark(SE._ckey(a, r))
cA.flush()
pend2 = _RegionCursor(os.path.join(tmp, "two_cond.json")).order(
    [SE._ckey(a, r) for r in REGIONS[:3]] + [SE._ckey(b, r) for r in REGIONS[:3]])
ck("조건 A 완료가 조건 B 를 가리지 않는다",
   all(SE._ckey(b, r) in pend2 for r in REGIONS[:3]) and len(pend2) == 3,
   f"남은 {len(pend2)}개")

seen_regions.clear()
run_once(stop_after=1)
# 1회차가 전 지역을 끝냈으므로 2회차는 새 패스를 열고 다시 전 지역을 받는다.
ck("한 바퀴 끝나면 새 패스로 다시 돈다",
   seen_regions and seen_regions[0] == REGIONS[:4], f"{seen_regions[:1]}")
saved2 = json.load(open(CUR, encoding="utf-8"))
ck("패스 번호가 올라간다", int(saved2.get("pass", 1)) >= 2, f"pass={saved2.get('pass')}")

print("\n=== 10. 확인 못 한 가격구간이 남은 지역은 완료로 찍지 않는다 ===")
# 엔진은 missed 가 있으면 "다음 사이클에 재시도"라고 알린다. 그런데 커서가
# 그 지역을 완료로 기록해 버리면 재시도는 이 패스 내내(6537동이면 몇 달) 오지
# 않는다 — 운영자에게는 재시도한다고 말해 놓고 실제로는 영영 불완전해진다.
CUR2 = os.path.join(tmp, "missed_cursor.json")
DB2 = os.path.join(tmp, "seen2.db")


def lanes_with_missed(keyword, regions, **kw):
    on_result = kw.get("on_result")
    for i, r in enumerate(regions):
        st = {"requests": 1, "saturated": False,
              # 홀수번째 지역만 가격구간 확인 실패
              "missed": [(0, 100)] if i % 2 else []}
        if on_result:
            on_result(r, [], st)
    return [], {"regions": len(regions), "requests": len(regions), "skipped": 0}


eng2 = SE.SweepEngine({"keyword": "샤넬", "scope": "regions",
                       "regions": REGIONS[:4], "db_path": DB2,
                       "cursor_fp": CUR2, "rest_min": 10, "rest_max": 10})
_orig = SE.collect_lanes
try:
    def once(*a, **kw):
        out = lanes_with_missed(*a, **kw)
        eng2.stop()
        return out
    SE.collect_lanes = once
    eng2.run()
finally:
    SE.collect_lanes = _orig

done2 = set(json.load(open(CUR2, encoding="utf-8")).get("done", []))
cond2 = {"keyword": "샤넬"}
clean = [REGIONS[0], REGIONS[2]]
dirty = [REGIONS[1], REGIONS[3]]
ck("확인 완료 지역은 기록된다",
   all(SE._ckey(cond2, r) in done2 for r in clean), f"{len(done2)}건")
ck("미확인 구간이 남은 지역은 기록되지 않는다",
   all(SE._ckey(cond2, r) not in done2 for r in dirty))
ck("따라서 다음 실행이 그 지역을 다시 돈다",
   set(_RegionCursor(CUR2).order([SE._ckey(cond2, r) for r in REGIONS[:4]]))
   == {SE._ckey(cond2, r) for r in dirty})

print("\n=== 11. 워터마크 원장 ===")
# 최신순은 publishedAt 내림차순으로 단조라, 지난 방문 시각까지만 파면 된다.
# 그 시각을 (조건,지역)마다 남긴다.
WM = os.path.join(tmp, "wm.json")
c11 = _RegionCursor(WM)
k = SE._ckey({"keyword": "샤넬"}, "동1-1")
ck("처음엔 워터마크가 없다", c11.watermark(k) is None)
c11.set_watermark(k, "2026-09-01T00:00:00Z")
c11.flush()
ck("기록 후 읽힌다", _RegionCursor(WM).watermark(k) == "2026-09-01T00:00:00Z")
c12 = _RegionCursor(WM)
c12.set_watermark(k, "2026-08-31T00:00:00Z")      # 과거로 되돌리기 시도
ck("워터마크는 뒤로 가지 않는다", c12.watermark(k) == "2026-09-01T00:00:00Z",
   "앞당기면 그 사이가 유실된다")
c12.set_watermark(k, "2026-09-01T12:00:00Z")
ck("앞으로는 간다", c12.watermark(k) == "2026-09-01T12:00:00Z")

c12.set_watermark(SE._ckey({"keyword": "없앨키워드"}, "동9-9"), "2026-09-01T00:00:00Z")
c12.flush()
dropped = c12.forget_stale([k])
ck("설정에서 사라진 키는 버린다", dropped >= 1 and c12.watermark(k) is not None,
   f"{dropped}건 정리")

print("\n=== 12. 수렴 판정 산수 ===")
# 사이클당 요청 = 지역 x 조건 x (주기 / 페이지폭). 사이클이 주기 안에 끝나야 하므로
# 주기가 약분되고 '지역 x 조건 = 페이지폭(초) x 초당요청수' 가 남는다.
ck("13 req/s 면 약 1.8만", 17000 < SE.sweep_capacity(13) < 19000,
   f"{SE.sweep_capacity(13):,.0f}")
ck("처리량에 비례한다", SE.sweep_capacity(26) == SE.sweep_capacity(13) * 2)
ck("페이지폭 실측값이 상수로 있다", 20 <= SE.PAGE_SPAN_MIN <= 26,
   f"{SE.PAGE_SPAN_MIN}분")
ck("이상한 입력에도 안 죽는다", SE.sweep_capacity(None) == 0.0)
# 실서버 설정(동 6537 x 브랜드 20)이 감당치를 넘는다는 것 자체를 고정한다.
ck("6537동x20브랜드는 13 req/s 로 수렴 불가",
   6537 * 20 > SE.sweep_capacity(13),
   f"{6537 * 20:,} > {SE.sweep_capacity(13):,.0f}")

print("\n=== 13. 엔진이 최신순 + 지역별 정지 규칙으로 부른다 ===")
CUR3 = os.path.join(tmp, "wm_engine.json")
DB3 = os.path.join(tmp, "seen3.db")
seen_kwargs = {}


def capture_lanes(keyword, regions, **kw):
    seen_kwargs["sort_option"] = kw.get("sort_option")
    seen_kwargs["regions"] = list(regions)
    on_result = kw.get("on_result")
    for i, r in enumerate(regions):
        st = {"requests": 1, "saturated": False, "missed": []}
        if i == 1:
            # 이 지역은 앱API 가 죽어 웹크롤로 떨어졌다 — 정지 규칙 미적용
            st["stop_before_unapplied"] = r.get("stop_before")
        if on_result:
            on_result(r, [], st)
    return [], {"regions": len(regions), "requests": len(regions), "skipped": 0}


def run_engine(cur_fp):
    eng = SE.SweepEngine({"keyword": "샤넬", "scope": "regions",
                          "regions": REGIONS[:3], "db_path": DB3,
                          "cursor_fp": cur_fp, "rest_min": 10, "rest_max": 10})
    _o = SE.collect_lanes
    try:
        def once(*a, **kw):
            out = capture_lanes(*a, **kw)
            eng.stop()
            return out
        SE.collect_lanes = once
        eng.run()
    finally:
        SE.collect_lanes = _o


run_engine(CUR3)
ck("최신순으로 부른다", seen_kwargs.get("sort_option") == SE.SORT_RECENT,
   f"{seen_kwargs.get('sort_option')}")
ck("지역마다 stop_before 를 실어 보낸다",
   all(isinstance(r, dict) and r.get("stop_before") for r in seen_kwargs["regions"]),
   f"{seen_kwargs['regions'][0]}")
ck("첫 방문은 최근 구간만 본다(끝까지 파지 않는다)",
   SE.FIRST_VISIT_WINDOW_MIN > 0 and seen_kwargs["regions"][0]["stop_before"] < SE._now_iso(),
   f"창 {SE.FIRST_VISIT_WINDOW_MIN:.0f}분")

marks = json.load(open(CUR3, encoding="utf-8")).get("marks", {})
c13 = {"keyword": "샤넬"}
ck("정상 지역은 워터마크가 선다",
   SE._ckey(c13, REGIONS[0]) in marks and SE._ckey(c13, REGIONS[2]) in marks,
   f"{len(marks)}건")
ck("웹크롤로 떨어진 지역은 워터마크를 안 올린다",
   SE._ckey(c13, REGIONS[1]) not in marks,
   "올리면 그 구간이 영영 빈다")

# 2회차: 선 워터마크가 그대로 stop_before 로 들어가야 한다
prev = marks[SE._ckey(c13, REGIONS[0])]
seen_kwargs.clear()
run_engine(CUR3)
sb = {r["in"]: r["stop_before"] for r in seen_kwargs["regions"]}
ck("2회차는 지난 방문 시각부터 훑는다", sb[REGIONS[0]] == prev, f"{sb[REGIONS[0]]}")
ck("워터마크 없던 지역은 여전히 첫 방문 창", sb[REGIONS[1]] != prev)

bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패:", bad)
sys.exit(1 if bad else 0)

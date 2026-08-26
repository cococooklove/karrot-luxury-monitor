"""동일 조건 반복 수집 편차 측정 — "데이터가 다르게 온다" 검증용 (클라이언트 제출).

같은 키워드·같은 지역·같은 로그인 상태(비로그인)로 N회 반복해
건수 편차와 재시도 소진(누락) 발생을 측정한다.

수정 전: 소진을 0건으로 반환 → 실행마다 0건 ↔ 270건
수정 후: 소진을 감지해 재시도 + missed 기록 → 편차 0 목표

실행:
    ../../../.venv/bin/python -u variance_test.py [키워드] [반복수] [지역코드]
    예) ../../../.venv/bin/python -u variance_test.py 샤넬 10 강남구-381
"""
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from daangn_ext.adaptive import collect_region

KEYWORD = sys.argv[1] if len(sys.argv) > 1 else "샤넬"
TRIALS = int(sys.argv[2]) if len(sys.argv) > 2 else 10
REGION = sys.argv[3] if len(sys.argv) > 3 else "강남구-381"

try:
    PROXIES = [l.strip() for l in open("settings.txt", encoding="utf-8")
               if l.strip().startswith("http")]
except FileNotFoundError:
    PROXIES = []

print(f"조건: '{KEYWORD}' · {REGION} · 비로그인 · {TRIALS}회 반복 · 프록시 {len(PROXIES)}개")
print(f"시작: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
print(f"{'회차':>3}  {'건수':>5}  {'요청':>4}  {'빈응답':>5}  {'미확인구간':>9}  {'소요':>6}")
print("-" * 46)

counts, missed_runs, idsets = [], 0, []
for i in range(1, TRIALS + 1):
    t0 = time.time()
    arts, st = collect_region(KEYWORD, REGION, only_on_sale=True,
                              proxies=PROXIES or None)
    dt = time.time() - t0
    counts.append(len(arts))
    idsets.append({a["id"] for a in arts})
    if st["missed"]:
        missed_runs += 1
    print(f"{i:>3}  {len(arts):>5}  {st['requests']:>4}  {st['empties']:>5}  "
          f"{len(st['missed']):>9}  {dt:>5.0f}s")

print("-" * 46)
lo, hi = min(counts), max(counts)
mean = statistics.mean(counts)
spread = (hi - lo) / hi * 100 if hi else 0.0
union = set().union(*idsets) if idsets else set()
common = set.intersection(*idsets) if idsets else set()

print(f"\n건수      최소 {lo} · 최대 {hi} · 평균 {mean:.1f}")
print(f"편차      {hi - lo}건 ({spread:.1f}%)")
print(f"매물 ID   합집합 {len(union)} · 모든 회차 공통 {len(common)}")
if union:
    print(f"          매 회차 재현율 {len(common) / len(union) * 100:.1f}%")
print(f"미확인    {missed_runs}/{TRIALS} 회차에서 확인 실패 구간 발생")

if lo == 0:
    print("\n❌ 0건 회차 있음 — 소프트차단 미극복. 프록시 수를 늘리거나 max_retry 상향 필요")
elif spread > 5:
    print(f"\n⚠️ 편차 {spread:.1f}% — 실매물 변동(등록/판매완료) 또는 잔여 누락 확인 필요")
else:
    print(f"\n✅ 편차 {spread:.1f}% — 동일 조건 반복 결과 안정")

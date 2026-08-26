"""구 단위 + 적응형 수집 시간 측정."""
import json, time, statistics
from delivery.daangn_ext.robust import robust_fetch_articles

OUT = "/private/tmp/claude-501/-Users-younglee---------/efe67086-6c00-4dc8-804b-6e28b11e67aa/scratchpad/manual/OUT.json"
CAP = 280   # 요청당 상한 근처면 '포화'로 간주 → 드릴다운 대상

d = json.load(open(OUT)); locs = []
for b in d: locs += b.get("locations", [])

# 전국 구(name2 단위) 유니크
gus = {}
for l in locs:
    key = (l["name1"], l["name2"])
    gus[key] = (f"{l['name2']}-{l['name2Id']}", l["name2Id"])
gu_list = list(gus.items())
dongs = [l for l in locs if l.get("depth") == 3]
print(f"[규모] 전국 동 {len(dongs)}개 / 구 {len(gu_list)}개  → 구단위면 {len(dongs)/len(gu_list):.0f}배 감소\n")

# 샘플 구 시간 측정
KW = "구찌"
sample = [v[0] for _, v in gu_list[:15]]
print(f"[측정] '{KW}' × 구 {len(sample)}개")
times, counts, saturated, ok = [], [], 0, 0
for i, inv in enumerate(sample):
    t0 = time.time()
    arts, meta = robust_fetch_articles(KW, inv, max_retry=8)
    dt = time.time() - t0
    n = len(arts)
    if n: ok += 1; times.append(dt)
    if n >= CAP: saturated += 1
    counts.append(n)
    print(f"  {inv:18} {n:4}건 {dt:6.2f}s tries{meta['tries']} "
          f"{'★포화→드릴다운' if n>=CAP else ''}")

if times:
    avg = statistics.mean(times)
    print(f"\n[구당] 성공 {ok}/{len(sample)}  평균 {avg:.2f}s  포화(드릴다운필요) {saturated}/{len(sample)}")
    NG = len(gu_list)
    sat_ratio = saturated / len(sample)
    base = NG * avg                                   # 구 전수 1회
    drill = NG * sat_ratio * 3 * avg                  # 포화 구만 가격3분할 추가
    total = base + drill
    print(f"\n[전국 추정 · 프록시1개]")
    print(f"  구 {NG}개 × {avg:.1f}s = {base/60:.1f}분")
    print(f"  + 포화구({sat_ratio*100:.0f}%) 가격3분할 = {drill/60:.1f}분")
    print(f"  = 총 약 {total/60:.1f}분 (동 전수 대비 {6537*avg/60:.0f}분 → {total/60:.0f}분)")
    print(f"\n  프록시 10개 병렬: 약 {total/10/60:.1f}분")
else:
    print("\n성공 0 — IP 스로틀. 프록시로 재측정 필요.")

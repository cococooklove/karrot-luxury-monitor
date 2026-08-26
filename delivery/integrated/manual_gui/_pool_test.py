import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
PROX = [l.strip() for l in open("proxies.txt") if l.strip()]
from daangn_ext.adaptive import collect_region

# 밀집구(강남) 적응형 — 단일프록시 vs 풀분산 비교
t0 = time.time()
arts1, st1 = collect_region("구찌", "강남구-381", proxy=PROX[0])          # 단일
t1 = time.time() - t0
t0 = time.time()
arts2, st2 = collect_region("구찌", "강남구-381", proxies=PROX)            # 풀분산
t2 = time.time() - t0
print(f"단일프록시: {len(arts1)}건 {t1:.1f}s 요청{st1['requests']} 분할{st1['splits']}")
print(f"풀20분산 : {len(arts2)}건 {t2:.1f}s 요청{st2['requests']} 분할{st2['splits']}")
print("결과:", "풀분산 빠름" if t2 < t1 else "비슷/역전", f"(건수 {len(arts1)} vs {len(arts2)})")

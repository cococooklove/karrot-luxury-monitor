"""전국 1브랜드 실수집 — 20프록시 병렬 + 적응형 + 중복제거 + CSV."""
import sys, os, time, json, csv, random, threading
import concurrent.futures as cf
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from daangn_ext.adaptive import collect_region, load_dong_regions
from daangn_ext.search_filters import KeywordRule

BRAND = sys.argv[1] if len(sys.argv) > 1 else "샤넬"
OUT = "/private/tmp/claude-501/-Users-younglee---------/efe67086-6c00-4dc8-804b-6e28b11e67aa/scratchpad/manual/OUT.json"
PROXIES = [l.strip() for l in open("proxies.txt") if l.strip()]

gus = [r["in"] for r in load_dong_regions(OUT)]   # 구 ID 는 폴백됨 → 동 단위
rule = KeywordRule(required=[BRAND], exclude=["레플", "미러", "이미테이션", "st", "스타일"])
print(f"브랜드 '{BRAND}' / 전국 구 {len(gus)}개 / 프록시 {len(PROXIES)}개")

seen = {}
lock = threading.Lock()
stats = {"req": 0, "sat": 0, "err": 0}

def rand_proxy():
    return random.choice(PROXIES)

def work(i_reg):
    i, reg = i_reg
    proxy = PROXIES[i % len(PROXIES)]
    try:
        arts, st = collect_region(BRAND, reg, proxy=proxy, only_on_sale=True,
                                  next_proxy=rand_proxy)
        with lock:
            stats["req"] += st["requests"]
            stats["sat"] += 1 if st["saturated"] else 0
            for a in arts:
                if rule.match(type("X", (), {"name": a.get("title", ""),
                                             "description": a.get("content", "")})):
                    seen[a["id"]] = {**a, "_gu": reg}
    except Exception as e:
        with lock:
            stats["err"] += 1
    return len(arts) if 'arts' in dir() else 0

t0 = time.time()
with cf.ThreadPoolExecutor(max_workers=20) as ex:
    list(ex.map(work, list(enumerate(gus))))
elapsed = time.time() - t0

out_csv = f"전국_{BRAND}.csv"
with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["지역(구)", "제목", "가격", "끌올", "링크"])
    for a in seen.values():
        w.writerow([a["_gu"], a.get("title", ""), a.get("price", ""),
                    a.get("boostedAt", ""), "https://www.daangn.com" + a.get("href", "")])

print(f"\n=== 전국 '{BRAND}' 실수집 결과 ===")
print(f"소요: {elapsed:.1f}초 ({elapsed/60:.1f}분)")
print(f"요청 총 {stats['req']}회 / 포화구(가격분할) {stats['sat']}개 / 오류구 {stats['err']}개")
print(f"고유 매물: {len(seen)}건 (레플/가품 제외 후)")
print(f"CSV: {out_csv}")
# 가격 상위 5
tops = sorted([a for a in seen.values() if str(a.get("price","")).isdigit()],
              key=lambda a: -int(a["price"]))[:5]
print("\n[가격 상위 5]")
for a in tops:
    print(f"  {int(a['price']):>12,}원  [{a['_gu']}] {a.get('title','')[:34]}")

"""전국 1브랜드 실수집 — 20프록시 병렬 + 적응형 + 중복제거 + CSV.

proxies.txt(실 프록시 계정, gitignore)가 없는 환경(신규 체크아웃, CI)에서는
실측 수집 구간을 [SKIP]하고 exit 0 (proxy_test.py 에서 세운 관례를 따른다).
그 대신 파일 없이도 가능한 부분(OUT.json → 동 목록 로딩, KeywordRule 필터링)은
항상 검증한다.

실행: python nationwide_test.py [브랜드]
"""
import sys, os, time, json, csv, random, threading
import concurrent.futures as cf

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from daangn_ext.adaptive import collect_region, load_dong_regions
from daangn_ext.search_filters import KeywordRule

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


BRAND = sys.argv[1] if len(sys.argv) > 1 else "샤넬"
OUT = "OUT.json"

print("=== 1. OUT.json → 동 목록 로딩 (네트워크 없음) ===")
if os.path.exists(OUT):
    gus = [r["in"] for r in load_dong_regions(OUT)]
    ck("load_dong_regions: 전국 동 목록 로딩", len(gus) > 0, f"{len(gus)}개")
    ck("동 코드 형식(이름-ID)", all("-" in g for g in gus[:50]))
else:
    print(f"[SKIP] {OUT} 없음 — 동 목록 로딩 생략")
    gus = []

print("\n=== 2. KeywordRule 필터링 (네트워크 없음) ===")
rule = KeywordRule(required=[BRAND], exclude=["레플", "미러", "이미테이션", "st", "스타일"])
_Prod = type("X", (), {})
ok_item = _Prod()
ok_item.name = f"{BRAND} 가방 정품"
ok_item.description = "직거래"
bad_item = _Prod()
bad_item.name = f"{BRAND} st 스타일 레플"
bad_item.description = ""
ck(f"'{BRAND}' 정품 매물 매치", rule.match(ok_item))
ck(f"'{BRAND}' 레플/st 매물 제외", not rule.match(bad_item))

print("\n=== 3. 전국 실수집 (20프록시 병렬) ===")
PROXY_PATH = "proxies.txt"
if not os.path.exists(PROXY_PATH):
    print(f"[SKIP] {PROXY_PATH} 없음(gitignore) — 전국 실수집 생략. "
          f"실행하려면 이 디렉터리({os.getcwd()})에 실 프록시 계정을 담은 "
          f"{PROXY_PATH}를 두고 재실행할 것.")
elif not gus:
    print(f"[SKIP] {OUT} 없음 — 순회할 동 목록이 없어 실수집 생략")
else:
    PROXIES = [l.strip() for l in open(PROXY_PATH, encoding="utf-8") if l.strip()]
    print(f"브랜드 '{BRAND}' / 전국 구 {len(gus)}개 / 프록시 {len(PROXIES)}개")

    seen = {}
    lock = threading.Lock()
    stats = {"req": 0, "sat": 0, "err": 0}

    def rand_proxy():
        return random.choice(PROXIES)

    def work(i_reg):
        i, reg = i_reg
        proxy = PROXIES[i % len(PROXIES)]
        arts = []
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
        except Exception:
            with lock:
                stats["err"] += 1
        return len(arts)

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
    ck("실수집: 최소 1건 수집", len(seen) > 0, f"{len(seen)}건")
    tops = sorted([a for a in seen.values() if str(a.get("price", "")).isdigit()],
                  key=lambda a: -int(a["price"]))[:5]
    print("\n[가격 상위 5]")
    for a in tops:
        print(f"  {int(a['price']):>12,}원  [{a['_gu']}] {a.get('title','')[:34]}")

print("\n" + "=" * 50)
passed = sum(1 for _, c in R if c)
print(f"===== {passed}/{len(R)} PASS =====")
bad = [n for n, c in R if not c]
if bad:
    print("FAIL:", *bad, sep="\n  - ")
sys.exit(0 if passed == len(R) else 1)

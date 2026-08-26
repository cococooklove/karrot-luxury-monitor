"""프록시 검증 + N배 스케일링 실측."""
import time, json, concurrent.futures as cf
from curl_cffi import requests
from bs4 import BeautifulSoup as Soup

PROXIES = [l.strip() for l in open("proxies.txt") if l.strip()]
OUT = "/private/tmp/claude-501/-Users-younglee---------/efe67086-6c00-4dc8-804b-6e28b11e67aa/scratchpad/manual/OUT.json"

def parse(h):
    for s in Soup(h, "html.parser").select("script"):
        if "window.__remixContext" in (s.text or ""):
            j = s.text.replace("window.__remixContext = ", "").rstrip(";")
            try:
                return len(json.loads(j)["state"]["loaderData"]["routes/kr.buy-sell._index"]["allPage"]["fleamarketArticles"])
            except Exception:
                return -1
    return -2

def fetch(proxy, region, kw="구찌", retry=6):
    params = {"search": kw, "in": region, "only_on_sale": "true", "price": "__"}
    t0 = time.time()
    for _ in range(retry):
        try:
            r = requests.get("https://www.daangn.com/kr/buy-sell/", impersonate="chrome",
                             proxy=proxy, timeout=20, params=params)
            n = parse(r.text)
            if n > 0:
                return time.time() - t0, n
            time.sleep(0.5)
        except Exception as e:
            return time.time() - t0, f"err:{str(e)[:30]}"
    return time.time() - t0, 0

# 지역 목록
d = json.load(open(OUT)); locs = []
for b in d: locs += b.get("locations", [])
gus = {}
for l in locs:
    gus[(l["name1Id"], l["name2Id"])] = f"{l['name2']}-{l['name2Id']}"
gu_list = list(gus.values())

print(f"프록시 {len(PROXIES)}개 / 전국 구 {len(gu_list)}개\n")

print("=== 1) 프록시 개별 검증 (첫 워밍 IP당) ===")
ok = 0; lat = []
def one_proxy(i_p):
    i, p = i_p
    dt, n = fetch(p, gu_list[i % len(gu_list)])
    return p.split("@")[1], dt, n
with cf.ThreadPoolExecutor(max_workers=20) as ex:
    res = list(ex.map(one_proxy, list(enumerate(PROXIES))))
for host, dt, n in res:
    good = isinstance(n, int) and n > 0
    ok += good;
    if good: lat.append(dt)
    print(f"  {host:24} {dt:5.1f}s  {n}")
print(f"\n작동 {ok}/{len(PROXIES)}  평균 {sum(lat)/len(lat):.1f}s" if lat else f"\n작동 {ok}/{len(PROXIES)}")

print("\n=== 2) 병렬 스케일링 실측 (20프록시 동시) ===")
N = 40  # 40개 구를 20프록시로
targets = gu_list[:N]
t0 = time.time()
def worker(i_reg):
    i, reg = i_reg
    p = PROXIES[i % len(PROXIES)]
    dt, n = fetch(p, reg)
    return reg, n
with cf.ThreadPoolExecutor(max_workers=20) as ex:
    r2 = list(ex.map(worker, list(enumerate(targets))))
elapsed = time.time() - t0
succ = sum(1 for _, n in r2 if isinstance(n, int) and n > 0)
print(f"{N}개 구 / 20프록시 병렬: {elapsed:.1f}s, 성공 {succ}/{N}")
if succ:
    per = elapsed / N
    full = per * len(gu_list) / 20  # 전국을 20프록시로
    print(f"구당 실효 {per:.2f}s → 전국 {len(gu_list)}구 / 20프록시 ≈ {full/60:.1f}분")

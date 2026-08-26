"""
전국 검색 시간 측정 + N계정 선형단축 검증.

측정:
  1) 전국 지역(동) 수 = 검색 단위 개수
  2) 세션 워밍업 비용(첫 빈응답 극복) + 워밍 후 지역당 정상 시간
  3) 1워커 전국 소요 → N워커(계정/프록시 N개) 소요 추정
"""
import json
import time
import statistics
from curl_cffi import requests
from bs4 import BeautifulSoup as Soup

OUT = "/private/tmp/claude-501/-Users-younglee---------/efe67086-6c00-4dc8-804b-6e28b11e67aa/scratchpad/manual/OUT.json"


def load_regions():
    d = json.load(open(OUT))
    locs = []
    for blk in d:
        locs += blk.get("locations", [])
    # depth3(동) = 검색단위
    dongs = [l for l in locs if l.get("depth") == 3]
    return locs, dongs


def parse(html):
    for s in Soup(html, "html.parser").select("script"):
        if "window.__remixContext" in (s.text or ""):
            j = s.text.replace("window.__remixContext = ", "").rstrip(";")
            try:
                return json.loads(j)["state"]["loaderData"][
                    "routes/kr.buy-sell._index"]["allPage"]["fleamarketArticles"]
            except Exception:
                return None
    return None


def timed_search(sess, kw, region, max_retry=15):
    """워밍 세션으로 1지역 검색. (경과초, 건수, 재시도수) 반환."""
    params = {"search": kw, "in": region, "only_on_sale": "true", "price": "__"}
    t0 = time.time()
    for i in range(max_retry):
        r = sess.get("https://www.daangn.com/kr/buy-sell/", params=params, timeout=15)
        arts = parse(r.text)
        if arts:
            return time.time() - t0, len(arts), i + 1
        time.sleep(0.6)
    return time.time() - t0, 0, max_retry


def main():
    locs, dongs = load_regions()
    print(f"[지역] 전체 {len(locs)}개 / 동(depth3) {len(dongs)}개 = 검색단위\n")

    # 샘플 지역(강남권 + 임의)로 워밍업+정상 측정
    sample = [f"{l['name3']}-{l['id']}" for l in dongs[:12]]
    kw = "샤넬"
    sess = requests.Session(impersonate="chrome")

    print(f"[측정] '{kw}' × {len(sample)}개 지역 (세션 1개 재사용)")
    times, retries = [], []
    for i, reg in enumerate(sample):
        dt, n, tr = timed_search(sess, kw, reg)
        tag = "워밍업" if i == 0 else ""
        print(f"  {i:2} {reg:16} {dt:6.2f}s  {n:4}건  재시도{tr} {tag}")
        times.append(dt); retries.append(tr)

    warm = times[0]
    steady = times[1:]
    avg = statistics.mean(steady)
    med = statistics.median(steady)
    print(f"\n[결과] 워밍업 첫지역={warm:.1f}s / 이후 지역당 avg={avg:.2f}s med={med:.2f}s")

    N = len(dongs)
    one = warm + avg * (N - 1)          # 1워커 순차
    print(f"\n[전국 추정] 동 {N}개 × 지역당 {avg:.2f}s")
    print(f"  1워커(계정1): {one/60:.1f}분 ({one:.0f}s)")
    for w in (5, 10, 20):
        # N워커: 각자 워밍업 1회 + (동/워커) 순차. 프록시 N개 가정.
        per = warm + avg * (N / w - 1)
        print(f"  {w}워커(계정{w}): {per/60:.1f}분   (선형대비 {one/w/60:.1f}분 + 워밍업오버헤드)")

    print("\n※ 브랜드 여러개면 × 브랜드수. 증분모니터는 신규만 → 훨씬 짧음.")


if __name__ == "__main__":
    main()

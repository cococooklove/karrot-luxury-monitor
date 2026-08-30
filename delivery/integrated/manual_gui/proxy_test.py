"""프록시 검증 + N배 스케일링 실측.

proxies.txt(실 프록시 계정, gitignore)가 없는 환경(신규 체크아웃, CI)에서는
임포트 단계에서 죽던 문제 수정: 파일이 없으면 실측 구간은 [SKIP]하고 exit 0.
그 대신 파일 없이도 가능한 부분(HTML 파싱 경로, proxies.txt 라인 형식)은 항상
검증한다. proxies.txt 가 있으면 실 프록시로 연결성/스케일링까지 실측한다.

실행: ../../../.venv/bin/python proxy_test.py
"""
import concurrent.futures as cf
import json
import os
import sys
import time

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from bs4 import BeautifulSoup as Soup

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


def parse(h):
    for s in Soup(h, "html.parser").select("script"):
        if "window.__remixContext" in (s.text or ""):
            j = s.text.replace("window.__remixContext = ", "").rstrip(";")
            try:
                return len(json.loads(j)["state"]["loaderData"]["routes/kr.buy-sell._index"]["allPage"]["fleamarketArticles"])
            except Exception:
                return -1
    return -2


print("=== 1. HTML 파싱 경로 (네트워크 없음) ===")

_OK_HTML = ('<html><body><script>window.__remixContext = '
            '{"state":{"loaderData":{"routes/kr.buy-sell._index":'
            '{"allPage":{"fleamarketArticles":[1,2,3]}}}}};</script></body></html>')
ck("parse: 정상 remixContext에서 매물 수 추출", parse(_OK_HTML) == 3, f"{parse(_OK_HTML)}건")

_BAD_JSON_HTML = '<html><body><script>window.__remixContext = {깨진 json;</script></body></html>'
ck("parse: JSON 파싱 실패 시 -1", parse(_BAD_JSON_HTML) == -1)

_NO_CTX_HTML = "<html><body>remixContext 없음</body></html>"
ck("parse: remixContext 없으면 -2", parse(_NO_CTX_HTML) == -2)

print("\n=== 2. proxies.txt 라인 형식 (proxies.example.txt로 구조 검증) ===")

EXAMPLE_PATH = "proxies.example.txt"
if os.path.exists(EXAMPLE_PATH):
    example = [l.strip() for l in open(EXAMPLE_PATH, encoding="utf-8") if l.strip()]
    ck("proxies.example.txt: 최소 1줄", len(example) > 0, f"{len(example)}줄")
    ck("각 줄이 http(s):// 스킴", all(p.startswith(("http://", "https://")) for p in example))
    ck("각 줄에서 host 추출 가능(split('@')[1])", all("@" in p for p in example))
else:
    print("[SKIP] proxies.example.txt 없음 — 라인 형식 구조 검증 생략")

print("\n=== 3. 실 프록시 연결성/스케일링 실측 ===")

PROXY_PATH = "proxies.txt"
if not os.path.exists(PROXY_PATH):
    print(f"[SKIP] {PROXY_PATH} 없음(gitignore) — 실 프록시 연결성/스케일링 실측 생략. "
          f"실행하려면 이 디렉터리({os.getcwd()})에 실 프록시 계정을 담은 {PROXY_PATH}를 "
          f"두고(형식은 {EXAMPLE_PATH} 참고) 재실행할 것.")
else:
    from curl_cffi import requests

    PROXIES = [l.strip() for l in open(PROXY_PATH, encoding="utf-8") if l.strip()]
    ck("proxies.txt: 최소 1개 로드", len(PROXIES) > 0, f"{len(PROXIES)}개")

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

    # 지역 목록: OUT.json(전국 동/구 스냅샷)이 있으면 쓰고, 없으면 알려진 기본 지역 하나로 폴백.
    # (OUT.json 은 별도 실측 산출물이라 리포에는 없다 — 없어도 개별 연결성 검증은 가능해야 한다.)
    OUT = "OUT.json"
    if os.path.exists(OUT):
        d = json.load(open(OUT, encoding="utf-8"))
        locs = []
        for b in d:
            locs += b.get("locations", [])
        gus = {}
        for l in locs:
            gus[(l["name1Id"], l["name2Id"])] = f"{l['name2']}-{l['name2Id']}"
        gu_list = list(gus.values())
    else:
        print(f"[SKIP] {OUT} 없음 — 전국 지역 목록 기반 스케일링은 생략, 기본 지역 1곳으로 연결성만 검증")
        gu_list = ["역삼동-6035"]

    print(f"프록시 {len(PROXIES)}개 / 대상 지역 {len(gu_list)}개\n")

    print("--- 3-1) 프록시 개별 검증 ---")
    ok = 0
    lat = []

    def one_proxy(i_p):
        i, p = i_p
        dt, n = fetch(p, gu_list[i % len(gu_list)])
        return p.split("@")[1], dt, n

    with cf.ThreadPoolExecutor(max_workers=20) as ex:
        res = list(ex.map(one_proxy, list(enumerate(PROXIES))))
    for host, dt, n in res:
        good = isinstance(n, int) and n > 0
        ok += good
        if good:
            lat.append(dt)
        print(f"  {host:24} {dt:5.1f}s  {n}")
    print(f"\n작동 {ok}/{len(PROXIES)}  평균 {sum(lat)/len(lat):.1f}s" if lat else f"\n작동 {ok}/{len(PROXIES)}")
    ck("개별 검증: 최소 1개 프록시 정상 응답", ok > 0, f"{ok}/{len(PROXIES)}")

    if len(gu_list) > 1:
        print("\n--- 3-2) 병렬 스케일링 실측 (20프록시 동시) ---")
        N = min(40, len(gu_list))
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
        ck("병렬 스케일링: 최소 1개 지역 성공", succ > 0, f"{succ}/{N}")
        if succ:
            per = elapsed / N
            full = per * len(gu_list) / 20
            print(f"구당 실효 {per:.2f}s → 전국 {len(gu_list)}구 / 20프록시 ≈ {full/60:.1f}분")

print("\n" + "=" * 50)
passed = sum(1 for _, c in R if c)
print(f"===== {passed}/{len(R)} PASS =====")
bad = [n for n, c in R if not c]
if bad:
    print("FAIL:", *bad, sep="\n  - ")
sys.exit(0 if passed == len(R) else 1)

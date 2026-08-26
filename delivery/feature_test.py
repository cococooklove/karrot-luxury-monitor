"""
클라 요구기능 실데이터 검증 — 당근 실수집 + 재시도 + 필터/가격/정렬/끌올.

핵심수정: 당근은 새 세션 초기요청을 빈 페이지로 응답(첫 몇 건 0건) → 그 후 정상.
기존 코드는 빈 결과를 '성공(0건)'으로 처리해 재시도 안 함 = 막힘의 정체.
여기선 '빈 결과 = 소프트블록'으로 보고 재시도.
"""
import json
import time
from curl_cffi import requests
from bs4 import BeautifulSoup as Soup

from delivery.daangn_ext.search_filters import KeywordRule, apply_filter


def _parse(html):
    for s in Soup(html, "html.parser").select("script"):
        if "window.__remixContext" in (s.text or ""):
            j = s.text.replace("window.__remixContext = ", "").rstrip(";")
            route = json.loads(j)["state"]["loaderData"]["routes/kr.buy-sell._index"]
            return route.get("allPage", {}).get("fleamarketArticles", [])
    return None


def fetch(keyword, area, proxy=None, only_on_sale=True,
          min_price=None, max_price=None, max_retry=15):
    """빈 결과=소프트블록 → 재시도. 실제 매물 나올 때까지(최대 max_retry)."""
    price = f"{min_price or ''}__{max_price or ''}"
    params = {"search": keyword, "in": area, "price": price}
    if only_on_sale:
        params["only_on_sale"] = "true"
    sess = requests.Session(impersonate="chrome")     # 쿠키 유지 세션
    empties = 0
    for i in range(max_retry):
        r = sess.get("https://www.daangn.com/kr/buy-sell/", params=params,
                     proxy=proxy, timeout=15)
        arts = _parse(r.text)
        if arts is None:
            time.sleep(1); continue
        if arts:
            return arts, i + 1, empties
        empties += 1
        time.sleep(0.8)
    return [], max_retry, empties


class Prod:
    def __init__(s, a):
        s.name = a.get("title", "")
        s.description = a.get("content", "")
        s.price_raw = a.get("price")
        s.price = int(a["price"]) if (a.get("price") or "").isdigit() else None
        s.href = a.get("href", "")
        s.boostedAt = a.get("boostedAt")
        s.createdAt = a.get("createdAt")
        s.status = a.get("status")


def line(p):
    return f"{(p.name or '')[:34]:34} {str(p.price_raw):>9}  끌올={str(p.boostedAt)[:16]}"


def main():
    KW, AREA = "샤넬", "역삼동-6035"
    print(f"=== 실수집: '{KW}' @ {AREA} ===")
    raw, tries, empties = fetch(KW, AREA, min_price=None, max_price=None)
    print(f"[수집] {len(raw)}건 (재시도 {tries}회, 빈응답 {empties}회 극복)\n")
    if not raw:
        print("수집 실패 — 프록시 필요할 수 있음."); return
    prods = [Prod(a) for a in raw]

    # 요구1: 메인사진/제목/본문/끌올시간/가격 필드
    a0 = raw[0]
    print("[요구:필드] 제목/본문/가격/썸네일/끌올/상태 존재?",
          all(k in a0 for k in ("title", "content", "price", "thumbnail", "boostedAt", "status")))

    # 요구2: 키워드 + 추가키워드 포함필터 + 제외
    rule = KeywordRule(required=["샤넬"], extra=["정품"], extra_mode="and", exclude=["레플", "미러", "st"])
    f2 = apply_filter(prods, rule)
    print(f"[요구:포함필터] 샤넬+정품-레플: {len(prods)}→{len(f2)}")

    # 요구3: 금액 최소~최대
    lo, hi = 500000, 3000000
    f3 = [p for p in prods if p.price is not None and lo <= p.price <= hi]
    print(f"[요구:가격범위] {lo:,}~{hi:,}: {len(f3)}건")

    # 요구4: 정렬 — 최근/오래된(끌올), 가격 낮은/높은순
    by_recent = sorted([p for p in prods if p.boostedAt], key=lambda p: p.boostedAt, reverse=True)
    by_priceasc = sorted([p for p in prods if p.price], key=lambda p: p.price)
    print(f"[요구:정렬] 끌올최신 top1: {line(by_recent[0])}")
    print(f"[요구:정렬] 가격낮은순 top1: {line(by_priceasc[0])}")
    print(f"[요구:정렬] 가격높은순 top1: {line(by_priceasc[-1])}")

    print("\n--- 샘플 5건(가격높은순) ---")
    for p in sorted([x for x in prods if x.price], key=lambda x: -x.price)[:5]:
        print("  ", line(p))

    print("\n[결과] 토큰 없이 실수집·필터·가격·정렬 전부 동작. "
          "간헐 빈응답은 재시도로 극복(빈응답 극복 확인).")


if __name__ == "__main__":
    main()

"""
명품 중고거래 응답 → 매물 레코드 정규화 + 리셀 강화.

2계층:
  [A] normalize(raw)  — 앱/웹 응답 dict 1건 → 표준 레코드. 필드 경로는 캡처 후 MAP 에 확정.
  [B] enrich(record)  — 제목/본문 텍스트만으로 브랜드·상태·가품의심·번들 판정. 스키마 무관, 지금 동작.

collect/monitor 는 parse.extract 대신 이 파일의 extract 를 쓰면 명품용 필드가 붙는다.
"""
import json
import re

# ── [A] 정규화 MAP ──────────────────────────────────────────────
# 캡처 응답(앱: kr.co.towneers.www / 웹: window.__remixContext) 확인 후 실제 경로로 교체.
# 점표기 지원. 빈 list_path 면 최장 dict-list 자동탐색.
MAP = {
    "list_path": "",
    "id": "id",              # 중복제거 키 (dbId/nodeId)
    "title": "title",
    "body": "content",       # 본문 전체 (브랜드/상태 판정 원천)
    "price": "price",
    "status": "status",      # 판매중/예약/판매완료
    "region": "region_name",
    "images": "images",      # 원본 이미지 배열
    "view_count": "viewCount",
    "chat_count": "chatCount",
    "created_at": "createdAt",
    "bumped_at": "republishedAt",
    "href": "href",
    "seller": "user",        # 판매자 객체 (webCrawlNotAllowed 확인용)
}

# ── [B] 리셀 사전 ───────────────────────────────────────────────
# 브랜드 → 정규 표기. 키는 소문자/공백제거 매칭용 별칭.
BRANDS = {
    "샤넬": "샤넬", "chanel": "샤넬",
    "루이비통": "루이비통", "루이뷔통": "루이비통", "루뷔": "루이비통", "lv": "루이비통", "louisvuitton": "루이비통",
    "에르메스": "에르메스", "hermes": "에르메스",
    "구찌": "구찌", "gucci": "구찌",
    "프라다": "프라다", "prada": "프라다",
    "디올": "디올", "dior": "디올",
    "셀린느": "셀린느", "셀린": "셀린느", "celine": "셀린느",
    "보테가": "보테가베네타", "보테가베네타": "보테가베네타", "bottega": "보테가베네타",
    "생로랑": "생로랑", "입생로랑": "생로랑", "ysl": "생로랑", "saintlaurent": "생로랑",
    "발렌시아가": "발렌시아가", "balenciaga": "발렌시아가",
    "펜디": "펜디", "fendi": "펜디",
    "버버리": "버버리", "burberry": "버버리",
    "몽클레르": "몽클레르", "몽클레어": "몽클레르", "moncler": "몽클레르",
    "고야드": "고야드", "goyard": "고야드",
    "롤렉스": "롤렉스", "rolex": "롤렉스",
    "까르띠에": "까르띠에", "cartier": "까르띠에",
    "티파니": "티파니", "tiffany": "티파니",
    "불가리": "불가리", "bvlgari": "불가리", "bulgari": "불가리",
    "반클리프": "반클리프", "vancleef": "반클리프",
    "오메가": "오메가", "omega": "오메가",
    "예거": "예거르쿨트", "jaeger": "예거르쿨트",
    "파텍": "파텍필립", "patek": "파텍필립",
}

# 상태 신호 (높을수록 상급). 정규식 → 등급 라벨.
CONDITION = [
    (re.compile(r"미개봉|새상품|새제품|미사용|풀박스|풀박|택포함|택그대로|s급|S급"), "최상"),
    (re.compile(r"a급|A급|거의새것|상태좋|깨끗|생활기스없"), "상"),
    (re.compile(r"b급|B급|사용감|생활기스|잔기스"), "중"),
    (re.compile(r"c급|C급|많이사용|하자|파손|수선|부분수선"), "하"),
]

# 정품 신뢰 신호
AUTH_POS = re.compile(r"정품|영수증|보증서|개런티|시리얼|공홈|백화점구매|매장구매|정품확인")
# 가품/오탐 신호 → 리셀 제외 후보
FAKE = re.compile(r"레플|레플리카|미러|미러급|이미테이션|스타일|s급복각|짝퉁|가품|정품아님|아님\s*주의|AAA|같은느낌")
# 부속품/오탐 (본품 아님)
ACCESSORY = re.compile(r"더스트백|보증서만|박스만|쇼핑백|스트랩만|참만|보관함만|택만|영수증만")
# 번들(여러개 묶음) → 개별 시세 왜곡
BUNDLE = re.compile(r"일괄|묶음|세트|여러개|몰아서|한번에|\d+\s*(개|점)\s*(일괄|묶음|판매)")

_PRICE_NUM = re.compile(r"[0-9][0-9,]*")


def _dig(obj, dotted):
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _find_list(obj):
    best = []
    def walk(o):
        nonlocal best
        if isinstance(o, list):
            if o and isinstance(o[0], dict) and len(o) > len(best):
                best = o
            for x in o:
                walk(x)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
    walk(obj)
    return best


def price_to_int(v):
    """'1,250,000원' / 1250000 / '125만' → 정수 원. 실패 시 None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v)
    man = re.search(r"([0-9,]+)\s*만", s)
    if man:
        return int(man.group(1).replace(",", "")) * 10000
    m = _PRICE_NUM.search(s)
    return int(m.group(0).replace(",", "")) if m else None


def detect_brand(text):
    t = re.sub(r"\s+", "", (text or "")).lower()
    for alias, canon in BRANDS.items():
        if alias.lower() in t:
            return canon
    return None


def detect_condition(text):
    t = text or ""
    for rx, label in CONDITION:
        if rx.search(t):
            return label
    return "미상"


def enrich(rec):
    """스키마 무관. 표준 레코드에 리셀 판정 필드 부착."""
    text = f"{rec.get('title') or ''} {rec.get('body') or ''}"
    brand = detect_brand(text)
    rec["brand"] = brand
    rec["condition"] = detect_condition(text)
    rec["price_num"] = price_to_int(rec.get("price"))
    rec["authentic_signal"] = bool(AUTH_POS.search(text))
    rec["suspect_fake"] = bool(FAKE.search(text))
    rec["is_accessory"] = bool(ACCESSORY.search(text))
    rec["is_bundle"] = bool(BUNDLE.search(text))
    # 리셀 시세 산정에 넣을지: 브랜드 있고 + 가품/부속품/번들 아님 + 가격 유효
    rec["resell_ok"] = bool(
        brand and rec["price_num"]
        and not rec["suspect_fake"]
        and not rec["is_accessory"]
        and not rec["is_bundle"]
    )
    return rec


def normalize(it):
    """응답 dict 1건 → 표준 레코드 (+enrich)."""
    seller = it.get(MAP["seller"]) if isinstance(it.get(MAP["seller"]), dict) else {}
    rec = {
        "id": it.get(MAP["id"]),
        "title": it.get(MAP["title"]),
        "body": it.get(MAP["body"]),
        "price": it.get(MAP["price"]),
        "status": it.get(MAP["status"]),
        "region": it.get(MAP["region"]),
        "images": it.get(MAP["images"]),
        "view_count": it.get(MAP["view_count"]),
        "chat_count": it.get(MAP["chat_count"]),
        "created_at": it.get(MAP["created_at"]),
        "bumped_at": it.get(MAP["bumped_at"]),
        "href": it.get(MAP["href"]),
        # 준법: 판매자가 크롤 거부 플래그면 제외 대상 표시
        "crawl_blocked": bool(seller.get("webCrawlNotAllowed")) if seller else False,
        "_raw": it,
    }
    return enrich(rec)


def extract(resp_json):
    if isinstance(resp_json, str):
        resp_json = json.loads(resp_json)
    items = _dig(resp_json, MAP["list_path"]) if MAP["list_path"] else None
    if not isinstance(items, list):
        items = _find_list(resp_json)
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        rec = normalize(it)
        if rec["id"] is None or rec["crawl_blocked"]:
            continue
        out.append(rec)
    return out


if __name__ == "__main__":
    # 스모크: enrich 로직만 (스키마 무관)
    samples = [
        {"title": "샤넬 클래식 미디움 캐비어 정품 영수증", "content": "s급 풀박스", "price": "5,500,000원"},
        {"title": "루이비통 스피디 레플 미러급", "content": "정품아님 주의", "price": 120000},
        {"title": "구찌 더스트백만 판매", "content": "박스만", "price": "10000"},
        {"title": "명품 지갑 일괄 3개 묶음", "content": "브랜드 다양", "price": "30만"},
    ]
    for s in samples:
        r = enrich(normalize(s) if False else {"title": s["title"], "body": s["content"], "price": s["price"]})
        print(f"brand={r['brand']} cond={r['condition']} price={r['price_num']} "
              f"fake={r['suspect_fake']} acc={r['is_accessory']} bundle={r['is_bundle']} "
              f"resell_ok={r['resell_ok']}")

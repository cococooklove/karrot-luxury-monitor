"""재시도 소진(exhausted) 처리 테스트 — 소프트차단이 '0건'으로 둔갑하지 않는지.

배경: 같은 키워드·같은 지역·로그인 상태 동일한데 결과가 0건 ↔ 270건으로 갈렸다.
원인은 당근의 빈 페이지 응답(소프트차단) + 재시도 소진을 성공한 0건으로 반환한 것.

실행: ../../../.venv/bin/python robust_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


import daangn_ext.robust as robust
from daangn_ext import adaptive

REAL_FETCH = robust.robust_fetch_articles

ART = {"id": "1", "title": "샤넬백", "price": "1000000", "href": "u",
       "boostedAt": "2026-08-26T00:00:00", "content": "", "thumbnail": ""}

print("=== A. robust: 소진과 진짜 0건 구분 ===")

ck("기본 재시도 한도 상향(30→45)",
   REAL_FETCH.__defaults__ is not None and 45 in REAL_FETCH.__defaults__,
   f"max_retry={[d for d in REAL_FETCH.__defaults__ if d == 45]}")

# 항상 빈 페이지를 주는 서버 → 소진되어야 하고, exhausted 로 표시돼야 한다
calls = {"n": 0}


class EmptyResp:
    status_code = 200
    headers = {}
    text = "<html><script>window.__remixContext = " \
           '{"state":{"loaderData":{"routes/kr.buy-sell._index":{"allPage":' \
           '{"fleamarketArticles":[]}}}}};</script></html>'


class FakeSession:
    def __init__(self, *a, **k):
        pass

    def get(self, *a, **k):
        calls["n"] += 1
        return EmptyResp()


robust.requests.Session = FakeSession
robust.time.sleep = lambda *_a, **_k: None

arts, meta = REAL_FETCH("샤넬", "강남구-381", max_retry=5)
ck("빈응답만 오면 소진", arts == [] and meta.get("exhausted") is True, str(meta.get("exhausted")))
# 카나리아 도입 후 총 요청 = 본시도(max_retry) + 카나리아 호출
ck("소진까지 max_retry 만큼 시도(+카나리아)",
   calls["n"] == 5 + meta.get("canaries", 0),
   f"{calls['n']}회 = 본시도 5 + 카나리아 {meta.get('canaries')}")
ck("빈응답 횟수 집계", meta.get("empties") == 5, f"empties={meta.get('empties')}")

print("\n=== B. collect_region: 소진 → 재시도 → missed 기록 ===")

seq = []


def fake_fetch(keyword, region_in, **kw):
    """1·2번째(0~1억 본시도+재시도) 소진, 이후 정상 → missed 1건 남아야 함."""
    seq.append((kw.get("min_price"), kw.get("max_price")))
    if len(seq) <= 2:
        return [], {"exhausted": True, "empties": 45, "blocked": 0}
    return [ART], {"empties": 0, "blocked": 0}


adaptive.robust_fetch_articles = fake_fetch
arts, st = adaptive.collect_region("샤넬", "강남구-381", proxies=["http://a:1", "http://b:2"])
ck("소진 시 새 IP 로 1회 더 시도", len(seq) >= 2 and seq[0] == seq[1], f"{seq[:2]}")
ck("두 번 다 소진 → missed 기록", st["missed"] == [(0, adaptive.PMAX)], str(st["missed"]))
ck("missed 있어도 나머지 구간은 수집", len(arts) == 1, f"{len(arts)}건")
ck("빈응답 누계 집계", st["empties"] == 90, f"empties={st['empties']}")

# 전 구간 정상이면 missed 비어야 함
seq.clear()
adaptive.robust_fetch_articles = lambda k, r, **kw: ([ART], {"empties": 0})
arts2, st2 = adaptive.collect_region("샤넬", "강남구-381")
ck("정상이면 missed 없음", st2["missed"] == [] and len(arts2) == 1)

# 진짜 0건(소진 아님) → missed 없이 0건
adaptive.robust_fetch_articles = lambda k, r, **kw: ([], {"empties": 0})
arts3, st3 = adaptive.collect_region("없는키워드", "강남구-381")
ck("진짜 0건은 missed 아님(오탐 없음)", st3["missed"] == [] and arts3 == [])

print("\n=== B2. 카나리아: 억제(suppressed) 와 차단(exhausted) 구분 ===")

# 카나리아가 통과하면 = 세션·IP 정상 → 이 쿼리만 억제 → 조기 종료
robust.requests.Session = FakeSession
calls["n"] = 0


class MixedSession(FakeSession):
    """본쿼리는 항상 빈 결과, 카나리아('삽니다')는 정상 → 억제로 판정돼야 함."""
    def get(self, url, params=None, **k):
        calls["n"] += 1
        if params and params.get("search") == robust.CANARY_KEYWORD:
            return OkResp()
        return EmptyResp()


class OkResp:
    status_code = 200
    headers = {}
    text = "<html><script>window.__remixContext = " \
           '{"state":{"loaderData":{"routes/kr.buy-sell._index":{"allPage":' \
           '{"fleamarketArticles":[{"id":"9","title":"t","price":"1","href":"u",' \
           '"boostedAt":"2026-08-26T00:00:00","content":"","thumbnail":""}]}}}}};</script></html>'


robust.requests.Session = MixedSession
arts, meta = REAL_FETCH("샤넬", "강남구-381", max_retry=45)
ck("카나리아 통과 → 억제로 판정", meta.get("suppressed") is True, f"suppressed={meta.get('suppressed')}")
ck("억제면 조기 종료(45회 안 돌림)", calls["n"] <= 6, f"{calls['n']}회 요청")
ck("억제는 exhausted 아님", not meta.get("exhausted"))

# 카나리아도 실패하면 = 진짜 차단 → 끝까지 재시도 후 exhausted
calls["n"] = 0
robust.requests.Session = FakeSession
arts, meta = REAL_FETCH("샤넬", "강남구-381", max_retry=8)
ck("카나리아 실패 → 차단으로 판정(exhausted)",
   meta.get("exhausted") is True and not meta.get("suppressed"), str(meta.get("exhausted")))
ck("카나리아 호출 상한 준수", meta.get("canaries", 0) <= robust.CANARY_MAX,
   f"카나리아 {meta.get('canaries')}회")

# 회귀: 프록시 풀이 있으면 빈응답마다 로테이션이 돈다.
# 그때 empty_run 이 리셋되면 카나리아 임계에 영원히 도달하지 못한다(실측 804s 낭비).
calls["n"] = 0
robust.requests.Session = MixedSession
arts, meta = REAL_FETCH("샤넬", "강남구-381", max_retry=45,
                        proxies=[f"http://p{i}:1" for i in range(20)])
ck("프록시 로테이션 중에도 카나리아 작동", meta.get("suppressed") is True,
   f"suppressed={meta.get('suppressed')} 요청={calls['n']}회")
ck("로테이션 경로에서도 조기 종료", calls["n"] <= 6, f"{calls['n']}회 요청")

print("\n=== B3. collect_region: 억제 → 접미어 우회 ===")

seq2 = []


def fake_suppressed(keyword, region_in, **kw):
    seq2.append(keyword)
    if keyword == "샤넬":
        return [], {"suppressed": True, "empties": 3}
    return [ART], {"empties": 0}          # 접미어 붙은 키워드는 정상


adaptive.robust_fetch_articles = fake_suppressed
arts4, st4 = adaptive.collect_region("샤넬", "강남구-381")
ck("억제 감지", st4["suppressed"] >= 1, f"suppressed={st4['suppressed']}")
ck("접미어로 우회 성공", st4["expanded"] and st4["expanded"][0] == "샤넬가방", str(st4["expanded"]))
ck("우회 결과가 수집됨", len(arts4) == 1, f"{len(arts4)}건")
ck("억제는 missed 아님(누락으로 오분류 금지)", st4["missed"] == [], str(st4["missed"]))
ck("접미어 시도 상한 준수",
   sum(1 for k in seq2 if k.startswith("샤넬") and k != "샤넬") <= adaptive.EXPAND_TRIES,
   f"{[k for k in seq2 if k != '샤넬']}")

print("\n=== C. get_products: 소진과 실패 메시지 구분 ===")

import daangn.api as api

api.robust_fetch_articles = lambda **kw: ([], {"exhausted": True, "empties": 45, "blocked": 0})
try:
    api.get_products("강남구-381", "강남구", "샤넬", True, None, None)
    ck("소진 시 예외 발생", False, "예외 없음")
except Exception as e:
    ck("소진 시 예외 문구에 '재시도 소진' 명시", "재시도 소진" in str(e), str(e)[:70])

api.robust_fetch_articles = lambda **kw: ([], {"empties": 0, "blocked": 3})
try:
    api.get_products("강남구-381", "강남구", "샤넬", True, None, None)
    ck("일반 실패 시 예외 발생", False, "예외 없음")
except Exception as e:
    ck("일반 실패는 기존 문구 유지", "재시도 소진" not in str(e), str(e)[:70])

print("\n" + "=" * 46)
bad = [n for n, c in R if not c]
print(f"{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("FAIL:", *bad, sep="\n  - ")
sys.exit(1 if bad else 0)

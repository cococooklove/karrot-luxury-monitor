"""키워드 알림 파이프라인 오프라인 자체검증 — 네트워크·adb·계정 없이 돈다.

배포 전 회귀 게이트. 실패하면 종료코드 1.
용법: python3 tools/selftest_alert.py
"""
import json
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "collector"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

FAILED = []


def check(name, cond, detail=""):
    mark = "✅" if cond else "❌"
    print(f"{mark} {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


# ── 1. 알림 엔드포인트 스펙 ───────────────────────────────────────
import keyword_alert as ka  # noqa: E402

spec = ka.load_spec()
check("info 경로 확정",
      spec["info"]["path"] == "/api/v1/fleamarket/keyword/notification/info",
      spec["info"]["path"])
check("info 호스트가 search-bff(피닝 없음)", "search-bff" in spec["host"], spec["host"])

learned = ka.learn_from_capture(path="/tmp/_selftest_spec.json") \
    if os.path.exists(ka.CAPTURE) else spec
check("캡처 학습이 info 를 유지", learned["info"]["path"] == spec["info"]["path"])
if os.path.exists("/tmp/_selftest_spec.json"):
    os.remove("/tmp/_selftest_spec.json")

# 미확정 경로는 명확히 막혀야 한다(조용한 실패 금지)
blank = dict(spec)
blank["register"] = {"method": "POST", "path": None}
client = ka.KeywordAlertClient.__new__(ka.KeywordAlertClient)
client.spec = blank
try:
    client._call("register", keyword="샤넬가방")
    check("미확정 경로는 EndpointUnknown", False, "예외 안 남")
except ka.EndpointUnknown:
    check("미확정 경로는 EndpointUnknown", True)
except Exception as e:
    check("미확정 경로는 EndpointUnknown", False, type(e).__name__)

# body_template 치환
tpl = {"keyword": "PLACEHOLDER", "nested": {"searchKeyword": "X"}, "n": 1}
ka._fill_keyword(tpl, "루이비통가방")
check("body_template keyword 치환(중첩 포함)",
      tpl["keyword"] == "루이비통가방" and tpl["nested"]["searchKeyword"] == "루이비통가방"
      and tpl["n"] == 1, json.dumps(tpl, ensure_ascii=False))

# 목록 응답 관용 파싱
sample = {"data": {"items": [{"keyword": "샤넬가방"}, {"keyword": "롤렉스시계"}],
                   "totalCount": 2}}
check("목록 응답에서 키워드 추출",
      ka._extract_keywords(sample) == ["샤넬가방", "롤렉스시계"],
      str(ka._extract_keywords(sample)))

# ── 2. 키워드셋 ──────────────────────────────────────────────────
import build_keyword_set as bks  # noqa: E402

full = bks.build()
tier1 = bks.build(tier=1)
check("키워드셋 생성", len(full) > 100, f"{len(full)}개")
check("브랜드 별칭 중복 제거",
      len({i["brand"] for i in full}) == len(bks.canonical_brands()))
check("티어1이 전체의 부분집합", 0 < len(tier1) < len(full), f"{len(tier1)}")
check("접미어 조합 기본(단독 브랜드 없음 — 억제 회피)",
      all(i["suffix"] for i in full))

# ── 3. 앱 검색 바디 ──────────────────────────────────────────────
import app_search as aps  # noqa: E402

b = aps.build_body("샤넬가방", "6128", 37.498, 127.026)
check("spatialContext 루트에 존재", "spatialContext" in b)
check("spatialContext 가 fleaMarket.filter 에도 존재",
      "spatialContext" in b["fleaMarket"]["filter"])
check("regionId 문자열", b["spatialContext"]["region"]["regionId"] == "6128")
check("coordinate type enum",
      b["spatialContext"]["userCoordinates"][0]["type"] == aps.COORD_TYPE)
check("1페이지는 pageToken 없음", "pageToken" not in b)
b2 = aps.build_body("샤넬가방", "6128", 37.498, 127.026, page_token="v2:abc")
check("페이징 키가 pageToken (nextToken 아님)",
      b2.get("pageToken") == "v2:abc" and "nextToken" not in b2)
docs = aps.documents({"results": [{"document": {"id": 1}}, {"payload": {}}]})
check("document 추출", docs == [{"id": 1}], str(docs))

# ── 4. 알림 파싱 ─────────────────────────────────────────────────
import notification_listener as nl  # noqa: E402

# 실기기(SM-N950N/Android 9) dumpsys 실측 포맷 그대로:
#  - 헤더 줄의 key= 뒤에 appImportanceLocked 가 공백 없이 붙는다
#  - when= 이 아예 없고 mCreationTimeMs 만 있다
DUMP = """
    NotificationRecord(0xabc: pkg=com.other user=UserHandle{0} id=1 tag=null key=0|com.other|1|null|100appImportanceLocked=false: Notification(channel=x))
      extras={
        android.title=String (다른앱)
        android.text=String (무시해야 함)
      }
    NotificationRecord(0xdef: pkg=com.towneers.www user=UserHandle{0} id=7 tag=null key=0|com.towneers.www|7|null|10123appImportanceLocked=false: Notification(channel=keyword))
      mCreationTimeMs=1787790428131(2026-08-27 12:00:00)
      key=0|com.towneers.www|7|null|10123
      contentIntent=PendingIntent{ab: PendingIntentRecord{cd com.towneers.www startActivity}}
      extras={
        android.title=String (샤넬가방 키워드 알림)
        android.text=String (샤넬 클래식 미디움 캐비어 정품)
        android.intent=Intent { dat=karrot://article/995077233 }
      }
"""
check("실제 패키지명(com.towneers.www)", nl.PKG == "com.towneers.www", nl.PKG)
recs = nl.parse(DUMP)
check("당근 알림만 파싱", len(recs) == 1, f"{len(recs)}건")
if recs:
    r = recs[0]
    check("제목 추출", r["title"] == "샤넬가방 키워드 알림", r["title"])
    check("본문(매물 제목) 추출",
          r["text"] == "샤넬 클래식 미디움 캐비어 정품", r["text"])
    check("딥링크 매물 id 추출", r.get("article_id") == "995077233",
          str(r.get("article_id")))
    check("key 는 독립 줄 우선(헤더 오염 배제)",
          r["key"] == "0|com.towneers.www|7|null|10123", str(r["key"]))
    check("when 없으면 mCreationTimeMs 로 대체",
          r["when"] == 1787790428131, str(r["when"]))
    check("지문 안정성", nl.fingerprint(r) == nl.fingerprint(dict(r)))
    r2 = dict(r, text="다른 매물")
    check("본문 다르면 다른 지문", nl.fingerprint(r) != nl.fingerprint(r2))

# ── 5. 매물 레코드 변환 ──────────────────────────────────────────
import alert_pipeline as apl  # noqa: E402

DOC = {"id": 995077233, "title": "샤넬 클래식 미디움 캐비어 정품 영수증",
       "content": "풀박스 상태 A급", "price": "5,500,000원", "status": "판매중",
       "regionName": "서초구 서초동", "watchesCount": 9, "chatRoomsCount": 3,
       "viewCount": 267, "createdAt": "2026-08-27T07:00:00Z",
       "publishedAt": "2026-08-27T08:00:00Z",
       "firstImage": {"url": "https://img/1440.jpg"}, "user": {}}
rec = apl.to_record(DOC, {"account": "acc1", "ts": 1.0})
check("브랜드 판정", rec["brand"] == "샤넬", str(rec.get("brand")))
check("가격 정수화", rec["price_num"] == 5500000, str(rec.get("price_num")))
check("찜 수 매핑", rec["watch_count"] == 9)
check("채팅 수 매핑(chatRoomsCount)", rec["chat_count"] == 3)
check("이미지 매핑", rec["images"] == ["https://img/1440.jpg"])
check("출처 표시", rec["source"] == "keyword_alert")
check("원본 raw 제거(용량)", "_raw" not in rec)
check("상세 링크 생성", str(DOC["id"]) in rec["href"], rec["href"])

blocked = apl.to_record({**DOC, "user": {"webCrawlNotAllowed": True}},
                        {"account": "acc1"})
check("크롤거부 판매자 플래그", blocked["crawl_blocked"] is True)

# ── 6. 상한 감지 ─────────────────────────────────────────────────
import setup_keyword_alerts as ska  # noqa: E402


def fake_resp(status, text):
    return types.SimpleNamespace(status_code=status, text=text)


check("상한 응답 감지(한글)",
      ska.is_cap_error(fake_resp(400, '{"message":"최대 30개까지 등록 가능합니다"}')))
check("상한 응답 감지(영문)",
      ska.is_cap_error(fake_resp(422, '{"error":"keyword limit exceeded"}')))
check("일반 4xx 는 상한 아님",
      not ska.is_cap_error(fake_resp(400, '{"error":"bad request"}')))
check("2xx 는 상한 아님", not ska.is_cap_error(fake_resp(200, "ok")))

# screened 산출물 두 형식(dict/list) 모두 로드되는지
_p = "/tmp/_selftest_kw.json"
json.dump({"ok": [{"keyword": "샤넬가방"}], "banned": [{"keyword": "X"}]},
          open(_p, "w", encoding="utf-8"))
check("screened dict 형식 로드(금지 키워드 제외)",
      ska.load_keywords(_p) == ["샤넬가방"], str(ska.load_keywords(_p)))
json.dump(["롤렉스시계"], open(_p, "w", encoding="utf-8"))
check("평문 리스트 형식 로드", ska.load_keywords(_p) == ["롤렉스시계"])
os.remove(_p)

# ── 결과 ────────────────────────────────────────────────────────
print()
if FAILED:
    print(f"실패 {len(FAILED)}건: {', '.join(FAILED)}")
    sys.exit(1)
print("전부 통과")

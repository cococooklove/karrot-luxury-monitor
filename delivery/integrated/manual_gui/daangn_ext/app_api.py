"""당근 앱 API 클라이언트 — 중고거래 검색.

웹 SSR 경로의 한계를 전부 없앤다:
  - 브랜드 키워드 억제 없음 (웹: '샤넬' 0건 / 앱: 1,198건+)
  - 페이지네이션 있음 (웹: ~285건 상한, 페이징 불가)
  - 반경 기반이라 인접 동이 자동으로 딸려온다

인증: authorization(JWT) + 디바이스 헤더. **서명/HMAC 없음** → 헤더 재현만으로 호출된다.
헤더 실값은 data/config.json (권한 0600, gitignore). 스펙은 docs/APP_API.md 참고.

주의 — pageToken:
  응답은 `nextToken` 으로 주지만 요청은 **`pageToken`** 으로 보내야 한다.
  `nextToken` 으로 보내면 에러 없이 1페이지가 재반환된다(조용한 중복).
  실측: 잘못된 이름으로 40페이지 순회 → 유니크 33건.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import time
from typing import Callable

from curl_cffi import requests

SEARCH_URL = "https://search-bff.kr.karrotmarket.com/api/v5/fleamarket/search"
COORD_TYPE = "USER_COORDINATE_TYPE_REGION_CENTER_COORDINATE"
PAGE_SIZE = 20              # 서버 고정
DEFAULT_CONFIG = "./data/config.json"

# 헤더가 없으면 호출 자체가 안 되는 것들
REQUIRED_HEADERS = ("authorization", "x-device-identity", "x-user-agent")

# ── 정렬(sortOption) ───────────────────────────────────────────────────────
# 상수 이름은 짧게, 실제 전송값은 서버 enum 문자열 그대로다.
# 값 목록은 추측이 아니라 서버 422 응답이 되돌려준 것(실측 2026-09-01).
SORT_UNSPECIFIED = "FLEA_MARKET_SORT_OPTION_UNSPECIFIED"
SORT_RELEVANT = "FLEA_MARKET_SORT_OPTION_RELEVANT"          # 서버 기본(관련도)
SORT_PRICE_ASC = "FLEA_MARKET_SORT_OPTION_PRICE_ASC"
SORT_PRICE_DESC = "FLEA_MARKET_SORT_OPTION_PRICE_DESC"
SORT_DISTANCE_ASC = "FLEA_MARKET_SORT_OPTION_DISTANCE_ASC"
SORT_RECENT = "FLEA_MARKET_SORT_OPTION_RECENT"              # publishedAt 내림차순

SORT_OPTIONS = (SORT_UNSPECIFIED, SORT_RELEVANT, SORT_PRICE_ASC,
                SORT_PRICE_DESC, SORT_DISTANCE_ASC, SORT_RECENT)

# stop_before 여유(초). 지정 시각에서 이만큼 **더 과거**까지 받아본 뒤 멈춘다.
#
# 300초(5분)인 근거:
#   - 우리 시계와 당근 서버 시계의 오차(보통 수 초~수십 초)
#   - 등록/끌올 → 검색 색인 반영 지연. 관측된 적은 없지만 분 단위까지는 가정해야
#     안전하다. 지연된 문서는 publishedAt 이 우리 '지난 방문 시각'보다 과거인 채로
#     방문 **뒤에** 색인되므로, 여유가 없으면 영구 유실된다(재시도해도 안 잡힌다).
#   - 비용은 거의 0 이다. 실측상 한 페이지(20건)가 20~25분 구간을 덮으므로
#     5분은 평균 1/4페이지 = 대부분의 경우 추가 요청 0회, 최악이어도 1회다.
#     반대로 부족하면 조용한 유실이라 비대칭이 크다 → 넉넉한 쪽으로 잡는다.
STOP_BEFORE_SLACK = 300.0


class TokenExpired(RuntimeError):
    """액세스 토큰 만료(401). 갱신 후 재시도해야 한다."""


class AppApiError(RuntimeError):
    """앱 API 호출 실패. `status` 는 HTTP 상태코드(전송단 오류면 None).

    상태코드를 **구조적으로** 들고 다니는 이유:
    호출측(app_source 의 IP 쿨다운 판단, adaptive 의 경고 dedup 키)이 예외
    메시지를 파싱해야 하는 걸 막는다. 메시지에는 응답본문·프록시 host:port 가
    섞여 지역·IP 마다 달라지므로, 문자열은 사람용으로만 두고 판단은 이 필드로 한다.
    RuntimeError 를 상속하므로 기존 `except RuntimeError` / 폴백 경로는 그대로 동작한다.
    """

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class AppApiConfig:
    """캡처에서 추출한 헤더 묶음. data/config.json 에서 읽는다."""

    def __init__(self, path: str = DEFAULT_CONFIG):
        self.path = path
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        self.headers = dict(raw.get("headers") or {})
        self.headers.setdefault("x-search-tab", "fleamarket")
        missing = [h for h in REQUIRED_HEADERS if h not in self.headers]
        if missing:
            raise ValueError(f"{path} 에 필수 헤더 없음: {missing} — 캡처를 다시 하세요")

    def set_access_token(self, token: str) -> None:
        """토큰 갱신 후 반영 + 파일에도 기록."""
        self.headers["authorization"] = token if token.lower().startswith("bearer ") \
            else f"Bearer {token}"
        raw = {"endpoint": SEARCH_URL, "headers": self.headers}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def token_expires_in(self) -> int:
        """액세스 토큰 잔여 초. 판단 불가면 -1."""
        import base64
        tok = (self.headers.get("authorization") or "").split()[-1]
        parts = tok.split(".")
        if len(parts) != 3:
            return -1
        try:
            pad = parts[1] + "=" * (-len(parts[1]) % 4)
            exp = json.loads(base64.urlsafe_b64decode(pad)).get("exp")
            return int(exp - time.time()) if exp else -1
        except Exception:
            return -1


def check_sort_option(sort_option: str | None) -> str | None:
    """허용값이 아니면 **호출 전에** ValueError. None 은 그대로 통과(서버 기본=관련도).

    서버 422 를 기다리지 않는 이유:
      - 422 한 번에 계정 쿼터 1회 + 토큰 왕복이 날아간다. 전국 순회 중이면
        6,537개 지역 × 레인 수만큼 반복된다.
      - 더 나쁜 건 **오타는 422 도 못 받는다**는 점이다. 서버는 `fleaMarket.sortOption`
        자리에 들어온 미지 enum 에만 422 를 주고, 자리가 틀리면 조용히 200 을 준다.
        즉 서버 검증에 기대면 '정렬이 걸린 줄 알았는데 관련도' 를 못 잡는다.
    """
    if sort_option is None:
        return None
    if sort_option not in SORT_OPTIONS:
        raise ValueError(
            f"알 수 없는 sortOption: {sort_option!r} — 허용값: {', '.join(SORT_OPTIONS)}")
    return sort_option


def to_epoch(v) -> float | None:
    """ISO8601 문자열 / datetime / epoch 숫자 → epoch 초(float). 판단 불가면 None.

    epoch 숫자도 받는 이유: 이 저장소는 시각을 epoch 로 들고 다니는 데가 많다
    (article_watch.parse_iso 반환값, watch DB 컬럼). 문자열만 받으면 호출측이
    매번 되돌려 만들어야 하고 그 변환에서 조용히 틀린다.

    tz 없는 값은 **로컬 시각**으로 본다(datetime.timestamp 기본과 동일).
    당근 응답의 publishedAt 은 'Z' 가 붙은 UTC 라 이 경로를 타지 않는다.
    """
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, _dt.datetime):
        return v.timestamp()
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        # 'Z' 는 파이썬 3.11 미만의 fromisoformat 이 못 읽는다. 서버가 항상 붙여 보내므로
        # 런타임 파이썬 버전에 결과가 좌우되지 않게 여기서 먼저 바꾼다.
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        try:
            return _dt.datetime.fromisoformat(s).timestamp()
        except ValueError:
            return None
    return None


def published_epoch(doc: dict) -> float | None:
    """문서의 publishedAt(끌올 시각) epoch. 없거나 못 읽으면 None.

    **createdAt 으로 대체하지 않는다.** RECENT 정렬은 publishedAt 기준으로만
    단조(실측 300건 위반 0건)이고 createdAt 은 정렬순서와 무관(54%가 역전)이다.
    createdAt 을 끼워 넣으면 정지 판단이 임의 값으로 내려진다.
    """
    return to_epoch((doc or {}).get("publishedAt"))


def _spatial(region_id: str, lat: float, lon: float) -> dict:
    return {
        "region": {"regionId": str(region_id)},
        "userCoordinates": [{
            "type": COORD_TYPE,
            "coordinate": {"latitude": lat, "longitude": lon},
        }],
    }


def build_body(keyword: str, region_id: str, lat: float, lon: float,
               page_token: str | None = None,
               without_completed: bool = True,
               sort_option: str | None = None) -> dict:
    """검색 요청 본문.

    spatialContext 를 **루트와 fleaMarket.filter 양쪽에** 넣어야 한다.
    하나라도 빠지면 422 (서버가 빠진 필드명을 그대로 알려준다).

    sortOption 자리는 **`fleaMarket` 바로 아래**다 — 루트도 아니고
    `fleaMarket.filter` 도 아니다. 다른 자리에 넣으면 서버가 조용히 무시하고
    200 을 준다(실측). 즉 자리 오류는 에러가 아니라 '정렬이 안 걸린 정상응답'으로
    보여서 눈으로는 못 잡는다 — 이 위치가 계약이다.

    sort_option=None 이면 키 자체를 넣지 않는다. 기존 본문과 바이트 단위로 같아야
    이번 변경이 기존 수집을 건드리지 않는다(회귀 방지).
    """
    check_sort_option(sort_option)
    flea: dict = {"filter": {
        "withoutCompleted": without_completed,
        "spatialContext": _spatial(region_id, lat, lon),
    }}
    if sort_option is not None:
        flea["sortOption"] = sort_option
    body = {
        "query": keyword,
        "fleaMarket": flea,
        "spatialContext": _spatial(region_id, lat, lon),
    }
    if page_token:
        body["pageToken"] = page_token      # ← nextToken 아님. 위 독스트링 참고
    return body


def _post(cfg: AppApiConfig, body: dict, timeout: int = 20, retries: int = 2,
          proxy: str | None = None):
    """검색 POST 1회(+재시도).

    proxy 는 웹 경로(robust.py)와 같은 **단수 문자열**이다. curl_cffi 0.16 의
    requests.post 는 proxy(str) 와 proxies(dict) 를 둘 다 받지만, 이 저장소는
    robust 가 sess.get(..., proxy=cur_proxy) 로 단수형을 쓰므로 그쪽에 맞춘다.
    None 이면 curl_cffi 기본값과 같아 직결로 나간다(예외 없음).
    """
    last = None
    last_status = None          # 마지막 실패의 HTTP 상태코드(전송단 오류면 None)
    for attempt in range(retries + 1):
        try:
            r = requests.post(SEARCH_URL, json=body, headers=cfg.headers,
                              impersonate="safari_ios", timeout=timeout,
                              proxy=proxy)
        except Exception as e:
            last, last_status = e, None
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 401:
            raise TokenExpired("액세스 토큰 만료 — 갱신 필요")
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(3 * (attempt + 1))
            last, last_status = RuntimeError(f"HTTP {r.status_code}"), r.status_code
            continue
        return r
    raise AppApiError(f"요청 실패: {last}", status=last_status)


def search_page(cfg: AppApiConfig, keyword: str, region_id: str,
                lat: float, lon: float, page_token: str | None = None,
                proxy: str | None = None,
                sort_option: str | None = None) -> tuple[list, str | None, bool]:
    """한 페이지. (문서 리스트, nextToken, hasNextPage). proxy=None 이면 직결.

    sort_option=None 이면 정렬 키를 아예 안 보낸다 = 종전과 동일(서버 기본 관련도).
    """
    body = build_body(keyword, region_id, lat, lon, page_token,
                      sort_option=sort_option)
    r = _post(cfg, body, proxy=proxy)
    if r.status_code != 200:
        raise AppApiError(f"HTTP {r.status_code}: {r.text[:200]}", status=r.status_code)
    j = r.json()
    docs = [it["document"] for it in j.get("results", [])
            if isinstance(it, dict) and it.get("document")]
    return docs, j.get("nextToken"), bool(j.get("hasNextPage"))


def collect(cfg: AppApiConfig, keyword: str, region_id: str,
            lat: float, lon: float,
            max_pages: int = 200,
            gap: float = 0.25,
            should_stop: Callable[[], bool] | None = None,
            proxy: str | None = None,
            sort_option: str | None = None,
            stop_before=None) -> tuple[dict, dict]:
    """한 지역 전량 수집. ({id: document}, stats).

    stats: pages, requests, stopped_by, proxy, sort_option
      stopped_by = 'end' | 'max_pages' | 'duplicate' | 'stopped' | 'token' | 'stop_before'

    proxy 는 이 지역 순회 **전체에 고정**한다. 웹 경로와 같은 이유로
    한 지역 안에서 IP 를 갈면 페이지 토큰 연속성이 깨질 수 있고,
    같은 IP 동시요청 회피는 상위(레인 샤딩)가 이미 보장한다.
    None 이면 직결.

    ── stop_before (증분 수집 정지 규칙) ────────────────────────────────
    "지난 방문 시각(ISO8601 문자열 / datetime / epoch 초)보다 오래된 게 나오면 멈춘다".
    SORT_RECENT 는 publishedAt 기준 **단조 내림차순**이므로(실측 15페이지 300건, 위반 0),
    첫 과거 항목이 나온 지점 뒤로는 전부 과거임이 보장된다. 그래서 이 정지는
    '적당히 이쯤이면 됐겠지' 하는 표본이 아니라 커버리지 **보장**이다 —
    max_pages 가 60이든 200이든 "얼마나 파야 충분한지 모른다"였던 문제가 사라진다.

    RECENT 가 아닌 정렬에 stop_before 가 오면 **ValueError 로 즉시 실패**시킨다.
    조용히 무시하지도, 적용하지도 않는 이유:
      - 적용하면 치명적이다. 관련도 정렬은 시각 순서가 없어서 앞쪽에 우연히 낀
        오래된 매물 하나가 그 뒤 신규 전부를 끊어버린다(조용한 유실).
      - 무시하면 안전하긴 하나(더 많이 긁을 뿐) 호출측은 "이 시각 이후는 전부 봤다"고
        믿는다. 그 오해가 다음 사이클의 stop_before 를 앞당겨 유실을 만든다.
      - 이건 런타임 상황이 아니라 **배선 실수**다. 배선 실수는 첫 호출에서 터져야지
        로그 한 줄로 흘러가면 안 된다(로그는 6,537지역 순회 중 묻힌다).

    여유(STOP_BEFORE_SLACK)만큼 더 과거까지 받아본다 — 근거는 상수 주석 참고.

    publishedAt 이 없거나 못 읽는 문서는 **버리지 않고 담되, 정지 판단도 안 시킨다**.
    버리면 유실이고(되찾을 경로가 없다), 정지시키면 이상 문서 하나가 페이지 뒤쪽
    정상 신규를 통째로 날린다. 담아두면 최악이 downstream 중복제거 한 번이다(id 기준).
    """
    check_sort_option(sort_option)
    threshold = None
    if stop_before is not None:
        if sort_option != SORT_RECENT:
            raise ValueError(
                f"stop_before 는 sort_option={SORT_RECENT} 에서만 쓸 수 있다 "
                f"(받은 값: {sort_option!r}). 관련도 정렬은 시각 단조가 아니라서 "
                "시각으로 끊으면 뒤쪽 신규를 통째로 잃는다.")
        threshold = to_epoch(stop_before)
        if threshold is None:
            raise ValueError(f"stop_before 를 시각으로 읽을 수 없다: {stop_before!r}")
        threshold -= STOP_BEFORE_SLACK

    seen: dict = {}
    token = None
    pages = 0
    why = "end"
    while pages < max_pages:
        if should_stop and should_stop():
            why = "stopped"
            break
        try:
            docs, token, has_next = search_page(cfg, keyword, region_id, lat, lon, token,
                                                proxy=proxy, sort_option=sort_option)
        except TokenExpired:
            why = "token"
            break
        pages += 1
        before = len(seen)
        hit_stop = False
        for d in docs:
            if threshold is not None:
                ts = published_epoch(d)
                # ts is None = publishedAt 없음/파싱불가 → 담되 멈추지 않는다(위 독스트링).
                if ts is not None and ts < threshold:
                    hit_stop = True
                    break               # 이 항목부터는 버린다(단조라 뒤도 전부 과거)
            if d.get("id"):
                seen[str(d["id"])] = d
        if hit_stop:
            why = "stop_before"
            break
        if not has_next or not token:
            why = "end"
            break
        if len(seen) == before:
            # 새 매물이 하나도 안 늘면 페이징이 헛도는 것(파라미터명 오류의 증상).
            why = "duplicate"
            break
        if gap:
            time.sleep(gap)
    else:
        why = "max_pages"
    return seen, {"pages": pages, "requests": pages, "stopped_by": why, "proxy": proxy,
                  # 무엇으로 정렬해 얻은 결과인지 결과에 박아둔다. 상위(app_source/
                  # sweep)가 'RECENT 로 stop_before 까지 봤다' 를 사후 확인할 수 있어야
                  # 커버리지 보장이 말로만 남지 않는다.
                  "sort_option": sort_option}


def status_str(v) -> str:
    """status 를 항상 'ongoing'/'reserved'/'closed' 같은 소문자 문자열로 만든다.

    당근은 같은 필드를 응답에 따라 문자열로도, {"type": "ONGOING"} 같은 객체로도
    준다. 객체를 그대로 흘리면 watch DB 쓰기가
    'Error binding parameter 6: type dict is not supported' 로 죽어 가격추적
    스윕이 통째로 실패한다(운영 서버 실측).
    """
    if isinstance(v, dict):
        for k in ("type", "status", "name", "value", "code"):
            got = v.get(k)
            if isinstance(got, str) and got:
                return got.strip().lower()
        return ""
    if isinstance(v, str):
        return v.strip().lower()
    return "" if v is None else str(v).strip().lower()


def to_article(doc: dict) -> dict:
    """앱 API document → 기존 파이프라인이 쓰는 매물 dict 로 정규화.

    웹 파서(parse_articles) 출력과 키를 맞춰 downstream(필터·중복제거·알림)을
    그대로 재사용한다.
    """
    img = doc.get("firstImage") or {}
    aid = str(doc.get("id", ""))
    return {
        "id": aid,
        "title": doc.get("title", ""),
        "content": doc.get("content", "") or "",
        "price": doc.get("price") or (doc.get("priceInfo") or {}).get("price") or "0",
        "thumbnail": img.get("url", ""),
        "href": f"https://www.daangn.com/kr/buy-sell/-{aid}/" if aid else "",
        "region": doc.get("regionName", ""),
        "boostedAt": doc.get("publishedAt") or doc.get("createdAt") or "",
        "createdAt": doc.get("createdAt") or "",
        # 응답에 따라 문자열이 아니라 {"type": "ONGOING"} 같은 객체로 온다.
        # 그대로 흘리면 watch DB 쓰기가 sqlite 바인딩 오류로 죽는다.
        "status": status_str(doc.get("status")),
        "category": doc.get("categoryId", ""),
        # 앱에만 있는 신호 — 시세·수요 판단에 쓴다
        "watchesCount": doc.get("watchesCount", 0),
        "chatRoomsCount": doc.get("chatRoomsCount", 0),
        "republishCount": doc.get("republishCount", 0),
    }

"""
차단 판정 — "지금 IP 가 막힌 건가?" 를 실제로 알 수 있게 하는 계층.

종전 robust 는 응답 **상태코드를 아예 보지 않았다**. 그래서 403(차단)·429(레이트리밋)·
5xx(서버오류)·당근 HTML 구조변경이 전부 "파싱 실패" 하나로 뭉뚱그려져,
운영자가 로그를 봐도 IP 가 막힌 건지 파서가 깨진 건지 구분할 수 없었다.

여기서 응답을 6가지로 분류하고, 각각에 다른 대응(쿨다운 길이·중단 여부)을 준다.

  OK          정상 매물 반환
  EMPTY       200 + 정상 HTML + 매물 0건 → 시점별 변동. 즉시 다음 IP (쿨다운 X)
  RATELIMIT   429 → 그 IP 레이트리밋. Retry-After 만큼(없으면 길게) 쿨다운
  BLOCKED     401/403/451 → 그 IP 차단. 길게 쿨다운
  CHALLENGE   200 인데 캡차/봇검증 페이지 → 차단과 동급 취급
  SERVER      5xx → 당근 쪽 문제. IP 잘못 아님. 짧게 쉬고 재시도
  PARSE       200 + 정상 응답인데 remixContext 없음 → **당근이 HTML 을 바꿨을 가능성**.
              IP 를 갈아도 안 풀린다. 여러 IP 에서 연속 PARSE 면 파서 점검 신호.
"""
from __future__ import annotations

import re

# 봇 검증/캡차 페이지 지문 (200 으로 오는 차단)
CHALLENGE_PAT = re.compile(
    r"(cf-browser-verification|cf_chl_|challenge-platform|/cdn-cgi/challenge"
    r"|recaptcha|hcaptcha|captcha|are you a human|비정상적인 접근|자동입력 방지)",
    re.I)

# 상태코드별 기본 쿨다운(초). RATELIMIT 은 Retry-After 가 있으면 그 값 우선.
COOLDOWN = {
    "RATELIMIT": 600.0,
    "BLOCKED": 1800.0,
    "CHALLENGE": 1800.0,
    "SERVER": 30.0,
    "ERROR": 120.0,      # 네트워크 예외(프록시 사망 등)
    "PARSE": 0.0,        # IP 문제 아님 → 쿨다운 무의미
    "EMPTY": 0.0,
}

# 이 분류는 IP 를 갈아도 소용없다 → 상위에서 조기중단 판단에 씀
NOT_IP_FAULT = {"PARSE", "SERVER"}


def retry_after_sec(headers) -> float | None:
    """Retry-After 헤더(초 또는 HTTP-date) → 초. 없거나 못 읽으면 None."""
    if not headers:
        return None
    v = None
    for k in ("retry-after", "Retry-After"):
        try:
            v = headers.get(k)
        except Exception:
            v = None
        if v:
            break
    if not v:
        return None
    try:
        return max(0.0, float(str(v).strip()))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone
        dt = parsedate_to_datetime(str(v))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
    except Exception:
        return None


def classify(status: int | None, html: str | None, articles: list | None,
             headers=None) -> tuple[str, float]:
    """(분류, 권장 쿨다운초) 반환.
    articles 는 parse_articles 결과 — 리스트면 파싱 성공, None 이면 실패."""
    if status is None:                          # 요청 자체가 예외
        return "ERROR", COOLDOWN["ERROR"]
    if status == 429:
        ra = retry_after_sec(headers)
        return "RATELIMIT", ra if ra else COOLDOWN["RATELIMIT"]
    if status in (401, 403, 451):
        return "BLOCKED", COOLDOWN["BLOCKED"]
    if 500 <= status < 600:
        return "SERVER", COOLDOWN["SERVER"]
    if html and CHALLENGE_PAT.search(html[:200_000]):
        return "CHALLENGE", COOLDOWN["CHALLENGE"]
    if articles is None:
        return "PARSE", COOLDOWN["PARSE"]
    if articles:
        return "OK", 0.0
    return "EMPTY", 0.0


def summarize(counts: dict) -> str:
    """분류 카운터 → 사람이 읽는 한 줄 진단."""
    if not counts:
        return "관측 없음"
    hard = counts.get("BLOCKED", 0) + counts.get("CHALLENGE", 0)
    if hard:
        return (f"IP 차단 감지 (BLOCKED/CHALLENGE {hard}회) — 해당 IP 는 쿨다운됨. "
                f"프록시 풀 교체 필요 여부 확인")
    if counts.get("RATELIMIT"):
        return (f"레이트리밋 {counts['RATELIMIT']}회 — 속도를 낮추거나 IP 풀을 늘려라 "
                f"(차단은 아님)")
    if counts.get("PARSE"):
        return (f"파싱 실패 {counts['PARSE']}회 — IP 문제 아님. 당근 HTML 구조변경 의심 "
                f"→ parse_articles 점검")
    if counts.get("SERVER"):
        return f"당근 서버 5xx {counts['SERVER']}회 — 우리 쪽 문제 아님. 잠시 후 재시도"
    if counts.get("EMPTY"):
        return f"빈응답 {counts['EMPTY']}회 — 정상 범주(시점별 변동). 재시도로 극복 대상"
    return "정상"

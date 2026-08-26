"""
헬스체크 — "지금 막힌 건가? 막혔으면 어디가?" 를 즉시 답하는 진단기.

수집이 안 될 때 원인은 4가지고, 대응이 전부 다르다:
  1. 특정 IP 만 차단      → 그 IP 만 빼면 됨 (풀이 살아있으면 계속 진행)
  2. 프록시 풀 전체 차단  → 풀 교체 필요 (같은 업체 대역이 통째로 막힌 경우)
  3. 당근 전면 변경/장애  → IP 를 아무리 갈아도 소용없음. 파서 점검 또는 대기
  4. 아무 문제 없음(빈응답) → 재시도로 극복되는 정상 범주

풀의 각 IP 를 1회씩 찔러 분류를 세고, 위 4가지 중 무엇인지 판정한다.
집(직결) IP 도 함께 찔러 "프록시만의 문제인지 당근 전체 문제인지" 를 가른다.

용법:
    from daangn_ext.health import health_check, print_report
    print_report(health_check(PROXIES))

  또는 CLI:
    python -m daangn_ext.health proxies.txt
"""
from __future__ import annotations

import time

from curl_cffi import requests

from . import proxy_budget
from .block_signals import classify
from .robust import BUYSELL, build_params, parse_articles

PROBE_KW = "구찌"
PROBE_REGION = "역삼동-6035"


def probe(proxy: str | None, keyword: str = PROBE_KW,
          region: str = PROBE_REGION, timeout: int = 10) -> dict:
    """IP 1개를 1회 찔러 분류. 요청 1건만 쓴다(재시도 없음)."""
    t = time.time()
    status = html = hdrs = None
    err = None
    try:
        sess = requests.Session(impersonate="chrome")
        r = sess.get(BUYSELL, params=build_params(keyword, region, True, None, None),
                     proxy=proxy, timeout=timeout)
        status, html, hdrs = r.status_code, r.text, r.headers
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:120]
    arts = parse_articles(html) if html is not None else None
    kind, cool = classify(status, html, arts, hdrs)
    return {"proxy": proxy, "kind": kind, "status": status,
            "articles": len(arts) if arts else 0,
            "cooldown": cool, "error": err, "sec": round(time.time() - t, 1)}


def health_check(proxies: list, include_direct: bool = True,
                 keyword: str = PROBE_KW, region: str = PROBE_REGION,
                 workers: int = 8, on_progress=None) -> dict:
    """풀 전체 + (옵션) 직결 IP 진단. 요청 수 = len(proxies) + 1.
    IP 마다 1건씩이라 **서로 다른 IP 간 병렬은 안전**하다(같은 IP 동시요청만 금지).
    20개 풀이 순차로는 2~3분 걸려 GUI 에서 못 쓴다 → 기본 8병렬.
    on_progress(done, total) 로 진행률을 받는다."""
    from concurrent.futures import ThreadPoolExecutor

    targets = list(proxies) + ([None] if include_direct else [])
    results: dict = {}
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(targets) or 1))) as ex:
        futs = {ex.submit(probe, t, keyword, region): t for t in targets}
        for f, t in futs.items():
            results[t] = f.result()
            done += 1
            if on_progress:
                on_progress(done, len(targets))
    rows = [results[p] for p in proxies]
    direct = results.get(None) if include_direct else None
    # 진단으로 밝혀진 차단 IP 는 곧바로 쿨다운시킨다 — 다음 수집이 그 IP 를 다시 태우지 않게.
    for r in rows:
        if r["kind"] in ("BLOCKED", "CHALLENGE", "RATELIMIT") and r["cooldown"]:
            proxy_budget.mark_exhausted(r["proxy"], r["cooldown"])

    counts: dict = {}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    n = len(rows) or 1
    hard = counts.get("BLOCKED", 0) + counts.get("CHALLENGE", 0) + counts.get("RATELIMIT", 0)
    parse_fail = counts.get("PARSE", 0)
    server = counts.get("SERVER", 0)
    alive = counts.get("OK", 0) + counts.get("EMPTY", 0)

    # ── 판정 ──
    if direct and direct["kind"] in ("BLOCKED", "CHALLENGE"):
        verdict, action = ("당근 전면 차단(직결 IP 도 막힘)",
                           "프록시 교체로 해결 안 됨. 수집 중단하고 시간을 두고 재시도")
    elif parse_fail >= max(2, n * 0.5) or (direct and direct["kind"] == "PARSE"):
        verdict, action = ("당근 HTML 구조 변경 의심",
                           "IP 문제 아님. parse_articles 의 remixContext 경로 점검 필요")
    elif server >= max(2, n * 0.5):
        verdict, action = ("당근 서버 장애(5xx)",
                           "우리 쪽 문제 아님. 잠시 후 재시도")
    elif hard >= n:
        verdict, action = ("프록시 풀 전체 차단",
                           "풀 통째로 교체 필요(같은 대역이 통째로 막혔을 가능성). "
                           "직결 IP 가 정상이면 프록시 업체 문제")
    elif hard:
        verdict, action = (f"일부 IP 차단 ({hard}/{n})",
                           "해당 IP 는 자동 쿨다운됨. 살아있는 IP 로 계속 진행 가능. "
                           f"가용 {alive}/{n} 이 부족하면 풀 보충")
    elif alive == 0:
        verdict, action = ("전 IP 응답 실패(네트워크/프록시 사망)",
                           "프록시 자격증명·엔드포인트 확인")
    else:
        verdict, action = (f"정상 (가용 {alive}/{n})",
                           "빈응답은 재시도로 극복되는 정상 범주")

    return {"rows": rows, "direct": direct, "counts": counts,
            "alive": alive, "total": n, "verdict": verdict, "action": action}


def print_report(res: dict) -> None:
    print(report_text(res))


def report_text(res: dict) -> str:
    """print_report 와 같은 내용을 문자열로 — GUI 팝업에서 재사용."""
    out = [f"{'IP':26s} {'분류':10s} {'HTTP':>5s} {'건수':>5s}  초"]
    for r in res["rows"]:
        host = (r["proxy"] or "직결").split("@")[-1]
        out.append(f"{host:26s} {r['kind']:10s} {str(r['status'] or '-'):>5s} "
                   f"{r['articles']:5d}  {r['sec']:.1f}"
                   + (f"  {r['error']}" if r["error"] else ""))
    d = res.get("direct")
    if d:
        out.append(f"{'(직결 IP)':26s} {d['kind']:10s} {str(d['status'] or '-'):>5s} "
                   f"{d['articles']:5d}  {d['sec']:.1f}")
    out += ["", f"분류: {res['counts']}", f"판정: {res['verdict']}", f"대응: {res['action']}"]
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "proxies.txt"
    pool = [l.strip() for l in open(path, encoding="utf-8") if l.strip()]
    print_report(health_check(pool))

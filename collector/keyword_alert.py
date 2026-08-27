"""키워드 알림 API 클라이언트 — 폴링을 푸시로 바꾸는 축.

확정된 것 (data/capture.jsonl 실측, 2026-08-27):
    GET https://search-bff.kr.karrotmarket.com/api/v1/fleamarket/keyword/notification/info?keyword=샤넬
    → {"keyword","isBannedKeyword","isRegistered","isNotificationBannedKeyword"}
    호스트가 search-bff = 검색과 동일 → 인증서 피닝 없음. 헤더 세트도 검색과 같다.

미확정(등록/목록/삭제)은 data/keyword_alert_endpoints.json 으로 주입한다.
캡처 후 `python3 -m collector.keyword_alert learn` 한 번 돌리면 자동으로 채워진다.
절차: docs/KEYWORD_ALERT_CAPTURE.md
"""
import json
import os
import random
import re
import sys
import time

import httpx

HOST = "search-bff.kr.karrotmarket.com"
SPEC_PATH = "data/keyword_alert_endpoints.json"
CONFIG_PATH = "data/config.json"
CAPTURE = "data/capture.jsonl"

DROP = {"content-length", "host", "connection", "accept-encoding"}

DEFAULT_SPEC = {
    "host": HOST,
    # 실측 확정
    "info": {"method": "GET",
             "path": "/api/v1/fleamarket/keyword/notification/info",
             "query_key": "keyword"},
    # 미확정 — 캡처 후 learn 으로 채움
    "list": {"method": "GET", "path": None, "query_key": None},
    "register": {"method": "POST", "path": None, "query_key": None,
                 "body_template": None},
    "unregister": {"method": "DELETE", "path": None, "query_key": "keyword",
                   "body_template": None},
    # 등록 가능 개수 상한. 캡처로 확인되면 숫자를 넣는다. None = 미확인
    "max_keywords": None,
}

# 알림 관련 경로 판별용
ALERT_PATH = re.compile(r"keyword.*(notification|alarm|alert)|"
                        r"(notification|alarm|alert).*keyword", re.I)


class EndpointUnknown(RuntimeError):
    """등록/목록/삭제 경로가 아직 캡처되지 않음."""


# ── 스펙 로드/저장 ────────────────────────────────────────────────

def load_spec(path=SPEC_PATH):
    spec = json.loads(json.dumps(DEFAULT_SPEC))  # deep copy
    if os.path.exists(path):
        saved = json.load(open(path, encoding="utf-8"))
        for k, v in saved.items():
            if isinstance(v, dict) and isinstance(spec.get(k), dict):
                spec[k].update(v)
            else:
                spec[k] = v
    return spec


def save_spec(spec, path=SPEC_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)
    os.chmod(path, 0o600)


def learn_from_capture(capture=CAPTURE, path=SPEC_PATH):
    """capture.jsonl 에서 알림 등록/목록/삭제 요청을 찾아 스펙에 채운다."""
    spec = load_spec(path)
    if not os.path.exists(capture):
        raise SystemExit(f"캡처 없음: {capture}")
    found = {}
    for line in open(capture, encoding="utf-8"):
        if not line.strip():
            continue
        d = json.loads(line)
        p = d.get("path") or ""
        if not ALERT_PATH.search(p):
            continue
        if d.get("method") == "OPTIONS":
            continue
        if not (d.get("status") and 200 <= d["status"] < 300):
            continue
        m = d["method"]
        if m == "POST":
            role = "register"
        elif m == "DELETE":
            role = "unregister"
        elif m == "GET":
            role = "info" if p.rstrip("/").endswith("info") else "list"
        else:
            continue
        found[role] = d

    for role, d in found.items():
        entry = spec.setdefault(role, {})
        entry["method"] = d["method"]
        entry["path"] = d["path"]
        q = d.get("query") or {}
        if q:
            entry["query_key"] = next((k for k in q if "keyword" in k.lower()),
                                      next(iter(q), None))
        body = d.get("req_body")
        if body:
            try:
                entry["body_template"] = json.loads(body)
            except Exception:
                entry["body_template"] = body
        spec["host"] = d.get("host", spec["host"])

    save_spec(spec, path)
    print(f"학습 완료 → {path}")
    for role in ("info", "list", "register", "unregister"):
        e = spec.get(role, {})
        mark = "OK " if e.get("path") else "미확정"
        print(f"  [{mark}] {role:11s} {e.get('method','')} {e.get('path') or '-'}")
    if not found:
        print("\n알림 요청이 캡처에 없음. docs/KEYWORD_ALERT_CAPTURE.md 절차 2번 수행.")
    return spec


# ── 클라이언트 ────────────────────────────────────────────────────

def load_headers(path=CONFIG_PATH):
    if not os.path.exists(path):
        raise SystemExit(f"{path} 없음 — tools/extract_token.py 로 생성")
    raw = json.load(open(path, encoding="utf-8"))
    h = raw.get("headers", raw)
    return {k: v for k, v in h.items() if k.lower() not in DROP}


class KeywordAlertClient:
    """단일 계정용. 다계정은 pool.WorkerPool 을 넘겨 쓴다(from_worker)."""

    def __init__(self, headers=None, proxy=None, spec=None,
                 min_gap=1.5, jitter=1.5):
        self.spec = spec or load_spec()
        self.host = self.spec["host"]
        self.headers = headers if headers is not None else load_headers()
        self.min_gap = min_gap
        self.jitter = jitter
        self._last = 0.0
        self._client = httpx.Client(http2=True, timeout=15, proxy=proxy)

    @classmethod
    def from_worker(cls, worker, spec=None):
        """pool.Worker 의 헤더·프록시를 그대로 쓰는 클라이언트."""
        worker.refresh_token()
        c = cls(headers=dict(worker.headers), proxy=worker.proxy, spec=spec)
        c._worker = worker
        return c

    def _gap(self):
        wait = self._last + self.min_gap - time.time()
        if wait > 0:
            time.sleep(wait)
        time.sleep(random.uniform(0, self.jitter))
        self._last = time.time()

    def _call(self, role, keyword=None, extra_body=None, params=None):
        e = self.spec.get(role) or {}
        if not e.get("path"):
            raise EndpointUnknown(
                f"'{role}' 경로 미확정. docs/KEYWORD_ALERT_CAPTURE.md 로 캡처 후 "
                f"`python3 -m collector.keyword_alert learn` 실행.")
        params = dict(params or {})
        if keyword is not None and e.get("query_key"):
            params[e["query_key"]] = keyword
        body = None
        tpl = e.get("body_template")
        if tpl is not None:
            if isinstance(tpl, dict):
                body = json.loads(json.dumps(tpl))
                _fill_keyword(body, keyword)
                if extra_body:
                    body.update(extra_body)
            else:
                body = tpl
        elif extra_body is not None:
            body = extra_body
        self._gap()
        url = f"https://{self.host}{e['path']}"
        content = (json.dumps(body, ensure_ascii=False).encode()
                   if isinstance(body, (dict, list)) else
                   (body.encode() if isinstance(body, str) else None))
        resp = self._client.request(e["method"], url, headers=self.headers,
                                    params=params or None, content=content)
        if getattr(self, "_worker", None):
            self._worker.note_result(resp.status_code)
        return resp

    # ── 확정 엔드포인트 ──
    def info(self, keyword):
        """{keyword,isBannedKeyword,isRegistered,isNotificationBannedKeyword}"""
        r = self._call("info", keyword=keyword)
        r.raise_for_status()
        return r.json()

    def registrable(self, keyword):
        """알림 등록이 가능한 키워드인지. (banned 면 False)"""
        d = self.info(keyword)
        return not (d.get("isBannedKeyword") or d.get("isNotificationBannedKeyword"))

    # ── 캡처 후 활성화 ──
    def list_keywords(self):
        r = self._call("list")
        r.raise_for_status()
        data = r.json()
        return _extract_keywords(data)

    def register(self, keyword, extra_body=None):
        r = self._call("register", keyword=keyword, extra_body=extra_body)
        return r

    def unregister(self, keyword):
        r = self._call("unregister", keyword=keyword)
        return r

    def close(self):
        self._client.close()


def _fill_keyword(obj, keyword):
    """body_template 안의 keyword 필드를 실제 값으로 치환(중첩 포함)."""
    if keyword is None:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                _fill_keyword(v, keyword)
            elif "keyword" in k.lower() and isinstance(v, str):
                obj[k] = keyword
    elif isinstance(obj, list):
        for v in obj:
            _fill_keyword(v, keyword)


def _extract_keywords(data):
    """목록 응답에서 키워드 문자열만 뽑는다(스키마 미확정 대비 관용 파싱)."""
    out = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if "keyword" in k.lower() and isinstance(v, str):
                    out.append(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    # 순서 유지 중복제거
    return list(dict.fromkeys(out))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "spec"
    if cmd == "learn":
        learn_from_capture()
    elif cmd == "spec":
        print(json.dumps(load_spec(), ensure_ascii=False, indent=2))
    elif cmd == "info":
        kw = sys.argv[2] if len(sys.argv) > 2 else "샤넬"
        c = KeywordAlertClient()
        print(json.dumps(c.info(kw), ensure_ascii=False))
        c.close()
    else:
        print(__doc__)

"""
다계정 × 다LD 워커 풀 — 안정성 #4(밴 분산) + #2(일 상한).

단일 계정/단일 기기로 대량 요청 = 즉시 밴. 이 풀이 요청을 여러
(계정+기기) 워커에 라운드로빈으로 흩고, 계정별 일 상한·요청간 쿨다운·
차단 감지 격리를 강제한다.

구성 파일: data/accounts.json
[
  {"name":"acc1","serial":"emulator-5554","app":"com.towneers.www",
   "headers_file":"data/headers_acc1.json","daily_cap":300},
  {"name":"acc2","serial":"emulator-5556","headers_file":"data/headers_acc2.json"}
]
headers_file = LD에서 추출한 토큰/디바이스/UA 헤더 dict (extract_token.py 산출 형식).

용법(코드):
  pool = WorkerPool.from_config()
  resp = pool.request("GET", "https://host/path", params={...})   # 워커 자동선택+서명
  pool.close()
"""
import json
import os
import random
import subprocess
import threading
import time

import httpx

CONFIG = "data/accounts.json"
DROP = {"content-length", "host", "connection", "accept-encoding"}


class Worker:
    def __init__(self, spec, use_frida=True):
        self.name = spec["name"]
        self.serial = spec.get("serial")
        self.app = spec.get("app", "com.towneers.www")
        self.base_cap = spec.get("daily_cap", 300)
        self.min_gap = spec.get("min_gap", 2.0)     # 요청간 최소 간격(초)
        self.jitter = spec.get("jitter", 2.5)
        # 워밍업(밴 원인 #4): 신규/복원 계정은 첫날부터 대량 금지. warmup_days 동안 선형 램프.
        self.warmup_days = spec.get("warmup_days", 3)
        self.first_day = spec.get("first_day")      # "YYYYMMDD" 최초가동일. 없으면 오늘로 각인
        # 앱토큰 갱신(밴 원인 #3): HTTP refresh 금지, 앱저장소 토큰을 읽어 헤더 주입
        self.token_key = spec.get("token_key")      # read_app_token 로 찾은 prefs 키
        self.token_header = spec.get("token_header", "authorization")
        self.token_prefix = spec.get("token_prefix", "Bearer ")
        self.token_ttl = spec.get("token_ttl", 300) # 이 초 지나면 재읽기
        self._token_at = 0.0
        self.headers = self._load_headers(spec.get("headers_file"))
        # 인스턴스별 주거/모바일 프록시 (밴 원인 #4: 데이터센터IP/공유IP 회피). 1워커=1IP 원칙.
        self.proxy = spec.get("proxy")           # 예 "http://user:pass@host:port"
        self.client = httpx.Client(http2=True, timeout=15, proxy=self.proxy)
        self.signer = None
        if use_frida:
            from frida_supervisor import FridaSigner
            self.signer = FridaSigner(serial=self.serial, app=self.app)
        # 상태
        self.count = 0               # 오늘 사용량
        self.day = time.strftime("%Y%m%d")
        self.last_used = 0.0
        self.quarantine_until = 0.0
        self.block_streak = 0

    def _load_headers(self, path):
        if not path or not os.path.exists(path):
            return {}
        raw = json.load(open(path, encoding="utf-8"))
        h = raw.get("headers", raw)   # extract_token.py 는 {"headers":{...}} 형식
        return {k: v for k, v in h.items() if k.lower() not in DROP}

    def _roll_day(self):
        today = time.strftime("%Y%m%d")
        if today != self.day:
            self.day, self.count = today, 0

    def effective_cap(self):
        """워밍업 램프: 가동 d일차면 base_cap * min(d, warmup)/warmup."""
        if not self.first_day:
            self.first_day = time.strftime("%Y%m%d")
        try:
            from datetime import datetime
            d0 = datetime.strptime(self.first_day, "%Y%m%d")
            dn = datetime.strptime(time.strftime("%Y%m%d"), "%Y%m%d")
            day_idx = (dn - d0).days + 1
        except Exception:
            day_idx = self.warmup_days
        w = max(1, self.warmup_days)
        return max(1, int(self.base_cap * min(day_idx, w) / w))

    def available(self, now):
        self._roll_day()
        return (now >= self.quarantine_until) and (self.count < self.effective_cap())

    def refresh_token(self):
        """앱 저장소에서 최신 토큰 읽어 헤더 갱신(TTL 경과 시). HTTP refresh 안 함."""
        if not self.token_key or (time.time() - self._token_at) < self.token_ttl:
            return
        try:
            out = subprocess.run(
                ["python3", "tools/read_app_token.py",
                 "--serial", self.serial, "--key", self.token_key],
                capture_output=True, text=True, timeout=30)
            tok = out.stdout.strip()
            if tok and tok != "(없음)":
                self.headers[self.token_header] = self.token_prefix + tok
                self._token_at = time.time()
        except Exception as e:
            print(f"[pool] {self.name} 토큰 재읽기 실패: {e}")

    def ready_at(self):
        """다음 요청 가능 시각 (min_gap 반영)."""
        return max(self.last_used + self.min_gap, self.quarantine_until)

    def sign_headers(self, method, url, body=""):
        h = dict(self.headers)
        if self.signer:
            payload = json.dumps({"method": method, "url": url, "body": body},
                                 sort_keys=True)
            # 실제 서명 헤더명은 analyze_capture 의 [매번 변함] 결과로 교체
            h["x-signature"] = self.signer.sign(payload)
        return h

    def note_result(self, status):
        self.count += 1
        self.last_used = time.time()
        if status in (401, 403, 429):
            self.block_streak += 1
            # 격리: 연속 차단일수록 길게 (2^n 분, 상한 30분)
            cool = min(60 * (2 ** self.block_streak), 1800)
            self.quarantine_until = time.time() + cool
            print(f"[pool] {self.name} 차단 {status} → {cool/60:.0f}분 격리 "
                  f"(streak {self.block_streak})")
        else:
            self.block_streak = 0

    def close(self):
        self.client.close()
        if self.signer:
            self.signer.close()


class WorkerPool:
    def __init__(self, workers):
        if not workers:
            raise SystemExit("워커 0개 — data/accounts.json 확인")
        self.workers = workers
        self._lock = threading.Lock()

    @classmethod
    def from_config(cls, path=CONFIG, use_frida=True):
        if not os.path.exists(path):
            raise SystemExit(f"{path} 없음 — 계정 구성 필요")
        specs = json.load(open(path, encoding="utf-8"))
        return cls([Worker(s, use_frida=use_frida) for s in specs])

    def _pick(self):
        """가용 워커 중 '다음 준비 시각' 가장 이른 것 선택. 없으면 대기시간 반환."""
        with self._lock:
            now = time.time()
            avail = [w for w in self.workers if w.available(now)]
            if not avail:
                # 전원 소진(일상한) or 전원 격리
                soonest = min((w.quarantine_until for w in self.workers), default=now + 60)
                if all(w.count >= w.effective_cap() for w in self.workers):
                    raise SystemExit("[pool] 전 계정 일 상한 도달 — 내일 재개 or 계정 추가")
                return None, max(soonest - now, 1.0)
            w = min(avail, key=lambda x: x.ready_at())
            wait = max(w.ready_at() - now, 0.0)
            return w, wait

    def request(self, method, url, params=None, body=""):
        """워커 자동선택 → (쿨다운 대기) → 서명 → 요청 → 결과기록. httpx.Response 반환."""
        while True:
            w, wait = self._pick()
            if w is None:
                print(f"[pool] 전원 대기중 — {wait:.0f}s 후 재시도")
                time.sleep(min(wait, 60))
                continue
            if wait > 0:
                time.sleep(wait + random.uniform(0, w.jitter))
            w.refresh_token()                       # 앱토큰 최신화(#3)
            headers = w.sign_headers(method, url, body)
            try:
                resp = w.client.request(method, url, headers=headers,
                                        params=params, content=body or None)
            except Exception as e:
                w.note_result(0)
                print(f"[pool] {w.name} 요청 예외: {e}")
                continue
            w.note_result(resp.status_code)
            if resp.status_code in (401, 403, 429):
                # 격리됐으니 다른 워커로 자동 재시도
                continue
            return resp

    def stats(self):
        now = time.time()
        return [{"name": w.name, "used": w.count, "cap": w.effective_cap(),
                 "quarantined": now < w.quarantine_until,
                 "healthy": (w.signer.healthy() if w.signer else True)}
                for w in self.workers]

    def close(self):
        for w in self.workers:
            w.close()


if __name__ == "__main__":
    # 구성 검증(서명기 없이 로직만): accounts.json 로드 + 스케줄 확인
    pool = WorkerPool.from_config(use_frida=False)
    print("워커:", [w.name for w in pool.workers])
    for row in pool.stats():
        print(" ", row)
    pool.close()

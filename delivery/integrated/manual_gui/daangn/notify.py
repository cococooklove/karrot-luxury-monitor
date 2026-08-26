"""알림 송신기 — 텔레그램 / 구글시트.

설계 이유:
  - 실패를 절대 무음으로 두지 않는다. 401(토큰오류)/400(chat_id오류)/429(레이트리밋)는
    예외가 아니라 HTTP 응답으로 오므로 status_code 를 직접 해석해야 한다.
  - 전국 첫 바퀴는 신규 매물이 수천 건. 1건 1메시지면 텔레그램 레이트리밋(429)에
    바로 걸린다 → enqueue/flush 로 묶어 보낸다(메시지당 최대 3900자).
  - 구글시트도 동일. append_row(1행 1콜) → append_rows(N행 1콜).
"""
import json
import os
import time

TG_API = "https://api.telegram.org/bot{token}/sendMessage"
TG_MAX_CHARS = 3900          # 텔레그램 본문 한도 4096 - 여유
TG_MIN_INTERVAL = 3.0        # 같은 방 연속 전송 최소 간격(초). 그룹 한도 ~20msg/min
TG_QUEUE_SOFT_CAP = 40       # 큐가 이만큼 쌓이면 호출측 flush 안 기다리고 자동 전송

_TG_HINT = {
    400: "chat_id 가 잘못됐거나 메시지 형식 오류",
    401: "봇 토큰이 잘못됨",
    403: "봇이 차단됐거나 방에 없음 — 봇에게 /start 또는 방에 초대 필요",
    404: "토큰 형식 오류 (숫자:문자 형태여야 함)",
}


def _sleep_stoppable(sec, should_stop):
    """중지 요청 시 즉시 깨어나는 sleep."""
    end = time.monotonic() + sec
    while not should_stop():
        left = end - time.monotonic()
        if left <= 0:
            return True
        time.sleep(min(0.2, left))
    return False


class TelegramSender:
    def __init__(self, token, chat, log=None, should_stop=None,
                 min_interval=TG_MIN_INTERVAL):
        self.token = (token or "").strip()
        self.chat = (chat or "").strip()
        self.min_interval = min_interval
        self._log = log or (lambda m: None)
        self.should_stop = should_stop or (lambda: False)
        self._q = []
        self._last_sent = 0.0
        self._fail_total = 0
        self._sent_total = 0

    @property
    def enabled(self):
        return bool(self.token and self.chat)

    # ── 큐 ──
    def enqueue(self, text):
        """전송 대기열에 넣는다. 미설정이면 조용히 버림(설정 자체가 선택)."""
        if not self.enabled:
            return
        self._q.append(str(text))
        if len(self._q) >= TG_QUEUE_SOFT_CAP:
            self.flush()

    def pending(self):
        return len(self._q)

    def _chunks(self):
        """대기열 → 3900자 이하 묶음. 단건이 한도를 넘으면 잘라 보낸다."""
        chunk = ""
        while self._q:
            msg = self._q.pop(0)
            while len(msg) > TG_MAX_CHARS:
                if chunk:
                    yield chunk
                    chunk = ""
                yield msg[:TG_MAX_CHARS]
                msg = msg[TG_MAX_CHARS:]
            if not chunk:
                chunk = msg
            elif len(chunk) + 2 + len(msg) <= TG_MAX_CHARS:
                chunk += "\n\n" + msg
            else:
                yield chunk
                chunk = msg
        if chunk:
            yield chunk

    def flush(self, deadline=None, ignore_stop=False):
        """대기열 전부 전송. (성공묶음수, 실패묶음수) 반환.

        deadline: time.monotonic() 기준 마감. 넘기면 남은 건 로그 남기고 포기
                  (종료 시 무한정 붙잡히지 않게).
        ignore_stop: 종료 직전 마지막 전송용 — 중지 플래그를 무시한다.
        """
        if not self._q:
            return 0, 0
        if not self.enabled:
            self._q.clear()
            return 0, 0
        prev_stop = self.should_stop
        if ignore_stop:
            self.should_stop = lambda: False
        sent = failed = 0
        try:
            for chunk in self._chunks():
                if self.should_stop() or (deadline and time.monotonic() > deadline):
                    self._q.insert(0, chunk)
                    self._log(f"[텔레그램] 시간 초과로 {len(self._q)}건 미전송 (다음 사이클에 재전송)")
                    break
                ok, err = self.send(chunk)
                if ok:
                    sent += 1
                else:
                    failed += 1
                    self._report_failure(err)
        finally:
            self.should_stop = prev_stop
        return sent, failed

    # ── 전송 ──
    def _pace(self):
        gap = self.min_interval - (time.monotonic() - self._last_sent)
        if gap > 0:
            _sleep_stoppable(gap, self.should_stop)

    def _post(self, text, timeout=10):
        from curl_cffi import requests
        return requests.post(
            TG_API.format(token=self.token),
            json={"chat_id": self.chat, "text": text,
                  "disable_web_page_preview": True},
            impersonate="chrome", timeout=timeout)

    @staticmethod
    def _interpret(resp):
        """(성공여부, 오류문구, 재시도대기초) — 429 는 retry_after 를 그대로 쓴다."""
        try:
            body = resp.json()
        except Exception:
            body = {}
        if resp.status_code == 200 and body.get("ok"):
            return True, "", None
        desc = body.get("description") or str(getattr(resp, "text", ""))[:200]
        code = resp.status_code
        if code == 429:
            wait = (body.get("parameters") or {}).get("retry_after") or 5
            try:
                wait = float(wait)
            except (TypeError, ValueError):
                wait = 5.0
            return False, f"429 레이트리밋 (retry_after={wait:.0f}s): {desc}", wait
        hint = _TG_HINT.get(code, "")
        return False, f"{code} {desc}" + (f" — {hint}" if hint else ""), None

    def send(self, text, retries=2):
        """단건 전송. (성공여부, 오류문구). 429/5xx/네트워크는 재시도."""
        if not self.enabled:
            return False, "텔레그램 미설정 (토큰/방 비어있음)"
        err = "알 수 없는 오류"
        for attempt in range(retries + 1):
            self._pace()
            try:
                resp = self._post(text)
            except Exception as e:
                err = f"네트워크 오류: {type(e).__name__}: {e}"
                if attempt < retries and _sleep_stoppable(2 * (attempt + 1), self.should_stop):
                    continue
                break
            self._last_sent = time.monotonic()
            ok, err, wait = self._interpret(resp)
            if ok:
                self._sent_total += 1
                return True, ""
            if wait is not None and attempt < retries:
                if _sleep_stoppable(wait, self.should_stop):
                    continue
                break
            if resp.status_code >= 500 and attempt < retries:
                if _sleep_stoppable(2 * (attempt + 1), self.should_stop):
                    continue
                break
            break
        self._fail_total += 1
        return False, err

    def _report_failure(self, err):
        """첫 3회는 항상, 이후 20회마다 로그 — 무음도 도배도 안 되게."""
        n = self._fail_total
        if n <= 3 or n % 20 == 0:
            self._log(f"[텔레그램 실패 #{n}] {err}")

    def verify(self):
        """설정 테스트용 — 실제 1건 발송. (성공여부, 사람이 읽을 메시지)."""
        if not self.token:
            return False, "봇 토큰이 비어 있음"
        if not self.chat:
            return False, "chat_id(방)가 비어 있음"
        ok, err = self.send("✅ 당근 모니터 알림 테스트 — 이 메시지가 보이면 설정 정상입니다.",
                            retries=1)
        return (True, "텔레그램 전송 성공") if ok else (False, err)


class SheetWriter:
    def __init__(self, url, cred="./credentials.json", log=None):
        self.url = (url or "").strip()
        self.cred = (cred or "./credentials.json").strip()
        self._log = log or (lambda m: None)
        self._sheet = None       # None=미시도, False=사용불가, 그 외=워크시트
        self._rows = []
        self._fail_total = 0

    @property
    def enabled(self):
        return bool(self.url)

    def _cred_email(self):
        try:
            with open(self.cred, encoding="utf-8") as f:
                return json.load(f).get("client_email", "(client_email 없음)")
        except Exception:
            return "(인증파일 확인 불가)"

    def _connect(self):
        """(워크시트|None, 오류문구)."""
        if not self.url:
            return None, "구글시트 주소 미입력 (선택 기능)"
        try:
            import gspread
        except ImportError:
            return None, "gspread 미설치 — pip install gspread"
        if not os.path.exists(self.cred):
            return None, (f"서비스계정 인증파일 없음: {os.path.abspath(self.cred)} "
                          "(구글클라우드 서비스계정 JSON 키를 지정하세요)")
        try:
            gc = gspread.service_account(filename=self.cred)
            return gc.open_by_url(self.url).sheet1, ""
        except Exception as e:
            name = type(e).__name__
            msg = str(e)
            low = (name + " " + msg).lower()
            if "notfound" in low or "permission" in low or "403" in low:
                return None, (f"시트 접근 거부 — 시트를 서비스계정({self._cred_email()})과 "
                              "'편집자'로 공유했는지 확인")
            if "novalidurlkey" in low:
                return None, "구글시트 주소 형식이 잘못됨"
            return None, f"{name}: {msg[:200]}"

    def _client(self):
        if self._sheet is not None:
            return self._sheet
        sh, err = self._connect()
        if sh is None:
            self._sheet = False
            self._log(f"[구글시트 미연결] {err} (텔레그램만 사용)")
        else:
            self._sheet = sh
        return self._sheet

    # ── 큐 ──
    def enqueue_row(self, row):
        if not self.enabled:
            return
        self._rows.append([str(x) for x in row])

    def pending(self):
        return len(self._rows)

    def flush(self):
        """대기 행 일괄 append. (기록행수, 실패행수)."""
        if not self._rows:
            return 0, 0
        sh = self._client()
        if not sh:
            n = len(self._rows)
            self._rows.clear()
            return 0, n
        rows, self._rows = self._rows, []
        for attempt in range(3):
            try:
                sh.append_rows(rows, value_input_option="USER_ENTERED")
                return len(rows), 0
            except Exception as e:
                msg = str(e)
                if "429" in msg or "quota" in msg.lower():
                    time.sleep(5 * (attempt + 1))
                    continue
                self._fail_total += 1
                if self._fail_total <= 3 or self._fail_total % 20 == 0:
                    self._log(f"[시트 오류 #{self._fail_total}] {type(e).__name__}: {msg[:200]}")
                return 0, len(rows)
        self._fail_total += 1
        self._log(f"[시트 오류 #{self._fail_total}] 쿼터 초과로 {len(rows)}행 기록 실패")
        return 0, len(rows)

    def verify(self):
        """설정 테스트용 — 연결만 확인(행은 쓰지 않음)."""
        sh, err = self._connect()
        if sh is None:
            return False, err
        try:
            return True, f"연결됨: {sh.spreadsheet.title} / {sh.title}"
        except Exception:
            return True, "연결됨"


def run_test(tg_token, tg_chat, sheet_url, sheet_cred):
    """알림 설정 테스트 1회 — GUI 테스트 버튼용. dict 반환."""
    tg = TelegramSender(tg_token, tg_chat, min_interval=0.0)
    tg_ok, tg_msg = tg.verify()
    sh = SheetWriter(sheet_url, sheet_cred)
    if sh.enabled:
        sh_ok, sh_msg = sh.verify()
    else:
        sh_ok, sh_msg = None, "미설정 (선택 기능)"
    return {"tg_ok": tg_ok, "tg_msg": tg_msg, "sheet_ok": sh_ok, "sheet_msg": sh_msg}

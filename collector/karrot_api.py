"""
공유 클라이언트 — 캡처 성공요청을 템플릿으로 헤더 재현 + (옵션) Frida 동적서명 + 레이트 제한.
collect_listings.py / monitor.py 가 이걸 사용.

정적 경로: 캡처 헤더 그대로 실어 요청.
동적 경로: KARROT_FRIDA=1 이면 frida 로 sign_hook 붙여 요청마다 서명.
"""
import json
import os
import random
import time
import httpx

CAP = "data/capture.jsonl"
DROP = {"content-length", "host", "connection", "accept-encoding"}


def _load_template(path):
    tpl = None
    try:
        cap = open(CAP, encoding="utf-8")
    except FileNotFoundError:
        raise SystemExit(f"{CAP} 없음. 먼저 캡처하라 (SETUP_LDPLAYER.md).")
    with cap as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r["path"] == path and r["status"] and 200 <= r["status"] < 300:
                tpl = r
    if not tpl:
        raise SystemExit(f"성공 요청 템플릿 없음: {path}")
    return tpl


class KarrotClient:
    def __init__(self, path, min_delay=1.5, max_delay=4.0):
        self.tpl = _load_template(path)
        self.headers = {k: v for k, v in self.tpl["req_headers"].items()
                        if k.lower() not in DROP}
        self.host = self.tpl["host"]
        self.method = self.tpl["method"]
        self.path = self.tpl["path"]
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._client = httpx.Client(http2=True, timeout=15)
        self._frida = None
        if os.environ.get("KARROT_FRIDA") == "1":
            self._attach_frida()

    def _attach_frida(self):
        import frida  # 동적서명 경로에서만 필요
        app = os.environ.get("KARROT_APP", "com.towneers.www")
        dev = frida.get_usb_device()
        pid = dev.attach(app)
        with open("capture/frida/sign_hook.js", encoding="utf-8") as f:
            self._frida = pid.create_script(f.read())
        self._frida.load()
        print("[karrot] frida sign hook attached")

    def _sign(self, params, body):
        if not self._frida:
            return self.headers
        payload = json.dumps({"params": params, "body": body}, sort_keys=True)
        exp = getattr(self._frida, "exports_sync", None) or self._frida.exports
        sig = exp.sign(payload)
        h = dict(self.headers)
        h["x-signature"] = sig  # 실제 서명 헤더명은 diff 로 확인 후 교체
        return h

    def request(self, params=None, path=None):
        params = params or dict(self.tpl.get("query", {}))
        headers = self._sign(params, self.tpl.get("req_body", ""))
        url = f"https://{self.host}{path or self.path}"
        resp = self._client.request(self.method, url, headers=headers, params=params)
        # 사람 유사 랜덤 지연 (패턴 차단 회피)
        time.sleep(random.uniform(self.min_delay, self.max_delay))
        return resp

    def close(self):
        self._client.close()

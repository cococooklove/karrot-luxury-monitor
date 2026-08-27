"""
Frida 서명 사이드카 감독기 — 안정성 #3(자동복구).

토큰 경로의 단일 실패점 = Frida 세션. 앱 크래시/detach/기기 리부트 시
수집 전체가 죽는다. 이 감독기가 그걸 자가복구한다.

기능:
  - attach 실패/detach → 지수 백오프 재시도
  - N회 연속 실패 → adb 로 앱 강제 재시작 후 재attach
  - sign() 스레드세이프. 서명 실패 시 1회 자동 재attach 후 재시도
  - 헬스체크: 마지막 성공 서명 이후 경과 시간 노출

용법(단독 데몬):
  python collector/frida_supervisor.py --serial emulator-5554 --app com.towneers.www
용법(코드):
  s = FridaSigner(serial="emulator-5554"); sig = s.sign(payload)
karrot_api 는 이 FridaSigner.sign 을 주입받아 요청마다 호출.
"""
import argparse
import subprocess
import threading
import time

SCRIPT = "capture/frida/sign_hook.js"
DEFAULT_APP = "com.towneers.www"


class FridaSigner:
    def __init__(self, serial=None, app=DEFAULT_APP, script_path=SCRIPT,
                 max_backoff=30.0, restart_after=3):
        self.serial = serial          # adb 기기 시리얼 (다기기 풀에서 필수)
        self.app = app
        self.script_path = script_path
        self.max_backoff = max_backoff
        self.restart_after = restart_after   # 연속 실패 이 횟수면 앱 재시작
        self._lock = threading.RLock()
        self._script = None
        self._session = None
        self._device = None
        self._fail_streak = 0
        self.last_ok = 0.0
        self._attach()

    # ── 기기 핸들 ──────────────────────────────────────────
    def _get_device(self):
        import frida
        if self.serial:
            return frida.get_device(self.serial, timeout=10)
        return frida.get_usb_device(timeout=10)

    def _adb(self, *args):
        cmd = ["adb"]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += list(args)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    def _restart_app(self):
        print(f"[frida] 앱 재시작 {self.app} @ {self.serial or 'usb'}")
        self._adb("shell", "am", "force-stop", self.app)
        time.sleep(1.5)
        self._adb("shell", "monkey", "-p", self.app, "-c",
                  "android.intent.category.LAUNCHER", "1")
        time.sleep(4.0)   # 스플래시/초기화 대기

    # ── attach & 복구 ─────────────────────────────────────
    def _attach(self):
        with self._lock:
            self._detach_quiet()
            self._device = self._get_device()
            # spawn 대신 attach: 이미 로그인된 앱 세션 재사용 (토큰 유지)
            self._session = self._device.attach(self.app)
            self._session.on("detached", self._on_detached)
            with open(self.script_path, encoding="utf-8") as f:
                self._script = self._session.create_script(f.read())
            self._script.load()
            print(f"[frida] attached {self.app} @ {self.serial or 'usb'}")

    def _detach_quiet(self):
        for obj in (self._script, self._session):
            try:
                if obj:
                    obj.unload() if obj is self._script else obj.detach()
            except Exception:
                pass
        self._script = self._session = None

    def _on_detached(self, reason, *_):
        print(f"[frida] detached: {reason} — 복구 예약")
        self._script = None   # 다음 sign 이 재attach 트리거

    def _recover(self):
        """지수 백오프 재attach. restart_after 회 실패마다 앱 재시작."""
        delay, attempt = 1.0, 0
        while True:
            attempt += 1
            try:
                if attempt > 1 and (attempt - 1) % self.restart_after == 0:
                    self._restart_app()
                self._attach()
                return
            except Exception as e:
                print(f"[frida] 복구 실패 {attempt}회: {e} — {delay:.0f}s 후 재시도")
                time.sleep(delay)
                delay = min(delay * 2, self.max_backoff)

    # ── 공개 API ──────────────────────────────────────────
    def sign(self, payload):
        """서명 문자열 반환. 실패 시 1회 재attach 후 재시도, 그래도 실패면 예외."""
        with self._lock:
            for _try in range(2):
                if self._script is None:
                    self._recover()
                try:
                    exp = getattr(self._script, "exports_sync", None) or self._script.exports
                    sig = exp.sign(payload)
                    self._fail_streak = 0
                    self.last_ok = time.time()
                    return sig
                except Exception as e:
                    self._fail_streak += 1
                    print(f"[frida] sign 실패({self._fail_streak}): {e} — 재attach")
                    self._script = None
            raise RuntimeError("frida sign 2회 연속 실패 — 기기/앱 점검 필요")

    def healthy(self, max_idle=120):
        return self._script is not None and (time.time() - self.last_ok) < max_idle

    def close(self):
        with self._lock:
            self._detach_quiet()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", default=None, help="adb 기기 시리얼 (다기기면 필수)")
    ap.add_argument("--app", default=DEFAULT_APP)
    ap.add_argument("--probe", action="store_true", help="10초마다 테스트 서명 호출")
    args = ap.parse_args()

    signer = FridaSigner(serial=args.serial, app=args.app)
    print("[frida] signer 기동. Ctrl+C 종료.")
    try:
        while True:
            if args.probe:
                try:
                    sig = signer.sign('{"probe":1}')
                    print(f"[frida] probe ok: {str(sig)[:40]} | healthy={signer.healthy()}")
                except Exception as e:
                    print(f"[frida] probe 실패: {e}")
            time.sleep(10)
    except KeyboardInterrupt:
        signer.close()
        print("종료.")


if __name__ == "__main__":
    main()

import threading
import time

from daangn.errors import DaangnCancelledError


class ProxyManager:
    def __init__(
        self,
        proxies: list[str],
        min_delay_ms: int = 1000,
    ):
        # 실행 중 UI 에서 원본 리스트가 바뀌어도 안전하도록 복사본 사용
        self.proxies = list(proxies)
        self.min_delay_ms = min_delay_ms

        self.last_req = {proxy: 0.0 for proxy in proxies}
        self.cooldown_until = {proxy: 0.0 for proxy in proxies}

        self.idx = 0
        self.lock = threading.Lock()
        self._min_delay_sec = self.min_delay_ms / 1000.0

    def _next_proxy(self) -> str:
        proxy = self.proxies[self.idx]
        self.idx = (self.idx + 1) % len(self.proxies)
        return proxy

    def acquire(self, ev: threading.Event) -> str:
        if not self.proxies:
            raise RuntimeError("No proxies are configured")

        with self.lock:
            while True:
                now = time.time()
                next_wait = None

                for _ in range(len(self.proxies)):
                    proxy = self._next_proxy()
                    available_at = max(
                        self.last_req[proxy] + self._min_delay_sec,
                        self.cooldown_until[proxy],
                    )
                    wait = available_at - now

                    if wait <= 0:
                        self.last_req[proxy] = time.time()
                        return proxy

                    if next_wait is None or wait < next_wait:
                        next_wait = wait

                wait_time = max(next_wait or 0, 0)

                if wait_time > 0:
                    if ev.wait(wait_time):
                        raise DaangnCancelledError()
                else:
                    # avoid busy loop if wait_time rounds to 0
                    time.sleep(0)

    def record_failure(self, proxy: str, cooldown_ms: int | None = None) -> None:
        with self.lock:
            if proxy not in self.cooldown_until:
                return

            # 10초
            cooldown_ms = cooldown_ms or (10 * 1000)
            if cooldown_ms <= 0:
                return

            cooldown_sec = cooldown_ms / 1000.0
            self.cooldown_until[proxy] = max(
                self.cooldown_until[proxy], time.time() + cooldown_sec
            )

    def empty(self) -> bool:
        return len(self.proxies) == 0

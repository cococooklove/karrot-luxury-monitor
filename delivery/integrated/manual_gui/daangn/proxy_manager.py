import threading
import time

from daangn.errors import DaangnCancelledError
from daangn_ext import proxy_budget, throttle

# 풀 전체가 쿨다운일 때 최대 이만큼만 기다리고, 가장 빨리 풀리는 IP 로 진행한다.
# 하드차단 쿨다운은 최대 1800초라 곧이곧대로 기다리면 작업이 30분 멈춘다.
# 어차피 대안 IP 가 없는 상황이므로 멈춤보다 진행이 낫고, robust 가 내부에서
# 다시 분류·교체하므로 정말 막혀 있으면 그 요청만 실패하고 끝난다.
MAX_STALL_SEC = 20.0


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

    @property
    def _min_delay_sec(self) -> float:
        """설정값 x 자동감속 배수. 차단 신호가 나오면 여기서 자동으로 느려진다."""
        return throttle.scale(self.min_delay_ms / 1000.0)

    def _next_proxy(self) -> str:
        proxy = self.proxies[self.idx]
        self.idx = (self.idx + 1) % len(self.proxies)
        return proxy

    def _available_at(self, proxy: str, delay_sec: float) -> float:
        """이 IP 를 다시 쓸 수 있는 시각.
        로컬 쿨다운(연속 실패)과 daangn_ext.proxy_budget 쿨다운(429/403 분류 결과)을
        **둘 다** 본다. 종전에는 두 저장소가 분리돼 있어, robust 가 429 로 600초 쿨다운시킨
        IP 를 ProxyManager 가 곧바로 다시 배정했다."""
        return max(
            self.last_req[proxy] + delay_sec,
            self.cooldown_until[proxy],
            proxy_budget.cooling_until(proxy),
        )

    def acquire(self, ev: threading.Event) -> str:
        if not self.proxies:
            raise RuntimeError("No proxies are configured")

        with self.lock:
            while True:
                now = time.time()
                delay_sec = self._min_delay_sec
                next_wait = None
                soonest = None

                for _ in range(len(self.proxies)):
                    proxy = self._next_proxy()
                    wait = self._available_at(proxy, delay_sec) - now

                    if wait <= 0:
                        self.last_req[proxy] = time.time()
                        return proxy

                    if next_wait is None or wait < next_wait:
                        next_wait, soonest = wait, proxy

                wait_time = max(next_wait or 0, 0)

                if wait_time > MAX_STALL_SEC and soonest:
                    # 전부 장기 쿨다운 → 멈추지 말고 가장 빨리 풀리는 IP 로 진행
                    if ev.wait(MAX_STALL_SEC):
                        raise DaangnCancelledError()
                    self.last_req[soonest] = time.time()
                    return soonest

                if wait_time > 0:
                    if ev.wait(wait_time):
                        raise DaangnCancelledError()
                else:
                    # avoid busy loop if wait_time rounds to 0
                    time.sleep(0)

    def record_failure(self, proxy: str, cooldown_ms: int | None = None) -> None:
        """워커 단위 실패(재시도 소진) → 짧은 로컬 쿨다운.
        여기서 proxy_budget 에는 손대지 않는다 — 이 실패의 대부분은 빈응답이고,
        빈응답에 전역 쿨다운을 걸면 멀쩡한 IP 가 풀에서 빠져 풀이 말라버린다.
        진짜 차단(403/429/캡차)은 robust 가 분류해서 proxy_budget 에 이미 걸어 둔다."""
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

    def status(self) -> dict:
        """GUI 표시용 — 지금 몇 개가 쓸 수 있는지(로컬+전역 쿨다운 합산).
        **self.lock 을 잡지 않는다** — acquire 가 대기 중에도 락을 쥐고 있어서,
        여기서 락을 기다리면 상태표시 때문에 UI 스레드가 최대 20초 얼어붙는다.
        표시용 근사치라 락 없이 읽어도 문제 없다."""
        now = time.time()
        cooling = [
            p for p in list(self.proxies)
            if max(self.cooldown_until.get(p, 0.0), proxy_budget.cooling_until(p)) > now
        ]
        return {"total": len(self.proxies), "cooling": len(cooling),
                "alive": len(self.proxies) - len(cooling)}

    def empty(self) -> bool:
        return len(self.proxies) == 0

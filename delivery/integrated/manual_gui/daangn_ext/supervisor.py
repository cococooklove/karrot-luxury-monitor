"""감시 수명주기 — 토글 하나가 폴링·워치 스윕·검색 스윕을 함께 관장한다.

이전에는 워치 스윕 타이머가 '자동 폴링' 버튼에 묶여 있어서, 폴링을 끄면
가격 추적도 같이 멈췄다. 사용자 의도와 어긋난다. 여기서는 셋이 한 수명을
공유하고 시작·정지가 한 곳에서만 일어난다.

Qt 를 import 하지 않는다. 타이머는 start(ms)/stop()/isActive()/setInterval(ms)/
interval() 을 가진 무엇이든 된다 — QTimer 가 그 모양이다.
"""
from __future__ import annotations


class SupervisorPolicy:
    """간격 계산만 한다. 야간 감속 배수는 두 타이머에 똑같이 곱한다."""

    def __init__(self, poll_interval_fn, night_factor_fn, sweep_interval: int = 600):
        self._poll_fn = poll_interval_fn
        self._night_fn = night_factor_fn
        self.sweep_interval = int(sweep_interval)

    def _factor(self) -> int:
        try:
            return max(1, int(self._night_fn() or 1))
        except Exception:
            return 1

    def poll_ms(self) -> int:
        try:
            base = max(1, int(self._poll_fn() or 0))
        except Exception:
            base = 120
        return base * self._factor() * 1000

    def sweep_ms(self) -> int:
        return self.sweep_interval * self._factor() * 1000


class SupervisorController:
    def __init__(self, policy, poll_timer, sweep_timer, sweep_queue,
                 start_search_sweep, stop_search_sweep,
                 start_feed=None, stop_feed=None):
        self.policy = policy
        self.poll_timer = poll_timer
        self.sweep_timer = sweep_timer
        self.sweep_queue = sweep_queue
        self._start_search = start_search_sweep
        self._stop_search = stop_search_sweep
        self._start_feed = start_feed or (lambda: None)
        self._stop_feed = stop_feed or (lambda: None)
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.poll_timer.start(self.policy.poll_ms())
        self.sweep_timer.start(self.policy.sweep_ms())
        # 검색 스윕은 대기열이 있을 때만 띄운다 — 빈 조건으로 지역을 훑으면
        # 요청만 쓰고 아무것도 안 잡는다.
        if len(self.sweep_queue):
            self._start_search()
        self._start_feed()

    def stop(self) -> None:
        self._running = False
        self.poll_timer.stop()
        self.sweep_timer.stop()
        self._stop_search()
        self._stop_feed()

    def retune(self) -> None:
        """정책 값이 바뀌었을 때(주기 변경·야간 진입) 간격만 갈아끼운다."""
        if not self._running:
            return
        self.poll_timer.setInterval(self.policy.poll_ms())
        self.sweep_timer.setInterval(self.policy.sweep_ms())

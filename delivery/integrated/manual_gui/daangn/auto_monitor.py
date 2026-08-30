"""
자동 모니터 QThread 어댑터 — GUI 전용.

로직은 전부 daangn.sweep_engine.SweepEngine 에 있다. 이 모듈은 그 엔진의 콜백을
Qt 시그널로 이어 주는 얇은 껍데기뿐이다. GUI 경로는 어차피 Qt 위에서 돌기 때문에
여기서 PyQt 를 import 하는 것은 정상이다 — 대신 엔진 모듈에는 Qt 가 없어야 한다.
"""
from PyQt6.QtCore import QThread, pyqtSignal

from daangn.sweep_engine import SweepEngine
# 재수출 — 기존 호출부(full_test/gui_func_test/_construct_test)가 여기서 가져간다.
from daangn.sweep_engine import load_conditions_from_excel  # noqa: F401


class AutoMonitor(QThread):
    """SweepEngine 을 QThread 로 감싼 얇은 어댑터. 로직은 전부 엔진에 있다."""

    log = pyqtSignal(str)
    found = pyqtSignal(dict)        # 신규/변동 매물 → 결과 테이블
    status = pyqtSignal(str)        # 현재 진행 상황 → 상태 라벨

    def __init__(self, parent, cfg: dict):
        super().__init__(parent)
        self.cfg = cfg
        self.engine = SweepEngine(cfg,
                                  on_log=self.log.emit,
                                  on_found=self.found.emit,
                                  on_status=self.status.emit)

    def stop(self):
        self.engine.stop()

    def run(self):
        self.engine.run()

    # 중지 플래그는 엔진 것 하나뿐이다(어댑터에 사본을 두면 갈라진다).
    # notify_test.py 가 `m._stop = True` 로 직접 세운다 → setter 필요.
    @property
    def _stop(self):
        return self.engine._stop

    @_stop.setter
    def _stop(self, v):
        self.engine._stop = v

    # 엔진 내부(_tg/_dedup_notify/_flush_notify/_telegram/_sheet_append/_proxy_cycle)
    # 로 위임 — notify_test.py / full_test.py 가 인스턴스에서 직접 부른다.
    def __getattr__(self, name):
        if name.startswith("__") or name == "engine":
            raise AttributeError(name)
        try:
            engine = object.__getattribute__(self, "engine")
        except AttributeError:
            raise AttributeError(name)
        return getattr(engine, name)

    # robust_test.py 가 `AutoMonitor.__dict__["_regions"]` 로 언바운드로 꺼내
    # 더미 객체에 물려 쓴다 → 클래스 사전에 실물이 있어야 한다.
    def _regions(self):
        return SweepEngine._regions(self)

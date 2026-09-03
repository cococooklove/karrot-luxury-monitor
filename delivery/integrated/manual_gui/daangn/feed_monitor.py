# daangn/feed_monitor.py
"""피드 스윕 QThread 어댑터 — GUI 전용. 로직은 daangn.feed_sweep.FeedSweep 에 있다."""
from PyQt6.QtCore import QThread, pyqtSignal

from daangn.feed_sweep import FeedSweep


class FeedMonitor(QThread):
    log = pyqtSignal(str)
    found = pyqtSignal(dict)
    status = pyqtSignal(str)

    def __init__(self, parent, cfg: dict):
        super().__init__(parent)
        self.cfg = cfg
        self.engine = FeedSweep(cfg, on_log=self.log.emit,
                                on_found=self.found.emit, on_status=self.status.emit)

    def stop(self):
        self.engine.stop()

    def run(self):
        self.engine.run()

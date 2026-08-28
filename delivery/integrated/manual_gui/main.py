import json
import os
from datetime import datetime, timedelta
from io import BytesIO

from typing import Any
from uuid import uuid4

from daangn.controller import MainController
from daangn.detail import render_to_html
from daangn.utils import image_contain_resize
from daangn.workers import CancelableImageDownloader, ExportExcel
from daangn.model import Product
from daangn.task import CrawlTask
from daangn.ui_mainwindow import Ui_MainWindow

from PyQt6 import QtWidgets, QtCore, QtGui


# 명품 브랜드(키워드 알림 일괄등록용) — parse_luxury.BRANDS 대표명
LUXURY_BRANDS = ["샤넬", "루이비통", "에르메스", "구찌", "프라다", "디올", "셀린느",
                 "보테가베네타", "생로랑", "발렌시아가", "펜디", "버버리", "몽클레르",
                 "고야드", "롤렉스", "까르띠에", "티파니", "불가리", "반클리프", "오메가"]


class _HarvestThread(QtCore.QThread):
    """백그라운드 자동 수확 — 앱 실행 중 주기적으로 LDPlayer/폰서 토큰 갱신.
    accounts.json 을 항상 신선하게 유지 → 수동 수확 불필요. access 30분 만료 전 갱신."""
    tick = QtCore.pyqtSignal(str)

    def __init__(self, interval=1200, accounts="./accounts.json"):
        super().__init__()
        self.interval = interval
        self.accounts = accounts
        self._stop = False

    def run(self):
        import time as _t
        while not self._stop:
            try:
                import ld_autoharvest
                u, i, t, h = ld_autoharvest.harvest_all(self.accounts, nudge=True)
                self.tick.emit(f"[자동수확] {h}계정 갱신 · 총 {t}계정" if h
                               else "[자동수확] 대상 없음(LDPlayer/폰 확인)")
            except Exception as e:
                self.tick.emit(f"[자동수확] 실패: {str(e)[:60]}")
            for _ in range(max(1, self.interval)):
                if self._stop:
                    return
                _t.sleep(1)

    def stop(self):
        self._stop = True


class _AlertWorker(QtCore.QThread):
    """알림 API 호출을 백그라운드로(GUI 프리징 방지). fn(log_emit) 실행 후 결과 emit."""
    done = QtCore.pyqtSignal(object)
    log = QtCore.pyqtSignal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn(self.log.emit))
        except Exception as e:
            self.log.emit(f"[오류] {type(e).__name__}: {e}")
            self.done.emit(None)
from PyQt6.QtGui import (
    QCloseEvent,
    QFontDatabase,
    QRegularExpressionValidator,
    QPixmap,
    QDesktopServices,
)
from PyQt6.QtCore import Qt, QRegularExpression, QItemSelection, QUrl
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtWidgets import QProgressDialog
from PIL import Image as PILImage
from openpyxl import load_workbook


APP_QSS = """
* { font-family: 'Pretendard', '.AppleSystemUIFont', 'Apple SD Gothic Neo', 'Malgun Gothic', Helvetica; font-size: 13px; color: #333D4B; }
QMainWindow, QWidget { background: #F9FAFB; }
QToolTip { background:#191F28; color:#fff; border:none; padding:6px 8px; border-radius:8px; }

QTabWidget::pane { border: none; background: transparent; }
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab { background: transparent; color: #8B95A1; padding: 10px 18px; margin-right: 2px; border: none; font-size: 15px; font-weight: 700; }
QTabBar::tab:selected { color: #FF7E36; }
QTabBar::tab:hover:!selected { color: #4E5968; }

QLabel { color: #4E5968; }

QLineEdit, QSpinBox, QComboBox { background: #F2F4F6; border: 1.5px solid transparent; border-radius: 12px; padding: 8px 13px; color: #191F28; font-size: 14px; min-height: 24px; selection-background-color: #FFD9C2; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { background: #FFFFFF; border: 1.5px solid #FF7E36; }
QLineEdit::placeholder { color: #B0B8C1; }
QSpinBox::up-button, QSpinBox::down-button { width: 16px; border: none; background: transparent; }

QPushButton { background: #F2F4F6; color: #4E5968; border: none; border-radius: 12px; padding: 9px 14px; font-weight: 700; font-size: 13px; min-height: 22px; }
QPushButton:hover { background: #E8EBED; }
QPushButton:pressed { background: #DDE1E5; }
QPushButton:disabled { color: #B0B8C1; }
QPushButton#startBtn, QPushButton#autoStartBtn { background: #FF7E36; color: #FFFFFF; padding: 10px 22px; font-size: 14px; }
QPushButton#startBtn:hover, QPushButton#autoStartBtn:hover { background: #F26F26; }
QPushButton#startBtn:pressed, QPushButton#autoStartBtn:pressed { background: #E0631F; }

QCheckBox { color: #4E5968; spacing: 8px; font-size: 14px; min-height: 24px; }
QCheckBox::indicator { width: 20px; height: 20px; border: 2px solid #D1D6DB; border-radius: 6px; background: #FFFFFF; }
QCheckBox::indicator:checked { background: #FF7E36; border-color: #FF7E36; }
QCheckBox::indicator:hover { border-color: #FF7E36; }

QGroupBox { background: #FFFFFF; border: none; border-radius: 18px; margin-top: 16px; padding: 20px 18px 14px 18px; font-size: 15px; font-weight: 800; color: #191F28; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; top: 2px; padding: 0 4px; }

QTreeWidget, QListWidget, QTableWidget, QTextEdit, QTextBrowser { background: #FFFFFF; border: 1px solid #F2F4F6; border-radius: 14px; padding: 4px; font-size: 13px; }
QTreeWidget::item, QListWidget::item { padding: 6px 4px; border-radius: 8px; }
QTreeWidget::item:selected, QListWidget::item:selected { background: #FFF0E6; color: #E8590C; }
QTreeWidget::item:hover, QListWidget::item:hover { background: #F9FAFB; }

QTableWidget { gridline-color: #F2F4F6; }
QTableWidget::item { padding: 9px 6px; }
QTableWidget::item:selected { background: #FFF0E6; color: #191F28; }
QHeaderView::section { background: #FFFFFF; color: #8B95A1; padding: 11px 8px; border: none; border-bottom: 1.5px solid #F2F4F6; font-weight: 700; font-size: 12px; }
QTableCornerButton::section { background: #FFFFFF; border: none; }

QProgressBar { background: #F2F4F6; border: none; border-radius: 4px; max-height: 6px; }
QProgressBar::chunk { background: #FF7E36; border-radius: 4px; }

QScrollArea { border: none; background: transparent; }
QSplitter::handle { background: transparent; }
QStatusBar { background: transparent; color: #8B95A1; }
QStatusBar::item { border: none; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 4px 2px; }
QScrollBar::handle:vertical { background: #D1D6DB; border-radius: 5px; min-height: 40px; }
QScrollBar::handle:vertical:hover { background: #B0B8C1; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px 4px; }
QScrollBar::handle:horizontal { background: #D1D6DB; border-radius: 5px; min-width: 40px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""


class NotifyTestThread(QtCore.QThread):
    """알림 설정 테스트 — 네트워크 호출이 GUI 를 멈추지 않게 별도 스레드."""
    result = QtCore.pyqtSignal(dict)

    def __init__(self, parent, cfg):
        super().__init__(parent)
        self.cfg = cfg

    def run(self):
        from daangn.notify import run_test
        try:
            res = run_test(self.cfg.get("tg_token"), self.cfg.get("tg_chat"),
                           self.cfg.get("sheet_url"), self.cfg.get("sheet_cred"))
        except Exception as e:
            res = {"tg_ok": False, "tg_msg": f"{type(e).__name__}: {e}",
                   "sheet_ok": None, "sheet_msg": "테스트 실패"}
        self.result.emit(res)


class HealthCheckThread(QtCore.QThread):
    """프록시 풀 진단 — IP 당 1요청. 네트워크가 GUI 를 멈추지 않게 별도 스레드."""
    result = QtCore.pyqtSignal(dict)
    progress = QtCore.pyqtSignal(int, int)

    def __init__(self, parent, proxies):
        super().__init__(parent)
        self.proxies = list(proxies)

    def run(self):
        from daangn_ext.health import health_check
        try:
            res = health_check(self.proxies,
                               on_progress=lambda d, t: self.progress.emit(d, t))
        except Exception as e:
            res = {"error": f"{type(e).__name__}: {e}"}
        self.result.emit(res)


class MyProgressDialog(QProgressDialog):
    def closeEvent(self, a0: QCloseEvent):  # type: ignore
        if a0.spontaneous():
            a0.ignore()


class SortUserRoleItem(QtWidgets.QTableWidgetItem):
    def __lt__(self, other):
        return self.data(Qt.ItemDataRole.UserRole) < other.data(
            Qt.ItemDataRole.UserRole
        )


class MainWindow(QMainWindow):
    EXCEL_HEADER_ALIASES = {
        "지역": "area",
        "키워드": "keyword",
        "최소가격": "minimum",
        "최대가격": "maximum",
    }

    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self._init_state()
        self._setup_ui()

        self.controller = MainController(self)

        if not self.controller.is_ready():
            self.alert(f"DB open failed: {self.controller.db_error}")
            return

        self._setup_model()
        self._init_tree()
        self._connect_signals()

        self._load_proxy()
        self._setup_tabs()
        self.sb.showMessage("프로그램이 시작되었습니다.")

        # 백그라운드 자동 수확 — 토큰 항상 신선 유지(수동 불필요). 20분 주기.
        self._harvest_thread = _HarvestThread(interval=1200, accounts="./accounts.json")
        self._harvest_thread.tick.connect(self._on_harvest_tick)
        self._harvest_thread.start()

    def _on_harvest_tick(self, msg):
        if hasattr(self, "alertLog"):
            self.alertLog.append(msg)
        self.sb.showMessage(msg, 4000)
        # 계정수 대시보드 즉시 갱신
        try:
            self._init_dashboard()
        except Exception:
            pass

    def _setup_tabs(self):
        """기존 수동 UI 를 탭으로 감싸고 자동 탭 추가. 스크롤로 어떤 창크기든 다 보이게."""
        self.takeCentralWidget()                    # 기존 중앙위젯 버림(위젯은 재사용)
        self.tabs = QtWidgets.QTabWidget(self)
        self.tabs.addTab(self._scroll(self._build_manual_tab()), "수동 검색")
        self.auto_monitor = None
        self.tabs.addTab(self._scroll(self._build_auto_tab()), "자동 모니터")
        self.tabs.addTab(self._scroll(self._build_alert_tab()), "키워드 알림")
        self.setCentralWidget(self.tabs)
        self._refresh_proxy_labels()
        self.resize(1200, 840)                      # 하단 위젯 안 잘리게 넉넉히
        self.setStyleSheet(APP_QSS)                  # 전역 스타일
        self._apply_card_shadows()

    def _apply_card_shadows(self):
        """그룹박스 카드에 소프트 그림자(토스 입체감). QSS box-shadow 대체."""
        from PyQt6.QtWidgets import QGraphicsDropShadowEffect
        from PyQt6.QtGui import QColor
        for gb in self.findChildren(QtWidgets.QGroupBox):
            eff = QGraphicsDropShadowEffect(gb)
            eff.setBlurRadius(28); eff.setOffset(0, 6)
            eff.setColor(QColor(17, 24, 40, 28))
            gb.setGraphicsEffect(eff)

    def _scroll(self, inner):
        sa = QtWidgets.QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(inner)
        return sa

    # ── 키워드 알림 탭 ─────────────────────────────────────────────
    def _build_alert_tab(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(10)

        v.addWidget(QtWidgets.QLabel(
            "키워드 알림을 계정에 등록 → 매물 뜨면 토큰폴링으로 실시간 수신. "
            "1계정 = 인증동네 + 인접 지역 커버. 여러 계정(다른 동네) = 전국."))

        # ── 현황 대시보드 ──
        dash = QtWidgets.QGroupBox("현황"); dl = QtWidgets.QVBoxLayout(dash)
        self.dashAccounts = QtWidgets.QLabel("계정: - (집계 전)")
        self.dashCoverage = QtWidgets.QLabel("커버리지: - ")
        self.dashBar = QtWidgets.QProgressBar(); self.dashBar.setRange(0, 100); self.dashBar.setValue(0)
        self.dashBar.setFormat("전국 커버 %p%")
        self.dashBar.setFixedHeight(24)            # 높이 붕괴 방지(라벨 사이 끼임 깨짐 수정)
        self.dashBar.setTextVisible(True)
        dl.setSpacing(8)
        self.dashCadence = QtWidgets.QLabel("폴링 주기: -")
        self.dashGuide = QtWidgets.QLabel("증설 안내: [커버 동네 집계]를 눌러 현황을 계산하세요")
        self.dashGuide.setWordWrap(True)
        for wdg in (self.dashAccounts, self.dashCoverage, self.dashBar, self.dashCadence, self.dashGuide):
            dl.addWidget(wdg)
        v.addWidget(dash)

        # 등록 폼
        form = QtWidgets.QGroupBox("키워드 등록"); fl = QtWidgets.QVBoxLayout(form)
        r0 = QtWidgets.QHBoxLayout()
        self.alertKeyword = QtWidgets.QLineEdit(); self.alertKeyword.setPlaceholderText("키워드 (예: 샤넬)")
        self.alertMin = QtWidgets.QLineEdit(); self.alertMin.setPlaceholderText("최소가(선택)"); self.alertMin.setFixedWidth(110)
        self.alertMax = QtWidgets.QLineEdit(); self.alertMax.setPlaceholderText("최대가(선택)"); self.alertMax.setFixedWidth(110)
        self.alertExclude = QtWidgets.QLineEdit(); self.alertExclude.setPlaceholderText("제외 키워드(쉼표)")
        r0.addWidget(self.alertKeyword, 2); r0.addWidget(self.alertMin); r0.addWidget(self.alertMax); r0.addWidget(self.alertExclude, 2)
        fl.addLayout(r0)
        r1 = QtWidgets.QHBoxLayout()
        self.alertAddBtn = QtWidgets.QPushButton("등록"); self.alertAddBtn.setObjectName("startBtn")
        self.alertBulkBtn = QtWidgets.QPushButton(f"명품{len(LUXURY_BRANDS)} 일괄(현재계정)")
        self.alertBulkAllBtn = QtWidgets.QPushButton(f"명품{len(LUXURY_BRANDS)} 전계정등록(전국)")
        self.alertBulkAllBtn.setObjectName("startBtn")
        self.alertRefreshBtn = QtWidgets.QPushButton("목록 새로고침")
        r1.addWidget(self.alertAddBtn); r1.addWidget(self.alertBulkBtn); r1.addWidget(self.alertBulkAllBtn)
        r1.addStretch(1); r1.addWidget(self.alertRefreshBtn)
        fl.addLayout(r1)
        v.addWidget(form)

        # 커버 동네 정보
        self.alertSubLabel = QtWidgets.QLabel("동네 정보: (새로고침을 누르세요)")
        v.addWidget(self.alertSubLabel)

        # 등록 목록
        self.alertTable = QtWidgets.QTableWidget(0, 4, w)
        self.alertTable.setHorizontalHeaderLabels(["키워드", "가격범위", "제외", "id"])
        self.alertTable.verticalHeader().setVisible(False)
        self.alertTable.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.alertTable.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.alertTable.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.alertTable.setMinimumHeight(300)
        v.addWidget(self.alertTable, 1)

        r2 = QtWidgets.QHBoxLayout()
        self.alertDelBtn = QtWidgets.QPushButton("선택 삭제")
        self.alertDelAllBtn = QtWidgets.QPushButton("전체 삭제")
        r2.addWidget(self.alertDelBtn); r2.addWidget(self.alertDelAllBtn); r2.addStretch(1)
        v.addLayout(r2)

        # ── 신규 매칭 (토큰 폴링, 앱/푸시 불필요) ──
        v.addWidget(QtWidgets.QLabel("── 신규 명품 매칭 (토큰 폴링으로 수신 · 앱/LDPlayer 상시ON 불필요) ──"))
        r3 = QtWidgets.QHBoxLayout()
        self.alertPollBtn = QtWidgets.QPushButton("매칭 조회(현재계정)")
        self.alertPollAllBtn = QtWidgets.QPushButton("전계정 매칭(전국)"); self.alertPollAllBtn.setObjectName("startBtn")
        self.alertAutoPollBtn = QtWidgets.QPushButton("자동 폴링 시작")
        self.alertCoverageBtn = QtWidgets.QPushButton("커버 동네 집계")
        self.alertPollInterval = QtWidgets.QSpinBox(); self.alertPollInterval.setRange(30, 3600)
        self.alertPollInterval.setValue(120); self.alertPollInterval.setSuffix("초")
        r3.addWidget(self.alertPollBtn); r3.addWidget(self.alertPollAllBtn)
        r3.addWidget(self.alertAutoPollBtn); r3.addWidget(self.alertCoverageBtn)
        r3.addWidget(QtWidgets.QLabel("주기")); r3.addWidget(self.alertPollInterval); r3.addStretch(1)
        v.addLayout(r3)

        self.matchTable = QtWidgets.QTableWidget(0, 6, w)
        self.matchTable.setHorizontalHeaderLabels(["시각", "키워드", "제목", "가격", "지역", "계정"])
        self.matchTable.verticalHeader().setVisible(False)
        self.matchTable.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.matchTable.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.matchTable.horizontalHeader().setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.matchTable.setMinimumHeight(260)
        self.matchTable.itemDoubleClicked.connect(self.on_match_open)
        v.addWidget(self.matchTable, 1)

        self.alertLog = QtWidgets.QTextEdit(); self.alertLog.setReadOnly(True); self.alertLog.setMaximumHeight(110)
        v.addWidget(self.alertLog)

        self.alertAddBtn.clicked.connect(self.on_alert_add)
        self.alertBulkBtn.clicked.connect(self.on_alert_bulk)
        self.alertRefreshBtn.clicked.connect(self.on_alert_refresh)
        self.alertDelBtn.clicked.connect(self.on_alert_delete)
        self.alertDelAllBtn.clicked.connect(self.on_alert_delete_all)
        self.alertPollBtn.clicked.connect(self.on_alert_poll)
        self.alertAutoPollBtn.clicked.connect(self.on_alert_autopoll)
        self.alertBulkAllBtn.clicked.connect(self.on_alert_bulk_all)
        self.alertPollAllBtn.clicked.connect(self.on_alert_poll_all)
        self.alertCoverageBtn.clicked.connect(self.on_alert_coverage)
        self._alert_worker = None
        self._match_links = {}
        self._match_seen = self._load_match_seen()
        self._alert_poll_timer = QtCore.QTimer(self)
        self._alert_poll_timer.timeout.connect(self.on_alert_poll_all)  # 자동폴링=전국(전계정)
        self._init_dashboard()
        return w

    def _init_dashboard(self):
        """탭 열릴 때 계정수 즉시 표시(토큰 불필요, accounts.json만). 커버리지는 버튼."""
        import json as _json
        n_total = n_valid = 0
        try:
            from daangn_ext.keyword_alert_api import token_remaining
            for a in _json.load(open("./accounts.json", encoding="utf-8")):
                n_total += 1
                if a.get("access") and token_remaining(a["access"]) > 60:
                    n_valid += 1
        except Exception:
            pass
        self.dashAccounts.setText(
            f"계정: 총 {n_total}개 · 유효토큰 {n_valid}개"
            + ("  (수확 필요 — 유효토큰 0)" if n_valid == 0 else ""))
        self.dashCadence.setText(f"폴링 주기: {self.alertPollInterval.value()}초 (자동폴링 시)")
        self.dashGuide.setText(
            "커버리지·전국% 는 [커버 동네 집계]를 눌러 계산하세요. "
            "1계정≈39지역 · 전국(~3500동)엔 서로 다른 동네 ~90~250계정 필요.")

    def _alert_api(self):
        """스레드 내에서 호출 — thread-safe 토큰 수확 후 KeywordAlertAPI 반환."""
        from daangn_ext.keyword_alert_api import KeywordAlertAPI
        token = self._harvest_token_quiet()
        if not token:
            raise RuntimeError("유효 토큰 없음 — LDPlayer/폰 수확 확인")
        return KeywordAlertAPI(token)

    def _alert_run(self, fn, on_done=None):
        if self._alert_worker and self._alert_worker.isRunning():
            self.alert("이전 작업 진행 중 — 잠시 후"); return
        self.alertLog.append("── 작업 시작 ──")
        self._alert_worker = _AlertWorker(fn)
        self._alert_worker.log.connect(lambda m: self.alertLog.append(m))
        if on_done:
            self._alert_worker.done.connect(on_done)
        self._alert_worker.start()

    def _pi(self, s):
        s = (s or "").strip().replace(",", "")
        return int(s) if s.isdigit() else None

    def on_alert_add(self):
        kw = self.alertKeyword.text().strip()
        if not kw:
            self.alert("키워드를 입력하세요"); return
        mn, mx = self._pi(self.alertMin.text()), self._pi(self.alertMax.text())
        excl = [x for x in self.alertExclude.text().replace(" ", "").split(",") if x]
        def job(log):
            api = self._alert_api()
            if api.is_banned(kw):
                log(f"'{kw}' 는 차단 키워드 — 등록불가"); return None
            api.register(kw, mn, mx, excl); log(f"'{kw}' 등록 ✓")
            return api.list()
        self._alert_run(job, self._alert_populate)

    def on_alert_bulk(self):
        mn, mx = self._pi(self.alertMin.text()), self._pi(self.alertMax.text())
        def job(log):
            api = self._alert_api()
            res = api.register_many(LUXURY_BRANDS, mn, mx, log=log)
            log(f"완료 — 등록 {len(res['added'])} · 스킵 {len(res['skipped'])} · 실패 {len(res['failed'])}")
            return api.list()
        self._alert_run(job, self._alert_populate)

    def on_alert_refresh(self):
        def job(log):
            api = self._alert_api()
            data = api.list(); log(f"등록 {len(data.get('user_keywords') or [])}건")
            return data
        self._alert_run(job, self._alert_populate)

    def on_alert_delete(self):
        row = self.alertTable.currentRow()
        if row < 0:
            self.alert("삭제할 행을 선택하세요"); return
        item = self.alertTable.item(row, 3)
        if not item:
            return
        uid = item.text()
        def job(log):
            api = self._alert_api()
            ok = api.delete(uid); log(f"삭제 {'✓' if ok else '실패'} id={uid}")
            return api.list()
        self._alert_run(job, self._alert_populate)

    def on_alert_delete_all(self):
        if QtWidgets.QMessageBox.question(self, "전체 삭제", "등록된 키워드를 모두 삭제할까요?") \
                != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        def job(log):
            api = self._alert_api()
            n = api.delete_all(log=log); log(f"총 {n}건 삭제")
            return api.list()
        self._alert_run(job, self._alert_populate)

    def _alert_populate(self, data):
        if not data:
            return
        kws = data.get("user_keywords") or []
        self.alertTable.setRowCount(0)
        for k in kws:
            r = self.alertTable.rowCount(); self.alertTable.insertRow(r)
            price = ""
            if k.get("min_price") or k.get("max_price"):
                price = f"{k.get('min_price') or ''}~{k.get('max_price') or ''}"
            vals = [k.get("keyword", ""), price,
                    ",".join(k.get("exclude_keywords") or []), str(k.get("id", ""))]
            for c, val in enumerate(vals):
                self.alertTable.setItem(r, c, QtWidgets.QTableWidgetItem(val))
        subs = data.get("subscription_infos") or []
        if subs:
            txt = " · ".join(f"{s.get('name')}({s.get('ranged_regions_count')}지역"
                             + (",알림ON" if s.get('enable_notification') else ",알림OFF") + ")"
                             for s in subs)
            self.alertSubLabel.setText(f"커버 동네: {txt}")

    # ── 신규 매칭 폴링 ──
    def on_alert_poll(self):
        def job(log):
            api = self._alert_api()
            matches = api.new_matches()
            log(f"매칭 조회: {len(matches)}건")
            return matches
        self._alert_run(job, self._match_populate)

    def on_alert_autopoll(self):
        if self._alert_poll_timer.isActive():
            self._alert_poll_timer.stop()
            self.alertAutoPollBtn.setText("자동 폴링 시작")
            self.alertLog.append("[자동폴링] 정지")
        else:
            self._alert_poll_timer.start(self.alertPollInterval.value() * 1000)
            self.alertAutoPollBtn.setText("자동 폴링 정지")
            self.alertLog.append(f"[자동폴링] 시작 · {self.alertPollInterval.value()}초 주기 · 전계정(전국)")
            self.on_alert_poll_all()

    def _match_populate(self, matches):
        if matches is None:
            return
        import time as _t
        new = 0
        new_items = []
        for m in matches:
            key = str(m.get("id") or m.get("article_id") or m.get("title"))
            if key in self._match_seen:
                continue
            self._match_seen.add(key); new += 1
            new_items.append(m)
            r = self.matchTable.rowCount(); self.matchTable.insertRow(r)
            try:
                ts = _t.strftime("%m/%d %H:%M", _t.localtime(int(m.get("time") or 0)))
            except Exception:
                ts = ""
            vals = [ts, m.get("keyword") or "", (m.get("title") or "")[:60],
                    str(m.get("price") or ""), m.get("region") or "", m.get("_account") or ""]
            for c, val in enumerate(vals):
                cell = QtWidgets.QTableWidgetItem(val)
                if c == 0:
                    cell.setData(QtCore.Qt.ItemDataRole.UserRole, m.get("url") or "")
                self.matchTable.setItem(r, c, cell)
            self.matchTable.sortItems(0, QtCore.Qt.SortOrder.DescendingOrder)
        if new:
            self.alertLog.append(f"[매칭] 신규 {new}건 추가 (누적 {len(self._match_seen)})")
            self._notify_matches(new_items)
            self._save_match_seen()

    _MATCH_SEEN_FILE = "./data/match_seen.json"

    def _load_match_seen(self):
        import json as _json, os as _os
        try:
            return set(_json.load(open(self._MATCH_SEEN_FILE, encoding="utf-8")))
        except Exception:
            return set()

    def _save_match_seen(self):
        import json as _json, os as _os
        try:
            _os.makedirs(_os.path.dirname(self._MATCH_SEEN_FILE), exist_ok=True)
            # 최근 5000개만 유지(무한증가 방지)
            keep = list(self._match_seen)[-5000:]
            _json.dump(keep, open(self._MATCH_SEEN_FILE, "w", encoding="utf-8"))
        except Exception:
            pass

    def _notify_matches(self, items):
        """신규 매칭 → 텔레그램 푸시(notify.json 설정 시). GUI 안 봐도 알림."""
        tok = (getattr(self, "_notify", {}) or {}).get("tg_token")
        chat = (getattr(self, "_notify", {}) or {}).get("tg_chat")
        if not (tok and chat and items):
            return
        try:
            from daangn.notify import TelegramSender
            tg = TelegramSender(tok, chat, log=self.alertLog.append)
            for m in items:
                line = (f"🎯 [{m.get('keyword') or ''}] {(m.get('title') or '')[:50]}\n"
                        f"💰 {m.get('price') or '-'} · 📍 {m.get('region') or '-'}"
                        f" · 계정 {m.get('_account') or '-'}\n{m.get('url') or ''}")
                tg.enqueue(line)
            tg.flush()
            self.alertLog.append(f"[텔레그램] {len(items)}건 전송")
        except Exception as e:
            self.alertLog.append(f"[텔레그램] 실패: {str(e)[:50]}")

    def on_match_open(self, item):
        cell0 = self.matchTable.item(item.row(), 0)
        url = cell0.data(QtCore.Qt.ItemDataRole.UserRole) if cell0 else ""
        if url:
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(url))

    # ── 전국(전 계정) 멀티계정 ──
    def _multi(self, harvest=False):
        """MultiAccountAlerts 반환. harvest=True 면 LDPlayer 수확 먼저(느림·프로덕션용).
        기본은 accounts.json 기존 토큰 사용(빠름 — coverage/poll 즉시)."""
        from daangn_ext.keyword_alert_api import MultiAccountAlerts
        if harvest:
            try:
                import ld_autoharvest
                ld_autoharvest.harvest_all("./accounts.json", nudge=True)
            except Exception:
                pass
        return MultiAccountAlerts("./accounts.json", "./data/config.json")

    def on_alert_bulk_all(self):
        mn, mx = self._pi(self.alertMin.text()), self._pi(self.alertMax.text())
        def job(log):
            self._multi().register_all(LUXURY_BRANDS, mn, mx, log=log)
            return None
        self._alert_run(job)

    def on_alert_poll_all(self):
        def job(log):
            return self._multi().poll_all(log=log)
        self._alert_run(job, self._match_populate)

    def on_alert_coverage(self):
        def job(log):
            cov = self._multi().coverage(log=log)
            total = sum(int(c[2] or 0) for c in cov)
            log(f"커버 동네 {len(cov)}개 · 합산 {total}지역")
            for code, name, cnt in cov:
                log(f"  {code}: {name} ({cnt}지역)")
            return cov
        self._alert_run(job, self._update_dashboard)

    def _update_dashboard(self, cov):
        if cov is None:
            return
        KOREA_DONG = 3500            # 전국 행정동 대략
        AVG_RANGE = 39              # 계정당 커버 지역(역삼동 기준)
        codes = {c[0] for c in cov}
        n_acc = len(codes)
        dongs = {(c[0], c[1]) for c in cov}         # 계정×동네
        total_regions = sum(int(c[2] or 0) for c in cov)
        # 겹침 감안 실효 커버(대략 70%)
        eff = int(total_regions * 0.7)
        pct = min(100, int(eff / KOREA_DONG * 100))
        interval = self.alertPollInterval.value()
        cycle = round(n_acc * 1.5)                  # 순차 폴 1순환(초)
        need_full = max(0, round(KOREA_DONG / (AVG_RANGE * 0.7)) - n_acc)  # 전국까지 추가계정(대략)

        self.dashAccounts.setText(f"계정: {n_acc}개 (유효토큰) · 동네 {len(dongs)}곳")
        self.dashCoverage.setText(f"커버리지: 합산 {total_regions}지역 · 실효 ~{eff}지역 / 전국 {KOREA_DONG}동")
        self.dashBar.setValue(pct)
        self.dashCadence.setText(
            f"폴링 주기: {interval}초 · 전계정 1순환 ~{cycle}초 (순차) · 매칭 감지지연 ≈ 주기")
        self.dashGuide.setText(
            f"증설 안내: 현재 {n_acc}계정 → 전국까지 약 +{need_full}계정 필요(잘 분산 시). "
            f"각 계정을 서로 다른 동네에 배치(LDPlayer GPS)해야 커버가 넓어집니다. "
            f"계정 늘어도 폴링은 병렬화하면 주기 유지(순차면 계정당 ~1.5초 가산).")

    def _build_auto_area_tree(self, parent):
        """자동용 지역 트리 — 수동과 동일한 시도>구>동 3단계. 미선택 시 전국."""
        import json as _json
        tree = QtWidgets.QTreeWidget(parent)
        tree.setHeaderLabel("지역 선택")
        tree.setMinimumWidth(240)
        self.auto_area_leaves = []
        CK = Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate
        try:
            data = _json.load(open("./OUT.json", encoding="utf-8"))
        except Exception:
            return tree
        # 수동 _init_tree 와 동일: 블록(구) 단위 순회 → 같은 동 코드 보장
        sido = {}          # name1(시도) -> [블록(구), ...]
        for block in data:
            sido.setdefault(block["name1"], []).append(block)
        root = QtWidgets.QTreeWidgetItem(tree, ["지역"])
        root.setFlags(root.flags() | CK); root.setCheckState(0, Qt.CheckState.Unchecked)
        for s in sido:                      # 원본 순서(수동과 동일). 정렬 안 함
            top = QtWidgets.QTreeWidgetItem(root, [s])
            top.setFlags(top.flags() | CK); top.setCheckState(0, Qt.CheckState.Unchecked)
            for block in sido[s]:
                gu_txt = f"{block['name1']} {block['name2']}".strip()
                guit = QtWidgets.QTreeWidgetItem(top, [gu_txt])
                guit.setFlags(guit.flags() | CK); guit.setCheckState(0, Qt.CheckState.Unchecked)
                for loc in block["locations"]:
                    leaf = QtWidgets.QTreeWidgetItem(guit, [f"{gu_txt} {loc['name']}".strip()])
                    leaf.setFlags(leaf.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    leaf.setCheckState(0, Qt.CheckState.Unchecked)
                    leaf.setData(0, Qt.ItemDataRole.UserRole, f"{loc['name']}-{loc['id']}")
                    self.auto_area_leaves.append(leaf)
        return tree

    def _tree_panel(self, tree, leaves):
        """트리 + 지역검색 + 전체선택/해제 (UX). 검색은 리프 텍스트 부분일치."""
        panel = QtWidgets.QWidget(self)
        v = QtWidgets.QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(6)
        search = QtWidgets.QLineEdit(panel)
        search.setPlaceholderText("🔍 지역 검색…")
        search.setClearButtonEnabled(True)

        def do_filter(text):
            text = text.strip()
            for leaf in leaves:
                match = (text == "" or text in leaf.text(0))
                leaf.setHidden(not match)
                if match and text:
                    p = leaf.parent()
                    while p:                     # 매칭 리프의 상위 펼침
                        p.setExpanded(True); p = p.parent()
        search.textChanged.connect(do_filter)
        v.addWidget(search)

        hb = QtWidgets.QHBoxLayout(); hb.setSpacing(6)
        ball = QtWidgets.QPushButton("전체 선택", panel)
        bclr = QtWidgets.QPushButton("전체 해제", panel)
        cnt = QtWidgets.QLabel("선택 0", panel)
        ball.clicked.connect(lambda: [l.setCheckState(0, Qt.CheckState.Checked)
                                      for l in leaves if not l.isHidden()])
        bclr.clicked.connect(lambda: [l.setCheckState(0, Qt.CheckState.Unchecked)
                                      for l in leaves])

        # 디바운스: 시도/구 체크 시 itemChanged 수천 발생 → 매번 전체스캔하면 O(N²) 폭발.
        # 타이머로 변경을 모아 한 번만 카운트.
        timer = QtCore.QTimer(panel); timer.setSingleShot(True); timer.setInterval(150)

        def do_count():
            n = sum(1 for l in leaves if l.checkState(0) == Qt.CheckState.Checked)
            cnt.setText(f"선택 {n}")
        timer.timeout.connect(do_count)
        tree.itemChanged.connect(lambda *_: timer.start())
        hb.addWidget(ball); hb.addWidget(bclr); hb.addStretch(1); hb.addWidget(cnt)
        v.addLayout(hb)
        v.addWidget(tree, 1)
        return panel

    def _selected_auto_regions(self):
        return [it.data(0, Qt.ItemDataRole.UserRole)
                for it in getattr(self, "auto_area_leaves", [])
                if it.checkState(0) == Qt.CheckState.Checked]

    def _build_auto_tab(self):
        w = QtWidgets.QWidget(self)
        outer = QtWidgets.QHBoxLayout(w)
        split = QtWidgets.QSplitter(Qt.Orientation.Horizontal, w)
        split.setChildrenCollapsible(False); split.setHandleWidth(6)
        outer.addWidget(split)
        self.autoAreaTree = self._build_auto_area_tree(w)
        split.addWidget(self._tree_panel(self.autoAreaTree, self.auto_area_leaves))
        right = QtWidgets.QWidget(w)
        lay = QtWidgets.QVBoxLayout(right)
        lay.setContentsMargins(4, 4, 4, 4); lay.setSpacing(12)
        split.addWidget(right)
        split.setStretchFactor(0, 0); split.setStretchFactor(1, 1)
        split.setSizes([260, 900])

        self.autoKeyword = QtWidgets.QLineEdit(w); self.autoKeyword.setPlaceholderText("검색 키워드")
        self.autoExtra = QtWidgets.QLineEdit(w); self.autoExtra.setPlaceholderText("추가 키워드")
        self.autoExclude = QtWidgets.QLineEdit(w); self.autoExclude.setPlaceholderText("제외 키워드")
        self.autoMin = QtWidgets.QLineEdit(w); self.autoMin.setPlaceholderText("최소가"); self.autoMin.setFixedWidth(96)
        self.autoMax = QtWidgets.QLineEdit(w); self.autoMax.setPlaceholderText("최대가"); self.autoMax.setFixedWidth(96)
        self.autoDays = QtWidgets.QSpinBox(w); self.autoDays.setRange(0, 365); self.autoDays.setValue(7); self.autoDays.setFixedWidth(72)
        # 사이클 휴식(초) — 하한 10s: 그 아래는 무휴식 폴링 = 봇 패턴 → 차단
        self.autoRestMin = QtWidgets.QSpinBox(w); self.autoRestMin.setRange(10, 3600); self.autoRestMin.setValue(30); self.autoRestMin.setFixedWidth(72)
        self.autoRestMax = QtWidgets.QSpinBox(w); self.autoRestMax.setRange(10, 3600); self.autoRestMax.setValue(90); self.autoRestMax.setFixedWidth(72)
        # 지역 간 휴식(초) — 전국 구단위 수백 요청 사이 간격. 0.3s 미만 연타 = IP 스로틀
        self.autoGapMin = QtWidgets.QDoubleSpinBox(w); self.autoGapMin.setRange(0.3, 10.0)
        self.autoGapMin.setDecimals(1); self.autoGapMin.setSingleStep(0.1)
        self.autoGapMin.setValue(0.4); self.autoGapMin.setFixedWidth(72)
        self.autoGapMax = QtWidgets.QDoubleSpinBox(w); self.autoGapMax.setRange(0.3, 10.0)
        self.autoGapMax.setDecimals(1); self.autoGapMax.setSingleStep(0.1)
        self.autoGapMax.setValue(1.2); self.autoGapMax.setFixedWidth(72)
        # min<=max 강제 — 뒤집힌 범위 입력 자체를 막는다
        for lo, hi in ((self.autoRestMin, self.autoRestMax), (self.autoGapMin, self.autoGapMax)):
            hi.setMinimum(lo.value()); lo.setMaximum(hi.value())
            lo.valueChanged.connect(hi.setMinimum)
            hi.valueChanged.connect(lo.setMaximum)
        self.autoRestMin.setToolTip("사이클(전국 1바퀴) 사이 랜덤 휴식. 10~3600초")
        self.autoRestMax.setToolTip("사이클(전국 1바퀴) 사이 랜덤 휴식. 10~3600초")
        self.autoGapMin.setToolTip("지역(구) 요청 사이 랜덤 휴식. 0.3~10.0초")
        self.autoGapMax.setToolTip("지역(구) 요청 사이 랜덤 휴식. 0.3~10.0초")
        # 레인 = 동시에 도는 수집 갈래. 프록시를 샤딩해 나눠 쓰므로 프록시 수를 넘을 수 없고,
        # 레인당 IP 가 3개 미만이면 빈응답 시 교체할 곳이 없어 오히려 느려진다.
        # 0 = 자동(프록시 수 ÷ 3). 실측: 레인4 = 순차 대비 2.5배, 매물 손실 0.
        self.autoLanes = QtWidgets.QSpinBox(w)
        self.autoLanes.setRange(0, 16); self.autoLanes.setValue(0)
        self.autoLanes.setSpecialValueText("자동"); self.autoLanes.setFixedWidth(72)
        self.autoLanes.setToolTip(
            "동시 수집 갈래(레인) 수. 0=자동(프록시 수 ÷ 3).\n"
            "레인은 프록시를 나눠 갖는다 — 같은 IP 로 동시요청하면 전부 빈응답이 된다.\n"
            "프록시가 부족하면 지정값보다 낮게 자동 조정된다.")
        self.autoTokenRefresh = QtWidgets.QCheckBox("토큰 갱신", w)
        self.autoTokenRefresh.setChecked(True)   # 기본 ON — LDPlayer 자동수확(제로컨피그)
        self.autoTokenRefresh.setToolTip(
            "체크 시 LDPlayer 정품앱이 갱신한 access 토큰을 자동 수확(WAF 우회). "
            "LDPlayer 실행+로그인 상태면 별도 설정 불필요.")
        self._notify = self._load_notify()
        self.auto_conditions = []

        # 슬림 필터 카드 (3줄)
        fc = QtWidgets.QGroupBox(w); fc.setTitle("")
        fv = QtWidgets.QVBoxLayout(fc); fv.setContentsMargins(14, 12, 14, 12); fv.setSpacing(8)
        r0 = QtWidgets.QHBoxLayout(); r0.setSpacing(8)
        r0.addWidget(self.autoKeyword, 3)
        r0.addWidget(self.autoMin); r0.addWidget(QtWidgets.QLabel("~")); r0.addWidget(self.autoMax)
        r1 = QtWidgets.QHBoxLayout(); r1.setSpacing(8)
        r1.addWidget(self.autoExtra, 1); r1.addWidget(self.autoExclude, 1)
        r1.addSpacing(10); r1.addWidget(self.autoTokenRefresh)
        r2 = QtWidgets.QHBoxLayout(); r2.setSpacing(8)
        r2.addWidget(QtWidgets.QLabel("끌올")); r2.addWidget(self.autoDays); r2.addWidget(QtWidgets.QLabel("일 이내"))
        r2.addSpacing(16)
        r2.addWidget(QtWidgets.QLabel("휴식")); r2.addWidget(self.autoRestMin)
        r2.addWidget(QtWidgets.QLabel("~")); r2.addWidget(self.autoRestMax); r2.addWidget(QtWidgets.QLabel("초"))
        r2.addSpacing(16)
        r2.addWidget(QtWidgets.QLabel("지역 간")); r2.addWidget(self.autoGapMin)
        r2.addWidget(QtWidgets.QLabel("~")); r2.addWidget(self.autoGapMax); r2.addWidget(QtWidgets.QLabel("초"))
        r2.addSpacing(16)
        r2.addWidget(QtWidgets.QLabel("레인")); r2.addWidget(self.autoLanes)
        r2.addStretch(1)
        fv.addLayout(r0); fv.addLayout(r1); fv.addLayout(r2)
        lay.addWidget(fc)

        # 액션 바 (한 줄)
        bar = QtWidgets.QHBoxLayout(); bar.setSpacing(8)
        self.autoExcelBtn = QtWidgets.QPushButton("엑셀 조건", w)
        self.autoExcelBtn.clicked.connect(self.on_auto_excel_clicked)
        self.autoNotifyBtn = QtWidgets.QPushButton("알림 설정", w)
        self.autoNotifyBtn.clicked.connect(self.on_auto_notify_clicked)
        self.autoAccountsBtn = QtWidgets.QPushButton("계정+프록시", w)
        self.autoAccountsBtn.clicked.connect(self.on_accounts_btn_clicked)
        self.autoProxyViewBtn = QtWidgets.QPushButton("프록시 목록", w)
        self.autoProxyViewBtn.clicked.connect(self.on_proxy_view_clicked)
        self.autoStartBtn = QtWidgets.QPushButton("자동 모니터 시작", w)
        self.autoStartBtn.setObjectName("autoStartBtn")
        self.autoStartBtn.clicked.connect(self.on_auto_start_clicked)
        for b in (self.autoExcelBtn, self.autoNotifyBtn, self.autoAccountsBtn,
                  self.autoProxyViewBtn, self.autoStartBtn):
            b.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed,
                            QtWidgets.QSizePolicy.Policy.Fixed)
        bar.addWidget(self.autoExcelBtn); bar.addWidget(self.autoNotifyBtn)
        bar.addWidget(self.autoAccountsBtn); bar.addWidget(self.autoProxyViewBtn)
        bar.addStretch(1); bar.addWidget(self.autoStartBtn)
        lay.addLayout(bar)

        # 상태 + 진행바
        self.autoStatus = QtWidgets.QLabel("대기 중", w)
        self.autoStatus.setStyleSheet("color:#8B95A1;")
        self.autoProgress = QtWidgets.QProgressBar(w)
        self.autoProgress.setRange(0, 0); self.autoProgress.setVisible(False)
        self.autoProgress.setMaximumHeight(6); self.autoProgress.setTextVisible(False)
        lay.addWidget(self.autoStatus)
        lay.addWidget(self.autoProgress)

        # 결과 테이블 (대형)
        self.autoTable = QtWidgets.QTableWidget(0, 5, w)
        self.autoTable.setHorizontalHeaderLabels(["지역", "제목", "가격", "끌올", "상태"])
        self.autoTable.verticalHeader().setVisible(False)
        self.autoTable.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.autoTable.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.autoTable.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.autoTable.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.autoTable.itemSelectionChanged.connect(self.on_auto_row_selected)
        self.autoTable.setMinimumHeight(340)
        self._auto_rows = []
        rl0 = QtWidgets.QLabel("검색 결과"); rl0.setStyleSheet("font-weight:800; color:#191F28; font-size:15px;")
        lay.addWidget(rl0)
        lay.addWidget(self.autoTable, 1)

        # 로그(작게)
        self.autoLog = QtWidgets.QTextEdit(w); self.autoLog.setReadOnly(True)
        self.autoLog.setMaximumHeight(96)
        lay.addWidget(self.autoLog, 0)

        # 우측: 상세 (수동과 동일)
        detail = QtWidgets.QWidget(w); dl = QtWidgets.QVBoxLayout(detail)
        dl.setContentsMargins(8, 4, 4, 4)
        dl.addWidget(QtWidgets.QLabel("상세", w))
        self.autoDetailImg = QtWidgets.QLabel(detail)
        self.autoDetailImg.setFixedSize(256, 256); self.autoDetailImg.setScaledContents(True)
        self.autoDetailView = QtWidgets.QTextBrowser(detail)
        self.autoDetailView.setOpenLinks(False)
        self.autoDetailView.anchorClicked.connect(lambda u: QDesktopServices.openUrl(u))
        dl.addWidget(self.autoDetailImg, 0, Qt.AlignmentFlag.AlignHCenter)
        dl.addWidget(self.autoDetailView, 1)
        split.addWidget(detail)
        split.setStretchFactor(0, 0); split.setStretchFactor(1, 1); split.setStretchFactor(2, 0)
        split.setSizes([240, 620, 300])
        return w

    def on_auto_status(self, text):
        self.autoStatus.setText(text)

    # ── 알림 설정 저장/불러오기 ──
    NOTIFY_FILE = "./notify.json"
    NOTIFY_DEFAULT = {"tg_token": "", "tg_chat": "", "sheet_url": "",
                      "sheet_cred": "./credentials.json"}

    def _load_notify(self):
        """notify.json 에서 알림 설정 복원. 없거나 깨졌으면 기본값."""
        cfg = dict(self.NOTIFY_DEFAULT)
        try:
            with open(self.NOTIFY_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                for k in cfg:
                    if isinstance(saved.get(k), str):
                        cfg[k] = saved[k]
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[알림설정 로드 실패] {type(e).__name__}: {e}")
        return cfg

    def _save_notify(self):
        """알림 설정 저장. 봇 토큰이 들어가므로 파일 권한 0600."""
        try:
            with open(self.NOTIFY_FILE, "w", encoding="utf-8") as f:
                json.dump(self._notify, f, ensure_ascii=False, indent=2)
            try:
                os.chmod(self.NOTIFY_FILE, 0o600)
            except OSError:
                pass
            return True, ""
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    def on_auto_notify_clicked(self):
        """알림 설정 다이얼로그 — 텔레그램/구글시트. 저장 지속 + 테스트 발송."""
        dlg = QtWidgets.QDialog(self); dlg.setWindowTitle("알림 설정"); dlg.resize(560, 300)
        v = QtWidgets.QVBoxLayout(dlg); f = QtWidgets.QFormLayout()
        tok = QtWidgets.QLineEdit(self._notify["tg_token"], dlg); tok.setPlaceholderText("텔레그램 봇 토큰 (예: 123456:AA...)")
        chat = QtWidgets.QLineEdit(self._notify["tg_chat"], dlg); chat.setPlaceholderText("chat_id / 방 (예: -1001234567890)")
        sheet = QtWidgets.QLineEdit(self._notify["sheet_url"], dlg); sheet.setPlaceholderText("구글시트 주소(선택)")
        cred = QtWidgets.QLineEdit(self._notify["sheet_cred"], dlg)
        cred.setPlaceholderText("구글 서비스계정 JSON 키 경로(시트 쓸 때만 필요)")
        credBtn = QtWidgets.QPushButton("찾기", dlg); credBtn.setFixedWidth(60)
        credRow = QtWidgets.QWidget(dlg); credLay = QtWidgets.QHBoxLayout(credRow)
        credLay.setContentsMargins(0, 0, 0, 0); credLay.setSpacing(6)
        credLay.addWidget(cred, 1); credLay.addWidget(credBtn)

        def pick_cred():
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                dlg, "서비스계정 JSON 키 선택", "", "JSON (*.json)")
            if path:
                cred.setText(path)
        credBtn.clicked.connect(pick_cred)

        f.addRow("텔레그램 토큰", tok); f.addRow("텔레그램 방", chat)
        f.addRow("구글시트", sheet); f.addRow("시트 인증파일", credRow)
        v.addLayout(f)
        v.addWidget(QtWidgets.QLabel("신규/가격변동 매물을 텔레그램·구글시트로 알림. 설정은 notify.json 에 저장됩니다.", dlg),
                    0, Qt.AlignmentFlag.AlignLeft)
        result = QtWidgets.QLabel("", dlg); result.setWordWrap(True)
        result.setStyleSheet("color:#8B95A1;")
        v.addWidget(result)

        bb = QtWidgets.QHBoxLayout()
        test = QtWidgets.QPushButton("테스트 발송", dlg)
        ok = QtWidgets.QPushButton("저장", dlg); ok.setObjectName("startBtn")
        cancel = QtWidgets.QPushButton("취소", dlg)
        bb.addWidget(test); bb.addStretch(1); bb.addWidget(cancel); bb.addWidget(ok)
        v.addLayout(bb)

        def collect():
            return {"tg_token": tok.text().strip(), "tg_chat": chat.text().strip(),
                    "sheet_url": sheet.text().strip(),
                    "sheet_cred": cred.text().strip() or "./credentials.json"}

        def on_test():
            cur = collect()
            if not (cur["tg_token"] and cur["tg_chat"]) and not cur["sheet_url"]:
                result.setText("⚠️ 텔레그램(토큰+방) 또는 구글시트 주소를 먼저 입력하세요.")
                return
            test.setEnabled(False); test.setText("보내는 중…")
            result.setStyleSheet("color:#8B95A1;")
            result.setText("전송 시도 중…")
            # 부모는 MainWindow — 다이얼로그가 먼저 닫혀도 실행 중 스레드가 삭제되지 않게
            self._notify_test = NotifyTestThread(self, cur)

            def done(res):
                try:
                    render(res)
                except RuntimeError:
                    pass            # 결과 도착 전 다이얼로그가 닫힌 경우

            def render(res):
                lines = []
                if cur["tg_token"] or cur["tg_chat"]:
                    lines.append(("✅ 텔레그램: " if res["tg_ok"] else "❌ 텔레그램: ")
                                 + res["tg_msg"])
                if res["sheet_ok"] is None:
                    if cur["sheet_url"]:
                        lines.append("❌ 구글시트: " + res["sheet_msg"])
                else:
                    lines.append(("✅ 구글시트: " if res["sheet_ok"] else "❌ 구글시트: ")
                                 + res["sheet_msg"])
                bad = (cur["tg_token"] and not res["tg_ok"]) or res["sheet_ok"] is False
                result.setStyleSheet("color:#E5484D;" if bad else "color:#128A6B;")
                result.setText("\n".join(lines) or "테스트할 항목 없음")
                test.setEnabled(True); test.setText("테스트 발송")
            self._notify_test.result.connect(done)
            self._notify_test.start()
        test.clicked.connect(on_test)

        def on_save():
            self._notify.update(collect())
            saved, err = self._save_notify()
            if not saved:
                self.alert(f"알림 설정 저장 실패 — {err}\n(이번 실행 동안만 적용됩니다)")
            dlg.accept()
        ok.clicked.connect(on_save)
        cancel.clicked.connect(dlg.reject)
        dlg.exec()

    def on_auto_found(self, item):
        r = self.autoTable.rowCount()
        self.autoTable.insertRow(r)
        try:
            price_txt = f"{int(item['price']):,}"
        except Exception:
            price_txt = str(item.get("price", ""))
        vals = [item.get("region", ""), item.get("title", ""), price_txt,
                str(item.get("boostedAt", ""))[:16], item.get("status", "")]
        for c, v in enumerate(vals):
            cell = QtWidgets.QTableWidgetItem(str(v))
            if item.get("status") == "가격변동":
                cell.setForeground(QtCore.Qt.GlobalColor.red)
            self.autoTable.setItem(r, c, cell)
        self._auto_rows.append(item)

    def on_auto_row_selected(self):
        rows = self.autoTable.selectionModel().selectedRows()
        if not rows:
            return
        i = rows[0].row()
        if i >= len(self._auto_rows):
            return
        it = self._auto_rows[i]
        from daangn.model import Product
        from daangn.detail import render_to_html
        try:
            b = datetime.fromisoformat(it["boostedAt"]) if it.get("boostedAt") else datetime.now()
        except Exception:
            b = datetime.now()
        p = Product(no=i + 1, name=it.get("title", ""), searched_keyword="",
                    price=str(it.get("price", "0")), priceCurrency="KRW",
                    description=it.get("desc", ""), image=it.get("image", ""),
                    url=it.get("url", ""), boostedAt=b, area=it.get("region", ""))
        self.autoDetailView.setHtml(render_to_html(p))
        self.autoDetailImg.clear()
        if it.get("image"):
            self._auto_img_thread = CancelableImageDownloader(self, it["image"], str(uuid4()))

            def _done(data, token):
                try:
                    img = PILImage.open(BytesIO(data))
                    img = image_contain_resize(img, (256, 256))
                    buf = BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
                    qp = QPixmap(); qp.loadFromData(buf.getvalue())
                    self.autoDetailImg.setPixmap(qp)
                except Exception:
                    pass
            self._auto_img_thread.finished.connect(_done)
            self._auto_img_thread.start()

    def _refresh_proxy_labels(self):
        n = len(self._collect_proxies())
        for attr in ("proxyViewBtn", "autoProxyViewBtn"):
            if hasattr(self, attr):
                getattr(self, attr).setText(f"프록시 목록 ({n})")

    @staticmethod
    def _mask_proxy(p: str) -> str:
        """비밀번호 마스킹 표시."""
        if "@" in p and "://" in p:
            scheme, rest = p.split("://", 1)
            if "@" in rest:
                cred, host = rest.split("@", 1)
                user = cred.split(":", 1)[0]
                return f"{scheme}://{user}:****@{host}"
        return p

    def _proxy_sources(self):
        """[(proxy, source)] — source 는 'settings' | 'account'."""
        rows = []
        seen = set()
        for p in self.controller.proxies:
            if p and p not in seen:
                seen.add(p)
                rows.append((p, "settings"))
        try:
            from daangn_ext import AccountStore
            for p in AccountStore("./accounts.json").proxies():
                if p and p not in seen:
                    seen.add(p)
                    rows.append((p, "account"))
        except Exception:
            pass
        return rows

    def on_proxy_view_clicked(self):
        dlg = QtWidgets.QDialog(self)
        dlg.resize(620, 440)
        v = QtWidgets.QVBoxLayout(dlg)

        info = QtWidgets.QLabel(parent=dlg)
        info.setWordWrap(True)
        v.addWidget(info)

        listw = QtWidgets.QListWidget(dlg)
        listw.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        v.addWidget(listw, 1)

        def reload_list():
            rows = self._proxy_sources()
            listw.clear()
            for proxy, src in rows:
                tag = "settings.txt" if src == "settings" else "계정저장소"
                item = QtWidgets.QListWidgetItem(
                    f"[{tag}] {self._mask_proxy(proxy)}")
                item.setData(Qt.ItemDataRole.UserRole, (proxy, src))
                listw.addItem(item)
            dlg.setWindowTitle(f"적용 프록시 {len(rows)}개")
            if rows:
                info.setText(
                    f"현재 적용 중인 프록시 {len(rows)}개 (settings.txt + 계정저장소). "
                    "여러 개 선택 후 삭제 가능.")
            else:
                info.setText(
                    "프록시 없음 — 아래 '추가' 버튼 또는 '계정+프록시 추가/관리' 사용")
            self._refresh_proxy_labels()
            self._update_window_title()

        def on_add():
            text, ok = QtWidgets.QInputDialog.getText(
                dlg, "프록시 추가", "프록시 주소 (여러 개는 줄바꿈/쉼표로 구분)",
                QtWidgets.QLineEdit.EchoMode.Normal,
                "http://user:pass@host:port")
            if not ok:
                return
            cands = [c.strip() for c in text.replace(",", "\n").splitlines()]
            cands = [c for c in cands if c]
            added, errs = 0, []
            for c in cands:
                if "://" not in c:
                    c = "http://" + c
                err = self.controller.add_proxy(c)
                if err:
                    errs.append(f"{self._mask_proxy(c)}: {err}")
                else:
                    added += 1
            reload_list()
            if errs:
                QtWidgets.QMessageBox.warning(
                    dlg, "일부 추가 실패",
                    f"{added}개 추가됨.\n\n" + "\n".join(errs))

        def on_del():
            items = listw.selectedItems()
            if not items:
                QtWidgets.QMessageBox.information(
                    dlg, "삭제", "삭제할 프록시를 선택하세요.")
                return
            picked = [it.data(Qt.ItemDataRole.UserRole) for it in items]
            names = "\n".join(self._mask_proxy(p) for p, _ in picked)
            if QtWidgets.QMessageBox.question(
                    dlg, "프록시 삭제",
                    f"{len(picked)}개 삭제할까요?\n\n{names}\n\n"
                    "계정저장소 항목은 계정은 남고 프록시 연결만 해제됩니다."
            ) != QtWidgets.QMessageBox.StandardButton.Yes:
                return

            errs = []
            acct_targets = [p for p, src in picked if src == "account"]
            for proxy, src in picked:
                if src == "settings":
                    err = self.controller.remove_proxy(proxy)
                    if err:
                        errs.append(f"{self._mask_proxy(proxy)}: {err}")
            if acct_targets:
                try:
                    from daangn_ext import AccountStore
                    store = AccountStore("./accounts.json")
                    for r in store.rows:
                        if r.get("proxy") in acct_targets:
                            r["proxy"] = None
                    store.save()
                except Exception as e:
                    errs.append(f"계정저장소 저장 실패: {e}")

            reload_list()
            if errs:
                QtWidgets.QMessageBox.warning(
                    dlg, "일부 삭제 실패", "\n".join(errs))

        btns = QtWidgets.QHBoxLayout()
        addBtn = QtWidgets.QPushButton("추가", dlg)
        addBtn.clicked.connect(on_add)
        delBtn = QtWidgets.QPushButton("삭제", dlg)
        delBtn.clicked.connect(on_del)
        closeBtn = QtWidgets.QPushButton("닫기", dlg)
        closeBtn.clicked.connect(dlg.accept)
        btns.addWidget(addBtn); btns.addWidget(delBtn)
        btns.addStretch(1); btns.addWidget(closeBtn)
        v.addLayout(btns)

        reload_list()
        dlg.exec()

    def _wrap(self, layout):
        c = QtWidgets.QWidget(self); c.setLayout(layout); return c

    EXCEL_COLS = ["대분류", "키워드", "추가키워드", "제외키워드", "최소금액", "최대금액", "끌올일수"]
    EXCEL_SAMPLE = [
        ["가방", "샤넬", "정품", "레플 미러", 500000, 3000000, 7],
        ["시계", "롤렉스", "", "레플", 1000000, "", 30],
        ["지갑", "루이비통", "", "", "", "", 14],
    ]

    def on_auto_excel_clicked(self):
        """엑셀 조건 — 형식 안내 팝업 + 샘플 저장 + 파일 불러오기."""
        from daangn.auto_monitor import load_conditions_from_excel
        dlg = QtWidgets.QDialog(self); dlg.setWindowTitle("엑셀 조건 불러오기"); dlg.resize(620, 400)
        v = QtWidgets.QVBoxLayout(dlg); v.setSpacing(10)
        v.addWidget(QtWidgets.QLabel(
            "여러 검색 조건을 엑셀로 한 번에 불러옵니다. 아래 형식으로 만드세요.\n"
            "키워드만 필수, 나머지는 선택. 추가/제외 키워드는 쉼표·공백 구분."))
        # 형식 표
        tbl = QtWidgets.QTableWidget(len(self.EXCEL_SAMPLE), len(self.EXCEL_COLS), dlg)
        tbl.setHorizontalHeaderLabels(self.EXCEL_COLS)
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        for r, row in enumerate(self.EXCEL_SAMPLE):
            for c, val in enumerate(row):
                tbl.setItem(r, c, QtWidgets.QTableWidgetItem(str(val)))
        tbl.resizeColumnsToContents()
        v.addWidget(tbl, 1)
        v.addWidget(QtWidgets.QLabel(
            "· 최소/최대금액 비우면 제한 없음  · 끌올일수 = 그 일수 이내 끌올된 매물만"))

        bb = QtWidgets.QHBoxLayout()
        sampleBtn = QtWidgets.QPushButton("샘플 엑셀 저장", dlg)
        loadBtn = QtWidgets.QPushButton("파일 선택해서 불러오기", dlg); loadBtn.setObjectName("startBtn")
        closeBtn = QtWidgets.QPushButton("닫기", dlg)
        bb.addWidget(sampleBtn); bb.addStretch(1); bb.addWidget(closeBtn); bb.addWidget(loadBtn)
        v.addLayout(bb)

        def do_sample():
            p, _ = QtWidgets.QFileDialog.getSaveFileName(
                dlg, "샘플 저장", "자동조건_샘플.xlsx", "Excel (*.xlsx)")
            if not p:
                return
            from openpyxl import Workbook
            wb = Workbook(); ws = wb.active; ws.title = "조건"
            ws.append(self.EXCEL_COLS)
            for row in self.EXCEL_SAMPLE:
                ws.append(row)
            wb.save(p)
            QtWidgets.QMessageBox.information(dlg, "저장됨", f"샘플 저장:\n{p}")

        def do_load():
            p, _ = QtWidgets.QFileDialog.getOpenFileName(
                dlg, "엑셀 조건 선택", "", "Excel (*.xlsx *.xlsm)")
            if not p:
                return
            try:
                self.auto_conditions = load_conditions_from_excel(p)
                cats = {c.get("category") or "-" for c in self.auto_conditions}
                self.autoLog.append(
                    f"[엑셀] 조건 {len(self.auto_conditions)}개 로드 (대분류 {len(cats)}종)")
                QtWidgets.QMessageBox.information(
                    dlg, "불러옴", f"조건 {len(self.auto_conditions)}개 로드됨.")
                dlg.accept()
            except Exception as e:
                QtWidgets.QMessageBox.warning(dlg, "오류", f"엑셀 로드 오류:\n{e}")

        sampleBtn.clicked.connect(do_sample)
        loadBtn.clicked.connect(do_load)
        closeBtn.clicked.connect(dlg.reject)
        dlg.exec()

    def _account_proxies(self):
        """accounts.json 프록시 — mtime 캐시 (자동 모니터가 구마다 호출하므로)."""
        path = "./accounts.json"
        try:
            st = os.stat(path)
            stamp = (st.st_mtime_ns, st.st_size)
        except OSError:
            self._acct_proxy_cache = (None, [])
            return []
        cached_stamp, cached = getattr(self, "_acct_proxy_cache", (None, []))
        if cached_stamp == stamp:
            return cached
        try:
            from daangn_ext import AccountStore
            proxies = AccountStore(path).proxies()
        except Exception:
            proxies = []
        self._acct_proxy_cache = (stamp, proxies)
        return proxies

    def _collect_proxies(self):
        """settings.txt 프록시 + 계정저장소 프록시 합침 → 자동 로테이션용."""
        proxies = list(self.controller.proxies) + self._account_proxies()
        return [p for p in dict.fromkeys(proxies) if p]

    def on_auto_start_clicked(self):
        from daangn.auto_monitor import AutoMonitor
        if self.auto_monitor and self.auto_monitor.isRunning():
            self.auto_monitor.stop()
            self.autoStartBtn.setText("정지 중…"); self.autoStartBtn.setEnabled(False)
            self.autoLog.append("[정지 요청] 진행 중 요청 마무리 후 정지 (최대 8초)…")

            def _finish():
                self.autoStartBtn.setText("자동 모니터 시작"); self.autoStartBtn.setEnabled(True)
                self.autoLog.append("[정지됨]")
            self.auto_monitor.finished.connect(_finish)
            return
        import re
        splt = lambda t: [x for x in re.split(r"[,\s]+", t.strip()) if x]
        if not self.auto_conditions and not self.autoKeyword.text().strip():
            self.alert("자동: 키워드 또는 엑셀 조건이 필요합니다")
            return
        # 초기 토큰은 워커스레드의 token_provider 가 획득(LDPlayer 부팅+수확은 오래 걸려
        # 메인스레드서 하면 GUI 프리징). 체크 시 provider 가 첫 사이클 시작서 확보.
        token = None
        cfg = {
            "conditions": self.auto_conditions or None,     # 엑셀 다중조건 우선
            "keyword": self.autoKeyword.text().strip(),
            "extra": splt(self.autoExtra.text()),
            "exclude": splt(self.autoExclude.text()),
            "min": int(self.autoMin.text()) if self.autoMin.text().strip().isdigit() else None,
            "max": int(self.autoMax.text()) if self.autoMax.text().strip().isdigit() else None,
            "days": self.autoDays.value() or None,
            "rest_min": self.autoRestMin.value(),
            "rest_max": self.autoRestMax.value(),
            "gap_min": self.autoGapMin.value(),
            "gap_max": self.autoGapMax.value(),
            "lanes": self.autoLanes.value(),        # 0 = 자동(프록시 수 기준)
            "tg_token": self._notify["tg_token"] or None,
            "tg_chat": self._notify["tg_chat"] or None,
            "sheet_url": self._notify["sheet_url"] or None,
            "sheet_cred": self._notify.get("sheet_cred") or "./credentials.json",
            "proxies": self._collect_proxies(),
            # 실행 중 프록시 추가/삭제 반영용 (조건 루프마다 재조회)
            "proxy_provider": self._collect_proxies,
            "access_token": token,
            # 사이클마다 최신 access 재조회(자동수확 연동). 스레드세이프(GUI 미접근).
            "token_provider": self._harvest_token_quiet if self.autoTokenRefresh.isChecked() else None,
            # 계정 안정화(밴회피): 사이클마다 계정 라운드로빈 + 계정별 고정프록시(없으면 KR네이티브)
            # + daily_cap/warmup. 수확 갱신 켜졌을 때 함께 활성(다계정 전제).
            "stabilize": self.autoTokenRefresh.isChecked(),
            "accounts_fp": "./accounts.json",
            "daily_cap": 300,
            "warmup_days": 3,
            "out_json": "./OUT.json",
            "db_path": "./auto_seen.db",
        }
        sel = self._selected_auto_regions()
        if sel:
            cfg["scope"] = "regions"; cfg["regions"] = sel
            self.autoLog.append(f"[지역] 선택 {len(sel)}개 동")
        else:
            cfg["scope"] = "nationwide"
            self.autoLog.append("[지역] 전국(동 단위)")
        self.auto_monitor = AutoMonitor(self, cfg)
        self.auto_monitor.log.connect(lambda m: (self.autoLog.append(m), print("[자동]", m)))
        self.auto_monitor.found.connect(self.on_auto_found)
        self.auto_monitor.status.connect(self.on_auto_status)
        self.auto_monitor.finished.connect(
            lambda: (self.autoProgress.setVisible(False),
                     self.autoStatus.setText("정지됨")))
        # 새 검색 = 결과 테이블 초기화 + 진행바 표시
        self.autoTable.setRowCount(0); self._auto_rows = []
        self.autoProgress.setVisible(True); self.autoStatus.setText("시작 중…")
        self.auto_monitor.start()
        self.autoStartBtn.setText("자동 모니터 정지")

    def _init_state(self):
        self.worker_thread: CancelableImageDownloader | None = None
        self.current_loaded_url: str | None = None
        self.current_download_task_token: str | None = None
        self.all_last_child: list[QtWidgets.QTreeWidgetItem] = []
        self.area_lookup: dict[str, list[tuple[str, str]]] = {}
        self.preview_image_size = (256, 256)

    def _setup_ui(self):
        self.ui.detailView.setReadOnly(True)
        # 링크 클릭 = 내부 이동(빈칸) 금지, 시스템 브라우저로 열기
        self.ui.detailView.setOpenLinks(False)
        self.ui.detailView.setOpenExternalLinks(False)
        self.ui.detailView.anchorClicked.connect(self._open_detail_link)
        self.sb: QtWidgets.QStatusBar = self.statusBar()  # type: ignore
        self._setup_health_indicator()

        for edit in (self.ui.minimumEdit, self.ui.maximumEdit):
            edit.setValidator(
                QRegularExpressionValidator(QRegularExpression("[0-9]*"), edit)
            )

        self.ui.prdImg.setScaledContents(True)
        self.ui.prdImg.setFixedSize(*self.preview_image_size)

        self._setup_extra_ui()

    def _setup_health_indicator(self):
        """상태바 우측 상시 표시 — 쓸 수 있는 IP 수 + 현재 요청간격(자동감속 반영).
        차단 대응은 전부 자동이라, 사용자에게 필요한 건 설정이 아니라 **지금 상태**다."""
        self.healthLabel = QtWidgets.QLabel("")
        self.healthLabel.setStyleSheet("color:#4E5968; font-size:12px;")
        self.healthBtn = QtWidgets.QPushButton("진단")
        self.healthBtn.setFixedHeight(24)
        self.healthBtn.setToolTip(
            "프록시를 IP 당 1회씩 찔러 '지금 막힌 건지, 막혔으면 어디가 문제인지' 판정")
        self.healthBtn.clicked.connect(self.on_health_check_clicked)
        self.sb.addPermanentWidget(self.healthLabel)
        self.sb.addPermanentWidget(self.healthBtn)
        self._health_thread = None
        self._health_timer = QtCore.QTimer(self)
        self._health_timer.timeout.connect(self._refresh_health_indicator)
        self._health_timer.start(2000)

    def _refresh_health_indicator(self):
        from daangn_ext import proxy_budget, throttle
        if not getattr(self, "controller", None):
            return
        try:
            pool = self._collect_proxies()
        except Exception:
            return
        st = proxy_budget.pool_status(pool)
        parts = [f"IP {st['alive']}/{st['total']}"]
        if st["cooling"]:
            parts[0] += f" (쿨다운 {st['cooling']}, {st['next_free_in']:.0f}초 후 해제)"
        parts.append(throttle.describe(self.controller.req_min_ms))
        self.healthLabel.setText("  ·  ".join(parts))

    def on_health_check_clicked(self):
        if self._health_thread and self._health_thread.isRunning():
            return
        pool = self._collect_proxies()
        if not pool and not self.ask("등록된 프록시가 없습니다. 직결 IP 만 진단할까요?"):
            return
        self.healthBtn.setEnabled(False)
        self.healthBtn.setText("진단 중…")
        self._health_thread = HealthCheckThread(self, pool)
        self._health_thread.progress.connect(
            lambda d, t: self.sb.showMessage(f"진단 중… {d}/{t}"))
        self._health_thread.result.connect(self._show_health_report)
        self._health_thread.start()

    def _show_health_report(self, res: dict):
        self.healthBtn.setEnabled(True)
        self.healthBtn.setText("진단")
        self._health_thread = None
        if res.get("error"):
            self.alert(f"진단 실패: {res['error']}")
            return
        from daangn_ext.health import report_text
        self.sb.showMessage(res["verdict"])
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("프록시 진단")
        dlg.resize(720, 520)
        v = QtWidgets.QVBoxLayout(dlg)
        head = QtWidgets.QLabel(f"판정: {res['verdict']}")
        head.setStyleSheet("font-weight:800; font-size:15px; color:#191F28;")
        act = QtWidgets.QLabel(f"대응: {res['action']}")
        act.setWordWrap(True)
        v.addWidget(head); v.addWidget(act)
        box = QtWidgets.QPlainTextEdit(report_text(res))
        box.setReadOnly(True)
        box.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        v.addWidget(box, 1)
        btn = QtWidgets.QPushButton("닫기"); btn.clicked.connect(dlg.accept)
        v.addWidget(btn, 0, Qt.AlignmentFlag.AlignRight)
        dlg.exec()

    def _open_detail_link(self, url: QUrl) -> None:
        """상세뷰 링크 = 시스템 브라우저로. 상대경로면 당근 도메인 부착."""
        if url.isRelative() or not url.scheme():
            url = QUrl("https://www.daangn.com" + url.toString())
        QDesktopServices.openUrl(url)

    def _setup_extra_ui(self):
        """추가기능 위젯 생성(배치는 _build_manual_tab 에서)."""
        self.extraEdit = QtWidgets.QLineEdit()
        self.extraEdit.setPlaceholderText("추가 키워드 (쉼표/공백 구분, 모두 포함)")
        self.excludeEdit = QtWidgets.QLineEdit()
        self.excludeEdit.setPlaceholderText("제외 키워드 (쉼표/공백 구분)")
        self.tokenRefreshCheck = QtWidgets.QCheckBox("검색 전 토큰 갱신")
        self.tokenRefreshCheck.setChecked(True)   # app-API 통일 → 토큰 필수 → 기본 ON(LDPlayer 자동수확)
        self.accountsBtn = QtWidgets.QPushButton("계정·프록시")
        self.accountsBtn.clicked.connect(self.on_accounts_btn_clicked)
        self.proxyViewBtn = QtWidgets.QPushButton("프록시 목록 보기")
        self.proxyViewBtn.clicked.connect(self.on_proxy_view_clicked)

    def _build_manual_tab(self):
        """수동 탭 — 자동 탭과 통일된 그룹박스 레이아웃. 클라 원본 위젯 재사용."""
        w = QtWidgets.QWidget(self)
        outer = QtWidgets.QHBoxLayout(w)
        outer.setContentsMargins(4, 4, 4, 4); outer.setSpacing(0)
        split = QtWidgets.QSplitter(Qt.Orientation.Horizontal, w)
        split.setChildrenCollapsible(False); split.setHandleWidth(6)
        outer.addWidget(split)

        # 좌: 지역 선택 (검색+전체선택 패널)
        self.ui.areaTree.setMinimumWidth(200)
        self.ui.areaTree.setHeaderLabel("지역 선택")
        split.addWidget(self._tree_panel(self.ui.areaTree, self.all_last_child))

        # 중앙: 슬림 필터바(2줄) + 대형 결과 테이블 + 하단 보조바
        center = QtWidgets.QWidget(w); cl = QtWidgets.QVBoxLayout(center)
        cl.setContentsMargins(8, 0, 8, 0); cl.setSpacing(10)

        self.ui.keywordEdit.setPlaceholderText("검색 키워드")
        self.ui.minimumEdit.setPlaceholderText("최소가"); self.ui.minimumEdit.setFixedWidth(96)
        self.ui.maximumEdit.setPlaceholderText("최대가"); self.ui.maximumEdit.setFixedWidth(96)
        self.ui.startBtn.setText("검색")
        self.tokenRefreshCheck.setText("토큰 갱신")

        fc = QtWidgets.QGroupBox(center); fc.setTitle("")
        fv = QtWidgets.QVBoxLayout(fc); fv.setContentsMargins(14, 12, 14, 12); fv.setSpacing(8)
        r0 = QtWidgets.QHBoxLayout(); r0.setSpacing(8)
        r0.addWidget(self.ui.keywordEdit, 3)
        r0.addWidget(self.ui.minimumEdit); r0.addWidget(QtWidgets.QLabel("~"))
        r0.addWidget(self.ui.maximumEdit); r0.addWidget(self.ui.startBtn)
        r1 = QtWidgets.QHBoxLayout(); r1.setSpacing(8)
        r1.addWidget(self.extraEdit, 1); r1.addWidget(self.excludeEdit, 1)
        r1.addSpacing(10)
        r1.addWidget(self.ui.onlyTradeableCheck); r1.addSpacing(18)
        r1.addWidget(self.tokenRefreshCheck)
        fv.addLayout(r0); fv.addLayout(r1)
        cl.addWidget(fc)

        hdr = QtWidgets.QHBoxLayout()
        rl0 = QtWidgets.QLabel("검색 결과"); rl0.setStyleSheet("font-weight:800; color:#191F28; font-size:15px;")
        hdr.addWidget(rl0); hdr.addStretch(1)
        cl.addLayout(hdr)
        self.ui.itemListView.setMinimumHeight(360)
        cl.addWidget(self.ui.itemListView, 1)

        # 하단 보조 바
        self.ui.saveToExcelBtn.setText("엑셀 저장")
        self.ui.crawlFromExcelBtn.setText("엑셀 크롤링")
        sb = QtWidgets.QHBoxLayout(); sb.setSpacing(8)
        for b in (self.ui.saveToExcelBtn, self.ui.crawlFromExcelBtn,
                  self.accountsBtn, self.proxyViewBtn):
            b.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed,
                            QtWidgets.QSizePolicy.Policy.Fixed)
        sb.addWidget(self.ui.saveToExcelBtn); sb.addWidget(self.ui.crawlFromExcelBtn)
        sb.addWidget(self.accountsBtn); sb.addStretch(1); sb.addWidget(self.proxyViewBtn)
        cl.addLayout(sb)
        split.addWidget(center)

        # 우: 상세
        right = QtWidgets.QWidget(w); rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        rl.addWidget(QtWidgets.QLabel("상세"))
        rl.addWidget(self.ui.prdImg, 0, Qt.AlignmentFlag.AlignHCenter)
        rl.addWidget(self.ui.detailView, 1)
        split.addWidget(right)
        split.setStretchFactor(0, 0); split.setStretchFactor(1, 1); split.setStretchFactor(2, 0)
        split.setSizes([240, 640, 300])
        return w

    def _setup_model(self):
        self.products_model = self.controller.create_model(self)
        header = self.ui.itemListView.horizontalHeader()
        header.setSortIndicator(0, Qt.SortOrder.AscendingOrder)  # type: ignore
        self.ui.itemListView.setSortingEnabled(True)
        self.ui.itemListView.setModel(self.products_model)

    def _connect_signals(self):
        self.ui.startBtn.clicked.connect(self.on_start_btn_clicked)
        self.ui.crawlFromExcelBtn.clicked.connect(self.crawl_from_excel)
        self.ui.saveToExcelBtn.clicked.connect(self.save_to_excel)

        selection_model = self.ui.itemListView.selectionModel()
        assert selection_model
        selection_model.selectionChanged.connect(self.on_select_prd)

        self.controller.task_error.connect(self._handle_task_error)
        self.controller.task_finished.connect(self._handle_task_finished)
        self.controller.task_message.connect(self._handle_task_message)

    def _update_window_title(self):
        self.setWindowTitle(self.controller.status_summary())

    def _load_proxy(self):
        err = self.controller.load_proxy_settings()
        if err:
            self.alert(err)
        self._update_window_title()

    def _init_tree(self):
        self.all_last_child.clear()
        self.area_lookup = {}
        with open("./OUT.json", "r", encoding="utf8") as f:
            AREA_DATA = json.loads(f.read())

        AREA_ROOT: dict[str, list[Any]] = {}
        for area in AREA_DATA:
            lis = AREA_ROOT.setdefault(area["name1"], [])
            lis.append(area)

        tree_root = QtWidgets.QTreeWidgetItem(self.ui.areaTree)
        tree_root.setText(0, "지역")
        tree_root.setFlags(
            tree_root.flags()
            | Qt.ItemFlag.ItemIsAutoTristate
            | Qt.ItemFlag.ItemIsUserCheckable
        )
        tree_root.setCheckState(0, Qt.CheckState.Unchecked)

        all_locations: list[tuple[str, str]] = []

        for sido in AREA_ROOT:
            parent = QtWidgets.QTreeWidgetItem(tree_root)
            parent.setText(0, f"{sido}")
            parent.setFlags(
                parent.flags()
                | Qt.ItemFlag.ItemIsAutoTristate
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            parent.setCheckState(0, Qt.CheckState.Unchecked)

            sido_locations: list[tuple[str, str]] = []

            for area in AREA_ROOT[sido]:
                name1 = area["name1"] or ""
                name2 = area["name2"] or ""
                child1_txt = f"{name1} {name2}".strip()

                child1 = QtWidgets.QTreeWidgetItem(parent)
                child1.setText(0, child1_txt)
                child1.setFlags(
                    child1.flags()
                    | Qt.ItemFlag.ItemIsAutoTristate
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                child1.setCheckState(0, Qt.CheckState.Unchecked)

                area_locations: list[tuple[str, str]] = []

                for loc in area["locations"]:
                    child2 = QtWidgets.QTreeWidgetItem(child1)
                    child2.setFlags(child2.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    child2.setText(0, f"{child1_txt} {loc['name']}".strip())
                    child2.setData(
                        0, Qt.ItemDataRole.UserRole, f"{loc['name']}-{loc['id']}"
                    )
                    child2.setCheckState(0, Qt.CheckState.Unchecked)
                    self.all_last_child.append(child2)

                    location_entry = (
                        child2.text(0),
                        child2.data(0, Qt.ItemDataRole.UserRole),
                    )
                    area_locations.append(location_entry)
                    sido_locations.append(location_entry)
                    all_locations.append(location_entry)

                    self._register_area_mapping(child2.text(0), [location_entry])
                    self._register_area_mapping(str(loc["id"]), [location_entry])

                self._register_area_mapping(child1_txt, area_locations)

            self._register_area_mapping(sido, sido_locations)

        self._register_area_mapping("전국", all_locations)

    def _register_area_mapping(
        self, key: str, locations: list[tuple[str, str]]
    ) -> None:
        if not key or not locations:
            return

        existing = self.area_lookup.setdefault(key, [])
        existing_codes = {code for _, code in existing}
        for name, code in locations:
            if code not in existing_codes:
                existing.append((name, code))
                existing_codes.add(code)

    def _enter_task(self):
        self.ui.startBtn.setText("정지")
        self.ui.crawlFromExcelBtn.setEnabled(False)
        self.ui.saveToExcelBtn.setEnabled(False)

    def _leave_task(self):
        self.ui.startBtn.setText("시작")
        self.ui.crawlFromExcelBtn.setEnabled(True)
        self.ui.saveToExcelBtn.setEnabled(True)

    def alert(self, text: str):
        message_box = QtWidgets.QMessageBox(self)
        message_box.setWindowIcon(app_icon())
        message_box.setWindowTitle("알림")
        message_box.setText(text)
        message_box.setIcon(QtWidgets.QMessageBox.Icon.Information)
        message_box.exec()

    def ask(self, text: str):
        reply = QtWidgets.QMessageBox(self)
        reply.setWindowIcon(app_icon())
        reply.setWindowTitle("알림")
        reply.setText(text)
        reply.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No
        )

        return reply.exec() == QtWidgets.QMessageBox.StandardButton.Yes

    def on_start_btn_clicked(self):
        # if stop btn
        if self.controller.is_task_running():
            if self.controller.is_task_stopping():
                self.alert("이미 정지하고 있습니다")
                return
            if not self.ask("정지 하시겠습니까?"):
                return
            self.controller.stop_task()
            return

        onlyTradeable = self.ui.onlyTradeableCheck.isChecked()
        keyword = self.ui.keywordEdit.text()
        minimum = int(val) if (val := self.ui.minimumEdit.text().strip()) else None
        maximum = int(val) if (val := self.ui.maximumEdit.text().strip()) else None

        if not keyword:
            self.alert("키워드가 비어있습니다")
            return

        if minimum is not None and maximum is not None:
            if int(minimum) > int(maximum):
                self.alert("최대 가격이 더 큽니다")
                return

        area_id_list = []
        for ch in self.all_last_child:
            if ch.checkState(0) == Qt.CheckState.Checked:
                area_id_list.append((ch.text(0), ch.data(0, Qt.ItemDataRole.UserRole)))

        if not area_id_list:
            self.alert("선택된 지역이 없습니다")
            return

        ok = self.ask(
            f"{len(area_id_list)}개 지역에서 검색을 시작합니다.\n키워드: {keyword}"
        )
        if not ok:
            return

        # 추가/제외 키워드 파싱
        def split_kw(text):
            import re
            return [k for k in re.split(r"[,\s]+", text.strip()) if k]
        extra = split_kw(self.extraEdit.text())
        exclude = split_kw(self.excludeEdit.text())
        # 앱API 통일: 수동도 항상 app-API(search-bff) 경로. 웹크롤(robust_fetch) 폐지.
        # (체크박스와 무관하게 True — 자동/수동 동일 데이터소스)
        adaptive = True

        # 검색 전 토큰 갱신(옵션)
        access_token = None
        if self.tokenRefreshCheck.isChecked():
            access_token = self._refresh_tokens()

        self._enter_task()
        self.clearItemList()

        try:
            tasks = [
                CrawlTask(
                    area=area,
                    keyword=keyword,
                    only_tradeable=onlyTradeable,
                    minimum=minimum,
                    maximum=maximum,
                    extra_keywords=extra,
                    exclude_keywords=exclude,
                    adaptive=adaptive,
                    access_token=access_token,
                )
                for area in area_id_list
            ]
            self.controller.start_task(tasks)
        except Exception as e:
            self._leave_task()
            self.alert(str(e))

    def _harvest_token_quiet(self) -> str | None:
        """스레드세이프 토큰 provider — AutoMonitor 스레드서 사이클마다 호출.
        GUI 미접근(showMessage/alert 금지). LDPlayer 수확 → 최신 access 반환."""
        import json as _json
        try:
            import ld_autoharvest
            ld_autoharvest.harvest_all("./accounts.json", nudge=True)
        except Exception:
            pass
        try:
            from daangn_ext.token_manager import token_exp
            best = None
            for a in _json.load(open("./accounts.json", encoding="utf-8")):
                acc = a.get("access") or ""
                if acc and (best is None or token_exp(acc) > token_exp(best)):
                    best = acc
            return best
        except Exception:
            return None

    def _refresh_tokens(self) -> str | None:
        """검색 전 access 토큰 확보. LDPlayer 온디바이스 수확 우선(WAF 우회),
        실패 시 기존 HTTP refresh 폴백. 최신 access 반환."""
        import json as _json
        # 1) LDPlayer 온디바이스 수확 — 정품 앱이 갱신한 access 를 su 로 직접 읽어 accounts.json 병합.
        #    HTTP refresh(api.kr.karrotmarket.com)는 WAF 403 이라 이 경로가 실질 갱신책.
        try:
            import ld_autoharvest
            ld_autoharvest.harvest_all(
                "./accounts.json", nudge=True,
                log=lambda m: self.sb.showMessage(m, 4000))
        except Exception as e:
            self.sb.showMessage(f"[수확 건너뜀] {str(e)[:60]}", 4000)
        # 2) accounts.json 에서 남은 수명이 가장 긴 access 반환
        try:
            from daangn_ext.token_manager import token_exp
            best = None
            for a in _json.load(open("./accounts.json", encoding="utf-8")):
                acc = a.get("access") or ""
                if acc and (best is None or token_exp(acc) > token_exp(best)):
                    best = acc
            if best:
                return best
        except Exception:
            pass
        # 3) 폴백: 기존 HTTP refresh (LDPlayer 없음/수확실패 시. WAF면 실패할 수 있음)
        try:
            from daangn_ext import TokenManager, AccountStore, bind_to_token_manager
            store = AccountStore("./accounts.json")
            if not store.rows:
                self.alert("계정 없음. LDPlayer 를 켜거나 '계정+프록시 추가'로 등록하세요.")
                return None
            tm = TokenManager()
            bind_to_token_manager(store, tm)
            tm.refresh_all()
            accs = list(tm.accounts.values())
            return tm.ensure_safe(accs[0]) if accs else None
        except Exception as e:
            self.alert(f"토큰 갱신 오류: {e}")
            return None

    def on_accounts_btn_clicked(self):
        """계정+프록시 추가/관리 다이얼로그."""
        from daangn_ext import AccountStore
        store = AccountStore("./accounts.json")
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("계정 + 프록시 관리")
        dlg.resize(520, 360)
        v = QtWidgets.QVBoxLayout(dlg)

        listw = QtWidgets.QListWidget(dlg)
        def reload_list():
            listw.clear()
            for r in store.rows:
                listw.addItem(f"{r.get('label') or '(무명)'}  |  {r.get('proxy') or '프록시없음'}")
        reload_list()
        v.addWidget(QtWidgets.QLabel("등록된 계정", parent=dlg))
        v.addWidget(listw)

        form = QtWidgets.QFormLayout()
        labelEdit = QtWidgets.QLineEdit(dlg); labelEdit.setPlaceholderText("별칭/전화 (선택)")
        refreshEdit = QtWidgets.QLineEdit(dlg); refreshEdit.setPlaceholderText("refresh 토큰 (JWT)")
        proxyEdit = QtWidgets.QLineEdit(dlg); proxyEdit.setPlaceholderText("http://user:pass@host:port")
        form.addRow("별칭", labelEdit)
        form.addRow("refresh 토큰", refreshEdit)
        form.addRow("프록시", proxyEdit)
        v.addLayout(form)

        btns = QtWidgets.QHBoxLayout()
        addBtn = QtWidgets.QPushButton("추가", dlg)
        delBtn = QtWidgets.QPushButton("선택 삭제", dlg)
        closeBtn = QtWidgets.QPushButton("닫기", dlg)
        btns.addWidget(addBtn); btns.addWidget(delBtn); btns.addStretch(1); btns.addWidget(closeBtn)
        v.addLayout(btns)

        def do_add():
            rf = refreshEdit.text().strip()
            if not rf:
                QtWidgets.QMessageBox.warning(dlg, "확인", "refresh 토큰을 입력하세요.")
                return
            store.add_pair(refresh=rf, proxy=proxyEdit.text().strip() or None,
                           label=labelEdit.text().strip())
            labelEdit.clear(); refreshEdit.clear(); proxyEdit.clear()
            reload_list()
        def do_del():
            i = listw.currentRow()
            if 0 <= i < len(store.rows):
                r = store.rows[i]
                store.remove(r.get("refresh") or r.get("label"))
                reload_list()
        addBtn.clicked.connect(do_add)
        delBtn.clicked.connect(do_del)
        closeBtn.clicked.connect(dlg.accept)
        dlg.exec()

    def crawl_from_excel(self):
        if self.controller.is_task_running():
            self.alert("작업이 진행 중입니다")
            return

        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, caption="엑셀 파일 선택", filter="*.xlsx"
        )
        if not path:
            return

        try:
            tasks, errors = self._read_excel_tasks(path)
        except Exception as e:
            self.alert(f"엑셀 파일을 읽는 중 오류가 발생했습니다\n{e}")
            return

        if errors:
            preview = "\n".join(errors[:5])
            if len(errors) > 5:
                preview += f"\n... 총 {len(errors)}개 행에서 오류가 발생했습니다"
            self.alert(preview)
            return

        if not tasks:
            self.alert("엑셀에 유효한 검색 조건이 없습니다")
            return

        self._enter_task()
        self.clearItemList()

        try:
            tradeable = self.ui.onlyTradeableCheck.isChecked()
            requests = []
            for task in tasks:
                for area in task["areas"]:
                    requests.append(
                        CrawlTask(
                            area=area,
                            keyword=task["keyword"],
                            only_tradeable=tradeable,
                            minimum=task["minimum"],
                            maximum=task["maximum"],
                        )
                    )
            self.controller.start_task(requests)
        except Exception as e:
            self._leave_task()
            self.alert(str(e))

    def _read_excel_tasks(self, path: str) -> tuple[list[dict[str, Any]], list[str]]:
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))  # type: ignore
        finally:
            wb.close()

        if not rows:
            return [], ["엑셀에 데이터가 없습니다"]

        header_map: dict[str, int] = {}
        for idx, value in enumerate(rows[0]):
            mapped = self.EXCEL_HEADER_ALIASES.get(str(value))
            if mapped and mapped not in header_map:
                header_map[mapped] = idx

        required = {"area", "keyword"}
        missing = required - header_map.keys()
        if missing:
            return [], [f"엑셀에 다음 열이 필요합니다: {', '.join(sorted(missing))}"]

        area_idx = header_map["area"]
        keyword_idx = header_map["keyword"]
        minimum_idx = header_map.get("minimum")
        maximum_idx = header_map.get("maximum")

        errors: list[str] = []
        tasks: list[dict[str, Any]] = []

        def row_value(row: tuple[Any, ...], idx: int | None):
            if idx is None or idx >= len(row):
                return None
            return row[idx]

        for row_idx, row in enumerate(rows[1:], start=2):
            area_raw = row_value(row, area_idx)
            keyword_raw = row_value(row, keyword_idx)

            # skip blank rows
            if not any(
                (
                    area_raw,
                    keyword_raw,
                    row_value(row, minimum_idx),
                    row_value(row, maximum_idx),
                )
            ):
                continue

            area_text = str(area_raw).strip() if area_raw is not None else ""
            keyword = str(keyword_raw).strip() if keyword_raw is not None else ""

            if not area_text:
                errors.append(f"{row_idx}행: 지역이 비어있습니다")
                continue

            if not keyword:
                errors.append(f"{row_idx}행: 키워드가 비어있습니다")
                continue

            area_tokens = [
                token.strip() for token in area_text.split(",") if token.strip()
            ]
            combined_areas: list[tuple[str, str]] = []
            missing_tokens: list[str] = []
            seen_codes: set[str] = set()

            for token in area_tokens:
                resolved = self._resolve_area_entry(token)
                if not resolved:
                    missing_tokens.append(token)
                    continue

                for entry in resolved:
                    if entry[1] not in seen_codes:
                        combined_areas.append(entry)
                        seen_codes.add(entry[1])

            if missing_tokens:
                errors.append(
                    f"{row_idx}행: 다음 지역을 찾을 수 없습니다 - {', '.join(missing_tokens)}"
                )
                continue

            if not combined_areas:
                errors.append(f"{row_idx}행: '{area_text}' 지역을 찾을 수 없습니다")
                continue

            try:
                minimum = (
                    self._parse_price_value(row_value(row, minimum_idx))
                    if minimum_idx is not None
                    else None
                )
            except ValueError:
                errors.append(f"{row_idx}행: 최소가격을 숫자로 변환할 수 없습니다")
                continue

            try:
                maximum = (
                    self._parse_price_value(row_value(row, maximum_idx))
                    if maximum_idx is not None
                    else None
                )
            except ValueError:
                errors.append(f"{row_idx}행: 최대가격을 숫자로 변환할 수 없습니다")
                continue

            if minimum is not None and maximum is not None and minimum > maximum:
                errors.append(f"{row_idx}행: 최소가격이 최대가격보다 큽니다")
                continue

            tasks.append(
                {
                    "areas": combined_areas,
                    "keyword": keyword,
                    "minimum": minimum,
                    "maximum": maximum,
                }
            )

        return tasks, errors

    def _resolve_area_entry(self, area_text: str) -> list[tuple[str, str]]:
        return self.area_lookup.get(area_text, [])

    def _parse_price_value(self, raw: Any) -> int | None:
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            return int(raw)
        text = str(raw).strip()
        if not text:
            return None
        text = text.replace(",", "")
        return int(float(text))

    def _prompt_recent_days_filter(self) -> tuple[bool, int | None]:
        while True:
            days_text, ok = QtWidgets.QInputDialog.getText(
                self,
                "필터링",
                "최근 며칠 이내의 상품만 저장할까요?\n(비워두면 전체 저장)",
            )
            if not ok:
                return False, None

            days_text = days_text.strip()
            if not days_text:
                return True, None

            try:
                days = int(days_text)
                if days <= 0:
                    raise ValueError
                return True, days
            except ValueError:
                self.alert("1 이상의 숫자를 입력해주세요.")

    def _filter_recent_products(
        self, products: list[Product], days: int | None
    ) -> list[Product]:
        if days is None:
            return products

        cutoff = datetime.now() - timedelta(days=days)
        return [prd for prd in products if prd.boostedAt >= cutoff]

    def on_select_prd(self, selected: QItemSelection, deselected: QItemSelection):
        prev_row = None
        prev_indexes = deselected.indexes()
        if prev_indexes:
            prev_row = prev_indexes[0].row()

        indexes = selected.indexes()
        if not indexes:
            return

        curr_row = indexes[0].row()

        if prev_row == curr_row:
            return

        curr_id = self.products_model.data(self.products_model.index(curr_row, 0))

        prd = self.controller.get_product_by_id(curr_id)
        if prd:
            self.load_detail(prd)
        else:
            self.alert("상품 정보를 불러오지 못했습니다")

    def load_detail(self, prd: Product):
        if self.current_loaded_url == prd.url:
            return
        self.current_loaded_url = prd.url

        document = self.ui.detailView.document()
        if document:
            self.ui.detailView.setHtml(render_to_html(prd))

        self.current_download_task_token = str(uuid4())

        if self.worker_thread is not None:
            self.worker_thread.cancel()

        if not prd.image:
            self.ui.prdImg.clear()
            return

        self.worker_thread = CancelableImageDownloader(
            self, prd.image, self.current_download_task_token
        )

        def on_download_finished(data: bytes, token: str):
            if token != self.current_download_task_token:
                return

            try:
                pil_img = PILImage.open(BytesIO(data))
                normalized = image_contain_resize(pil_img, self.preview_image_size)

                buffer = BytesIO()
                normalized.save(buffer, format="PNG")
                buffer.seek(0)

                qp = QPixmap()
                qp.loadFromData(buffer.getvalue())
                self.ui.prdImg.setPixmap(qp)
            except Exception:
                self.alert("이미지 로딩 오류")

        def on_download_failed(token: str):
            if token != self.current_download_task_token:
                return

            self.alert("이미지 다운로드 오류")

        self.worker_thread.finished.connect(on_download_finished)
        self.worker_thread.failed.connect(on_download_failed)
        self.worker_thread.start()

    def save_to_excel(self):
        if self.controller.is_task_running():
            self.alert("작업이 진행 중입니다")
            return

        products = list(self.controller.get_current_data())

        if not products:
            self.alert("크롤링된 상품이 없습니다")
            return

        proceed, recent_days = self._prompt_recent_days_filter()
        if not proceed:
            return

        filtered_products = self._filter_recent_products(products, recent_days)
        if not filtered_products:
            self.alert("조건에 맞는 상품이 없습니다")
            return

        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, filter="*.xlsx")
        if not path:
            return

        yesno = self.ask("이미지도 저장을 하시겠습니까?")
        export = ExportExcel(self, path, filtered_products, yesno)
        dlg = MyProgressDialog("저장 중", "취소", 0, 0, self)
        dlg.setWindowModality(Qt.WindowModality.ApplicationModal)

        dlg.canceled.disconnect()
        dlg.canceled.connect(lambda: export.cancel())

        def on_finished(success: bool):
            dlg.close()

            if export.cancelled:
                return

            if success:
                self.alert("저장되었습니다")
                try:
                    os.startfile(os.path.dirname(path))  # type: ignore
                except Exception:
                    pass
            else:
                self.alert("저장 중 오류")

        export.finished.connect(on_finished)
        export.start()

        dlg.show()

    def closeEvent(self, ev: QCloseEvent) -> None:  # type: ignore
        running = self.controller.is_task_running()
        prompt = (
            "작업이 진행 중입니다.\n정지하고 종료하시겠습니까?"
            if running
            else "종료 하시겠습니까?"
        )
        if not self.ask(prompt):
            ev.ignore()
            return

        if running:
            if not self.controller.is_task_stopping():
                self.controller.stop_task()
            task = self.controller.task
            if task is not None and task.isRunning():
                if not task.wait(8000):
                    task.terminate()
                    task.wait(2000)

        # 종료 전 실행 중인 QThread 정리 (미정리 시 SIGABRT)
        if self.auto_monitor is not None and self.auto_monitor.isRunning():
            self.auto_monitor.stop()
            if not self.auto_monitor.wait(3000):
                self.auto_monitor.terminate()
                self.auto_monitor.wait(2000)
        if self.worker_thread is not None and self.worker_thread.isRunning():
            self.worker_thread.cancel()
            self.worker_thread.wait(3000)

    def clearItemList(self):
        self.controller.clear_products()

    def _handle_task_error(self):
        self._leave_task()
        self.alert("작업 중 오류\nERROR_LOG 파일에 오류가 저장되었습니다")

    def _handle_task_finished(self):
        self.alert("작업이 정지되었습니다")
        self._leave_task()

    def _handle_task_message(self, msg: str):
        self.sb.showMessage(msg)


ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
FONT_DIR = os.path.join(ASSET_DIR, "fonts")
APP_ICON_PATH = os.path.join(ASSET_DIR, "icon.png")


def app_icon() -> QtGui.QIcon:
    """명품 앱 아이콘. 없으면 빈 QIcon(기본 로켓 대신 Qt 기본)."""
    return QtGui.QIcon(APP_ICON_PATH) if os.path.isfile(APP_ICON_PATH) else QtGui.QIcon()


def load_bundled_fonts() -> list[str]:
    """번들 Pretendard 등록. 미설치 환경에서도 QSS font-family 가 먹도록."""
    families: list[str] = []
    if not os.path.isdir(FONT_DIR):
        return families
    for name in sorted(os.listdir(FONT_DIR)):
        if not name.lower().endswith((".otf", ".ttf")):
            continue
        fid = QFontDatabase.addApplicationFont(os.path.join(FONT_DIR, name))
        if fid != -1:
            families.extend(QFontDatabase.applicationFontFamilies(fid))
    return families


def _setup_logging():
    """exe 옆 karrot_monitor.log 에 stdout/stderr + 모든 미처리 예외 기록(원격 디버깅용)."""
    import sys as _sys, os as _os, traceback as _tb, datetime as _dt
    base = _os.path.dirname(_sys.executable) if getattr(_sys, "frozen", False) \
        else _os.path.dirname(_os.path.abspath(__file__))
    try:
        logf = open(_os.path.join(base, "karrot_monitor.log"), "a",
                    encoding="utf-8", buffering=1)
    except Exception:
        return
    def stamp():
        return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logf.write(f"\n===== 시작 {stamp()} =====\n")

    class _Tee:
        def __init__(self, *s): self.s = [x for x in s if x]
        def write(self, d):
            for x in self.s:
                try: x.write(d)
                except Exception: pass
        def flush(self):
            for x in self.s:
                try: x.flush()
                except Exception: pass
    _sys.stdout = _Tee(_sys.__stdout__, logf)
    _sys.stderr = _Tee(_sys.__stderr__, logf)

    def _hook(et, ev, tb):
        logf.write(f"[{stamp()}] 미처리 예외:\n"
                   + "".join(_tb.format_exception(et, ev, tb)) + "\n")
        logf.flush()
    _sys.excepthook = _hook
    try:
        import threading as _th
        def _thook(a):
            logf.write(f"[{stamp()}] 스레드 예외:\n"
                       + "".join(_tb.format_exception(a.exc_type, a.exc_value, a.exc_traceback)) + "\n")
            logf.flush()
        _th.excepthook = _thook
    except Exception:
        pass
    print(f"[로그] {logf.name}")


if __name__ == "__main__":
    _setup_logging()
    try:
        app = QApplication([])
        app.setWindowIcon(app_icon())   # Dock/작업표시줄/팝업 전부 명품 아이콘
        load_bundled_fonts()
        window = MainWindow()
        window.show()
        app.exec()
    except Exception:
        import traceback
        traceback.print_exc()   # _Tee 로 로그파일에도 기록됨
        raise

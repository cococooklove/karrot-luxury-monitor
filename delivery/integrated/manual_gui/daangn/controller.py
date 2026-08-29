from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtSql import QSqlDatabase, QSqlQuery

from daangn.model import Product
from daangn.ui import MySqlQueryModel
from daangn.workers import CrawlThread
from daangn.task import CrawlTask


class MainController(QObject):
    task_error = pyqtSignal()
    task_finished = pyqtSignal()
    task_message = pyqtSignal(str)

    def __init__(
        self, parent: QObject | None = None, settings_path: str = "./settings.txt"
    ):
        super().__init__(parent)
        self.settings_path = settings_path

        self.db = QSqlDatabase.addDatabase("QSQLITE")
        self.db.setDatabaseName(":memory:")
        self.db_ready = self.db.open()
        self.db_error = None if self.db_ready else self.db.lastError().text()

        self.req_min_ms = 1000
        self.max_workers = 16
        self.proxies: list[str] = []

        self.model: MySqlQueryModel | None = None
        self.task: CrawlThread | None = None

    def get_current_data(self) -> list[Product]:
        return self.model.sorted_products() if self.model else []

    def is_ready(self) -> bool:
        return self.db_ready

    def create_model(self, parent) -> MySqlQueryModel:
        self.model = MySqlQueryModel(parent, self.db)
        return self.model

    def clear_products(self):
        if self.model:
            self.model.clear_all()

    def load_proxy_settings(self) -> str | None:
        import os
        if not os.path.exists(self.settings_path):
            # 파일 없음 = 프록시 미사용(정상). 모달 띄우지 않고 기본값.
            self.req_min_ms = 1000
            self.max_workers = 16
            self.proxies = []
            return None
        try:
            with open(self.settings_path, "r") as f:
                data = f.read().strip()

            lines = data.splitlines()
            self.req_min_ms = int(lines[0])
            self.max_workers = int(lines[1])
            self.proxies = lines[2:]
            return None
        except Exception as e:
            self.req_min_ms = 1000
            self.max_workers = 16
            self.proxies = []
            return f"프록시 로드 오류 {e}"

    def save_proxy_settings(self) -> str | None:
        """현재 프록시 목록을 settings.txt 에 다시 씀 (1줄:간격, 2줄:동시요청, 3줄~:프록시)."""
        try:
            lines = [str(self.req_min_ms), str(self.max_workers)]
            lines += [p.strip() for p in self.proxies if p and p.strip()]
            tmp = self.settings_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            os.replace(tmp, self.settings_path)
            return None
        except Exception as e:
            return f"프록시 저장 오류 {e}"

    def add_proxy(self, proxy: str) -> str | None:
        """settings.txt 프록시 추가. 중복이면 에러 문자열 반환."""
        proxy = proxy.strip()
        if not proxy:
            return "프록시가 비어 있습니다."
        if proxy in self.proxies:
            return "이미 등록된 프록시입니다."
        self.proxies.append(proxy)
        err = self.save_proxy_settings()
        if err:
            self.proxies.remove(proxy)
        return err

    def remove_proxy(self, proxy: str) -> str | None:
        """settings.txt 프록시 삭제."""
        if proxy not in self.proxies:
            return "목록에 없는 프록시입니다."
        self.proxies.remove(proxy)
        err = self.save_proxy_settings()
        if err:
            self.proxies.append(proxy)
        return err

    def effective_workers(self) -> int:
        """실제 동시 요청 수 — 프록시 수를 넘을 수 없다(같은 IP 동시요청 = 차단)."""
        n = len(self.proxies)
        return max(1, min(self.max_workers, n)) if n else self.max_workers

    def status_summary(self) -> str:
        eff = self.effective_workers()
        workers = f"{eff}개" if eff == self.max_workers else f"{eff}개(설정 {self.max_workers})"
        return (
            f"당근 검색기 (프록시 {len(self.proxies)}개, "
            f"동시 요청 {workers}, 요청별 최소 대기 시간 {self.req_min_ms}ms)"
        )

    def start_task(
        self,
        tasks: Iterable[CrawlTask],
    ):
        task_list = list(tasks)
        if not task_list:
            raise Exception("작업이 없습니다")

        if self.is_task_running():
            raise Exception("작업이 이미 진행 중입니다")

        self._start_task(task_list)

    def stop_task(self):
        if self.task:
            self.task.stop()

    def is_task_running(self) -> bool:
        return self.task is not None

    def is_task_stopping(self) -> bool:
        return bool(self.task and self.task.stop_event.is_set())

    def _handle_task_finished(self):
        self.task = None
        self.task_finished.emit()

    def _handle_new_products(self, area: str, products: list[Product]):
        if self.model:
            self.model.insert_products(area, products)

    def _start_task(
        self,
        payload: list[CrawlTask],
    ):
        self.task = CrawlThread(
            self,
            self.req_min_ms,
            self.proxies,
            self.max_workers,
            payload,
        )
        self.task.error.connect(self.task_error.emit)
        self.task.message.connect(self.task_message.emit)
        self.task.finished.connect(self._handle_task_finished)
        self.task.new_products.connect(self._handle_new_products)
        self.task.start()

    def fetch_all_products(self) -> list[Product]:
        query = QSqlQuery(self.db)
        query.exec(
            "SELECT no, name, price, description, image_url, url, boosted_at, keyword, area FROM products"
        )
        products: list[Product] = []
        while query.next():
            products.append(
                Product(
                    no=query.value(0),
                    name=query.value(1),
                    price=str(query.value(2)),
                    priceCurrency="KRW",
                    description=query.value(3),
                    image=query.value(4),
                    url=query.value(5),
                    boostedAt=datetime.fromtimestamp(query.value(6)),
                    searched_keyword=query.value(7) or "",
                    area=query.value(8) or "",
                )
            )
        return products

    def get_product_by_id(self, prd_id) -> Product | None:
        query = QSqlQuery(self.db)
        query.prepare(
            "SELECT no, name, price, description, image_url, url, boosted_at, keyword, area FROM products WHERE id = ?"
        )
        query.addBindValue(prd_id)
        query.exec()

        if query.next():
            return Product(
                no=query.value(0),
                name=query.value(1),
                searched_keyword=query.value(7) or "",
                price=str(query.value(2)),
                priceCurrency="KRW",
                description=query.value(3),
                image=query.value(4),
                url=query.value(5),
                boostedAt=datetime.fromtimestamp(query.value(6)),
                area=query.value(8) or "",
            )
        return None

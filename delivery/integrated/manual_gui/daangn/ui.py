from datetime import datetime
from PyQt6.QtSql import QSqlDatabase, QSqlQuery, QSqlQueryModel
from PyQt6.QtCore import Qt

from daangn.model import Product


class MySqlQueryModel(QSqlQueryModel):
    NAMES = ["id", "no", "name", "area", "price", "boosted_at"]

    def __init__(self, parent, db: QSqlDatabase):
        super().__init__(parent)

        self.sort_column = 0
        self.sort_order = "ASC"
        self.db = db

        self._init()

    def _init(self):
        query = QSqlQuery(self.db)
        query.exec("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            no INTEGER,
            name TEXT,
            description TEXT,
            image_url TEXT,
            url TEXT,
            area TEXT,
            keyword TEXT,
            price INTEGER,
            boosted_at INTEGER
        )
        """)

        query.exec("CREATE INDEX IF NOT EXISTS idx_products_no ON products(no)")
        query.exec("CREATE INDEX IF NOT EXISTS idx_products_name ON products(name)")
        query.exec("CREATE INDEX IF NOT EXISTS idx_products_area ON products(area)")
        query.exec("CREATE INDEX IF NOT EXISTS idx_products_price ON products(price)")
        query.exec(
            "CREATE INDEX IF NOT EXISTS idx_products_boosted_at ON products(boosted_at)"
        )

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):  # type: ignore
        if role == Qt.ItemDataRole.DisplayRole:
            col = index.column()
            value = super().data(index, role)

            if col == 4 and value is not None:
                try:
                    return f"₩ {int(value):,}"
                except Exception:
                    return value

            if col == 5 and value is not None:
                try:
                    ts = int(value)
                    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")  # noqa: F821
                except Exception:
                    return value

        return super().data(index, role)

    def _get_current_sql(self) -> str:
        return f"""
        SELECT id AS '순번', no AS '지역별 순번', name AS '이름', area AS '지역', price AS '가격', boosted_at AS '끌어올리기 시간'
        FROM products
        ORDER BY {self.NAMES[self.sort_column]} {self.sort_order}
        """

    def select(self):
        self.setQuery(self._get_current_sql(), self.db)

    def sort(self, column: int, order: Qt.SortOrder) -> None:  # type: ignore
        self.sort_column = column
        self.sort_order = "ASC" if order == Qt.SortOrder.AscendingOrder else "DESC"
        self.select()

    def insert_products(self, area: str, products: list[Product]):
        query = QSqlQuery(self.db)
        query.prepare("""
        INSERT INTO products (no, name, description, image_url, url, area, keyword, price, boosted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """)

        self.db.transaction()

        for product in products:
            query.addBindValue(product.no)
            query.addBindValue(product.name)
            query.addBindValue(product.description)
            query.addBindValue(product.image)
            query.addBindValue(product.url)
            query.addBindValue(area)
            query.addBindValue(product.searched_keyword)
            query.addBindValue(int(float(product.price)))
            query.addBindValue(int(product.boostedAt.timestamp()))
            query.exec()

        self.db.commit()
        self.select()

    def clear_all(self):
        query = QSqlQuery(self.db)
        query.exec("DELETE FROM products")
        self.select()

    def sorted_products(self) -> list[Product]:
        sql = f"""
SELECT no, name, keyword, area, price, description, image_url, url, boosted_at
FROM products
ORDER BY {self.NAMES[self.sort_column]} {self.sort_order}
"""

        q = QSqlQuery(sql, self.db)
        products = []

        while q.next():
            products.append(
                Product(
                    no=q.value(0),
                    name=q.value(1),
                    searched_keyword=q.value(2),
                    area=q.value(3),
                    price=q.value(4),
                    priceCurrency="KRW",
                    description=q.value(5),
                    image=q.value(6),
                    url=q.value(7),
                    boostedAt=datetime.fromtimestamp(q.value(8)),
                )
            )

        return products

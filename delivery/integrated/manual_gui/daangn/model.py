from dataclasses import dataclass
from datetime import datetime

from daangn.data import CURRENCY_SYMBOLS


@dataclass
class Product:
    no: int
    name: str
    searched_keyword: str
    price: str
    priceCurrency: str
    description: str
    image: str
    url: str
    boostedAt: datetime
    area: str

    def get_price_str(self):
        try:
            symbol = CURRENCY_SYMBOLS.get(self.priceCurrency, self.priceCurrency)
            if self.priceCurrency == "KRW":
                return f"{symbol} {int(float(self.price)):,}"

            return f"{symbol} {self.price}"
        except Exception as e:
            print("get_price_str", e)
            return "N/A"

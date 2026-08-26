from dataclasses import dataclass, field
from typing import Tuple


@dataclass
class CrawlTask:
    area: Tuple[str, str]
    keyword: str
    only_tradeable: bool
    minimum: int | None
    maximum: int | None
    # 추가기능
    extra_keywords: list[str] = field(default_factory=list)   # 추가 키워드(모두 포함)
    exclude_keywords: list[str] = field(default_factory=list)  # 제외 키워드
    adaptive: bool = False                                     # 구단위+가격분할
    access_token: str | None = None                           # 토큰(옵션)

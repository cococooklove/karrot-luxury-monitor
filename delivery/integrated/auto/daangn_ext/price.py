"""
가격 문자열 → 원 단위 정수. 한 곳에만 둔다.

알림 payload 도, 엑셀 셀도 같은 규칙으로 읽어야 한다. 예전에는 이 파서가
article_watch 안에만 있었는데, article_watch 는 manual_gui 트리에만 들어가는
모듈이라 다른 배포본에서 alert_rules 가 부르면 ImportError 로 죽었다.
"""
from __future__ import annotations

import re

_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(억|만)?")


def parse_price_text(s) -> int:
    """매칭 응답의 가격 문자열 → 원 단위 정수. 판단 불가면 0.

    알림 문자열은 큰 금액을 줄여 쓴다('285만원'). 숫자만 뽑으면 285 가 되어
    실제 2,850,000 과 백만 배 어긋나므로 만·억 단위를 반드시 풀어야 한다."""
    if isinstance(s, bool):
        return 0
    if isinstance(s, (int, float)):
        return int(s)
    if not isinstance(s, str):
        return 0
    txt = s.replace(",", "")
    if not re.search(r"\d", txt):
        return 0                       # '나눔' 등
    if "억" not in txt and "만" not in txt:
        digits = re.sub(r"[^0-9]", "", txt)
        return int(digits) if digits else 0
    total = 0
    matched = False
    for num, unit in _UNIT_RE.findall(txt):
        try:
            v = float(num)
        except ValueError:
            continue
        matched = True
        total += v * {"억": 100000000, "만": 10000}.get(unit, 1)
    return int(total) if matched else 0

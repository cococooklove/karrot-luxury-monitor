"""조건 그리드 ↔ 룰 변환 — 화면 표가 엑셀을 대신한다.

조건표는 엑셀 파일이 원본이었다. 클라는 파일을 만들고, 고치고, 저장하고,
다시 불러와야 했다 — 다섯 줄 바꾸는 데 네 단계다. 이제 화면 표에 바로
적는다. 표의 열은 엑셀 시트와 같고(브랜드·제품명·최소가격·최대가격·제외),
엑셀에서 복사한 것을 그대로 붙여 넣을 수 있다.

행 번호는 엑셀과 맞춘다 — 머리글이 1행, 첫 데이터가 2행. 파서
(parse_rule_rows)의 오류 메시지가 "5행 …" 이라 말하면 표에서도 5 를 찾으면
된다. 그래서 빈 행도 버리지 않고 그대로 넘긴다.
"""
from __future__ import annotations

RULE_COLS = ["브랜드", "제품명", "최소가격", "최대가격", "제외"]


def paste_cells(text: str) -> list[list[str]]:
    """클립보드 텍스트 → 셀. 엑셀 복사는 탭으로 칸, 줄바꿈으로 행을 나눈다.

    끝의 줄바꿈은 엑셀이 늘 붙이는 것이라 행이 아니다. 가운데 빈 줄은
    빈 행이다 — 붙여 넣은 뒤 행 번호가 엑셀과 어긋나면 안 된다."""
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    return [line.split("\t") for line in lines]


def grid_to_rows(cells) -> list[tuple]:
    """셀 → parse_rule_rows 가 먹는 행 튜플(머리글 포함). 빈 행도 지킨다."""
    rows = [tuple(RULE_COLS)]
    n = len(RULE_COLS)
    for row in cells:
        vals = ["" if v is None else str(v) for v in (row or [])][:n]
        vals += [""] * (n - len(vals))
        rows.append(tuple(vals))
    return rows


def grid_row_label(i: int) -> str:
    """표의 i번째 줄(0부터)의 엑셀 행 번호."""
    return str(i + 2)


def _price(v) -> str:
    return f"{int(v):,}" if v else ""


def rules_to_grid(rules) -> list[list[str]]:
    """룰 → 셀. 제품명이 비면 빈 칸이 맞다 — '그 브랜드 전체' 라는 뜻이다.

    브랜드 열 없던 옛 시트의 룰은 키워드 첫 어절을 브랜드, 나머지를
    제품명으로 편다 — 다시 적용해도 키워드가 같아진다."""
    out = []
    for r in rules or []:
        brand = r.brand_name()
        prod = r.product or ""
        if not prod and r.keyword.strip() != brand:
            parts = r.keyword.split()
            if parts and parts[0] == brand:
                prod = " ".join(parts[1:])
            else:
                prod = r.keyword
        out.append([brand, prod, _price(r.min_price), _price(r.max_price),
                    ", ".join(r.exclude)])
    return out

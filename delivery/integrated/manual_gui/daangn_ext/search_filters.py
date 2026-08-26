"""
키워드 포함 필터 — 클라 요구 "키워드 검색 + 추가 키워드 설정. 포함된 것만 보기".

당근 검색은 느슨하게 매칭돼 무관 매물이 섞인다. 제목+본문 기준으로
필수 키워드가 실제 포함된 것만 남긴다. 추가 키워드는 AND(모두 포함) 또는
OR(하나라도) 선택. 제외 키워드로 오탐(가품/부속품 등)도 컷.

manual/auto 공용. Product 는 각 프로젝트 model 을 그대로 받음(제목/본문 속성만 사용).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class KeywordRule:
    required: list[str]                 # 기본 검색 키워드(반드시 포함)
    extra: list[str] | None = None      # 추가 키워드
    extra_mode: str = "and"             # "and"=모두 포함, "or"=하나라도
    exclude: list[str] | None = None    # 제외 키워드(하나라도 있으면 컷)
    fields: tuple[str, ...] = ("name", "title", "description", "content")

    def _text(self, product) -> str:
        parts = []
        for f in self.fields:
            v = getattr(product, f, None)
            if isinstance(v, str):
                parts.append(v)
        return " ".join(parts).lower()

    def match(self, product) -> bool:
        text = self._text(product)
        # 필수: 전부 포함
        for kw in self.required:
            if kw and kw.lower() not in text:
                return False
        # 제외: 하나라도 있으면 탈락
        for kw in (self.exclude or []):
            if kw and kw.lower() in text:
                return False
        # 추가: 모드에 따라
        extra = [k for k in (self.extra or []) if k]
        if extra:
            hits = [k for k in extra if k.lower() in text]
            if self.extra_mode == "and" and len(hits) != len(extra):
                return False
            if self.extra_mode == "or" and not hits:
                return False
        return True


def apply_filter(products: list, rule: KeywordRule) -> list:
    return [p for p in products if rule.match(p)]

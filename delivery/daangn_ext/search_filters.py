"""
키워드 포함 필터 — 클라 요구 "키워드 검색 + 추가 키워드 설정. 포함된 것만 보기".

당근 검색은 느슨하게 매칭돼 무관 매물이 섞인다. 제목+본문 기준으로
필수 키워드가 실제 포함된 것만 남긴다. 추가 키워드는 AND(모두 포함) 또는
OR(하나라도) 선택. 제외 키워드로 오탐(가품/부속품 등)도 컷.

매칭은 '어절 AND'다. 클라 요구가 "띄어쓰기 상관없이 그 글자가 다 포함된
글이면 잡아낸다"이기 때문이다. 키워드를 어절로 쪼개고, 제목+본문에서
공백·구분기호를 지운 문자열에 각 어절이 들어 있으면 통과시킨다.

  키워드 "루이비통 오버 더 문" →
    루이비통 오버 더 문        통과
    루이비통 오버더 문         통과
    루이비통 오 버더문         통과
    루이비통 … 내용 … 오버더문  통과 (어절이 떨어져 있어도 됨)

한 글자 어절은 앞 어절에 붙여 하나로 본다("오버"+"더"+"문" → "오버더문").
따로 찾으면 '더'·'문' 같은 흔한 글자가 아무 데나 걸린다.

단순 substring 이었다면 위 넷 중 첫 줄만 통과했다. 한글 중고 매물은 어순도
자주 뒤집히므로("노에 나노 루이비통") 연속 부분열로는 놓친다.

숫자 어절은 예외로 앞 어절에 묶는다. "반둘리에 50" 을 어절 AND 로 풀면
"반둘리에 25 … 50만원 네고" 가 걸려버리기 때문이다. 숫자는 바로 앞 어절
가까이(사이 3글자 이내) 있을 때만 인정한다 — "반둘리에 사이즈 50" 은 통과,
"반둘리에25 가격 50만원" 은 탈락.

manual/auto 공용. Product 는 각 프로젝트 model 을 그대로 받음(제목/본문 속성만 사용).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# 공백과 구분기호는 통째로 지운다 — 클라가 띄어쓰기·기호 차이를 무시하길 원한다.
_SEP_RE = re.compile(r"[\s​ \-_·・‧,./\\|~^*+=<>()\[\]{}\"'`:;!?#％%&@…]+")
_NUM_RE = re.compile(r"^\d+$")
# 제목과 본문 사이에 끼우는 경계 표식. 공백을 지우고 이어 붙이면 제목 끝
# 글자와 본문 첫 글자가 붙어 없던 단어가 생긴다 — 제목 "루이비통 오버 더" +
# 본문 "문의주세요" 가 "루이비통 오버 더 문" 으로 잡혔다. 이 글자는
# _SEP_RE 가 지우지 않으므로 어절 하나가 경계를 넘지 못한다.
FIELD_SEP = "\x00"
# 숫자 어절과 앞 어절 사이에 끼어도 되는 글자 수. "반둘리에 사이즈 50" 까지만 인정.
# 사이에 다른 숫자가 끼면 안 된다 — "반둘리에25 급처 50만원" 이 "반둘리에 50" 으로
# 걸려버린다. 그래서 틈은 숫자가 아닌 글자만 허용한다.
_NUM_GAP = 3

# 삽니다/구합니다 글은 판매 매물이 아니다. 제목에서만 본다 —
# 본문은 "구합니다 아니고 팝니다" 같은 문장이 섞여 오탐이 난다.
# 짧은 표식("구함")은 넣지 않는다 — 공백을 지운 문자열에서는 "친구 함께"가
# "구함"이 되어 멀쩡한 판매글이 사라진다. 그래서 판정은 공백을 살린 채 한다.
WANTED_MARKERS = ("삽니다", "삽니당", "삼니다", "구합니다", "구합니당", "구해요",
                  "구해봅니다", "파실분", "팔실분", "사고싶어요", "삽니닷")


def normalize_text(s) -> str:
    """비교용 정규화: NFKC → 공백·구분기호 제거 → 소문자."""
    return _SEP_RE.sub("", unicodedata.normalize("NFKC", str(s or ""))).lower()


def keyword_patterns(keyword) -> list[re.Pattern]:
    """키워드를 어절 단위 정규식으로 쪼갠다. 숫자 어절은 앞 어절에 묶는다."""
    words = [normalize_text(w) for w in re.split(r"[\s,]+", str(keyword or "")) if w]
    pats: list[re.Pattern] = []
    prev: str | None = None
    prev_bound = False          # 앞 어절이 이미 숫자를 물었는가
    gap = r"[^0-9%s]{0,%d}" % (re.escape(FIELD_SEP), _NUM_GAP)
    for w in words:
        if not w:
            continue
        if _NUM_RE.match(w) and prev:
            pat = re.compile(re.escape(prev) + gap + re.escape(w))
            if prev_bound:
                pats.append(pat)      # "반둘리에 50 55" — 둘 다 같은 어절에 묶는다
            else:
                pats[-1] = pat
                prev_bound = True
        elif len(w) == 1 and prev and not prev_bound:
            # 한 글자 어절은 앞 어절에 붙인다. "오버 더 문"의 '더'·'문'을
            # 따로 찾으면 "…오버 더" + "문의주세요" 처럼 아무 데나 걸린다.
            prev += w
            pats[-1] = re.compile(re.escape(prev))
        elif _NUM_RE.match(w):
            # 앞 어절 없는 숫자("50 반둘리에"). 다른 수의 일부로 걸리면 안 되므로
            # 숫자 경계를 요구한다 — 안 그러면 "550,000원"에 50 이 걸린다.
            pats.append(re.compile(r"(?<![0-9])" + re.escape(w) + r"(?![0-9])"))
        else:
            pats.append(re.compile(re.escape(w)))
            prev, prev_bound = w, False
    return pats


def contains_keyword(text_norm: str, keyword) -> bool:
    """정규화된 텍스트에 키워드의 모든 어절이 들어 있으면 True."""
    pats = keyword_patterns(keyword)
    return bool(pats) and all(p.search(text_norm) for p in pats)


def spaced_text(s) -> str:
    """구분기호를 지우지 않고 공백 하나로 줄인 문자열. 표식 판정용."""
    return _SEP_RE.sub(" ", unicodedata.normalize("NFKC", str(s or ""))).lower()


def looks_wanted_ad(title) -> bool:
    """'삽니다' 류 구매글이면 True.

    공백을 지우지 않고 본다 — 지우면 "친구 함께"가 "구함"이 되는 식으로
    멀쩡한 판매글을 잡는다."""
    t = spaced_text(title)
    return any(m in t for m in WANTED_MARKERS)


@dataclass
class KeywordRule:
    required: list[str]                 # 기본 검색 키워드(반드시 포함)
    extra: list[str] | None = None      # 추가 키워드
    extra_mode: str = "and"             # "and"=모두 포함, "or"=하나라도
    exclude: list[str] | None = None    # 제외 키워드(하나라도 있으면 컷)
    fields: tuple[str, ...] = ("name", "title", "description", "content")
    title_fields: tuple[str, ...] = ("name", "title")
    drop_wanted: bool = True            # 삽니다/구합니다 글 컷

    def _join(self, product, fields) -> str:
        parts = []
        for f in fields:
            v = getattr(product, f, None)
            if isinstance(v, str):
                parts.append(v)
        return " ".join(parts)

    def _text(self, product) -> str:
        # 필드마다 따로 정규화한 뒤 경계 표식으로 잇는다. 그냥 붙이면 제목 끝
        # 글자와 본문 첫 글자가 한 어절로 뭉쳐 없던 단어가 생긴다.
        parts = []
        for f in self.fields:
            v = getattr(product, f, None)
            if isinstance(v, str) and v:
                parts.append(normalize_text(v))
        return FIELD_SEP.join(parts)

    def match(self, product) -> bool:
        text = self._text(product)
        if self.drop_wanted and looks_wanted_ad(self._join(product, self.title_fields)):
            return False
        # 필수: 전부 포함
        for kw in self.required:
            if kw and not contains_keyword(text, kw):
                return False
        # 제외: 하나라도 있으면 탈락
        for kw in (self.exclude or []):
            if kw and contains_keyword(text, kw):
                return False
        # 추가: 모드에 따라
        extra = [k for k in (self.extra or []) if k]
        if extra:
            hits = [k for k in extra if contains_keyword(text, k)]
            if self.extra_mode == "and" and len(hits) != len(extra):
                return False
            if self.extra_mode == "or" and not hits:
                return False
        return True


def apply_filter(products: list, rule: KeywordRule) -> list:
    return [p for p in products if rule.match(p)]

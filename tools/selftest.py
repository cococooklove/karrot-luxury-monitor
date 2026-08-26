"""
캡처 없이 파이프라인 로직 검증 (parse / analyze 휴리스틱).
실기기 캡처 전에 코드가 도는지 확인용.

용법:
  python tools/selftest.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "collector"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import parse
import analyze_capture as ac

FAILS = []


def check(name, cond):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILS.append(name)


# --- parse.extract: 응답에서 매물 배열 자동탐색 + 정규화 ---
sample_resp = {
    "result": {
        "articles": [
            {"id": 101, "title": "역세권 원룸", "price": 5000, "area": 23.1,
             "region_name": "역삼동", "lat": 37.5, "lng": 127.0,
             "created_at": "2026-08-23T10:00:00", "image_url": "http://x/1.jpg"},
            {"id": 102, "title": "투룸 전세", "price": 20000, "area": 45.0,
             "region_name": "역삼동", "lat": 37.5, "lng": 127.0,
             "created_at": "2026-08-23T11:00:00", "image_url": "http://x/2.jpg"},
        ],
        "meta": {"count": 2},
    }
}
items = parse.extract(sample_resp)
check("parse: 2건 추출", len(items) == 2)
check("parse: id 매핑", items[0]["id"] == 101)
check("parse: title 매핑", items[1]["title"] == "투룸 전세")
check("parse: _raw 보존", items[0]["_raw"]["price"] == 5000)

# 배열 경로 다를 때도 자동탐색
alt = {"data": {"list": [{"id": 1}, {"id": 2}, {"id": 3}]}}
check("parse: 자동탐색(다른 스키마)", len(parse.extract(alt)) == 3)

# --- analyze 휴리스틱 ---
check("analyze: 서명값 탐지(hex)", ac.looks_signed("9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"))
check("analyze: 서명값 탐지(base64)", ac.looks_signed("dGhpc2lzYXNpZ25hdHVyZXZhbHVl123+/="))
check("analyze: 짧은값 서명아님", not ac.looks_signed("v1"))
check("analyze: 엔트로피 낮으면 서명아님", not ac.looks_signed("aaaaaaaaaaaaaaaaaaaa"))

check("analyze: DEVICE_KEYS", bool(ac.DEVICE_KEYS.search("x-device-id")))
check("analyze: INTEGRITY_KEYS", bool(ac.INTEGRITY_KEYS.search("x-play-integrity")))
check("analyze: SIGN_KEYS", bool(ac.SIGN_KEYS.search("x-signature")))
check("analyze: AUTH_KEYS", bool(ac.AUTH_KEYS.search("authorization")))

print()
if FAILS:
    print(f"{len(FAILS)}건 실패: {FAILS}")
    sys.exit(1)
print("전체 통과 — parse/analyze 로직 정상. 실기기 캡처만 붙이면 됨.")


if __name__ == "__main__":
    pass

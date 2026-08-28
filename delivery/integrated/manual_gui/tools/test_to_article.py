#!/usr/bin/env python3
"""수동 모드 핵심 파서(app-API document → 매물 dict) 단위테스트. 토큰/네트워크 불필요.
실행: python tools/test_to_article.py  (manual_gui 디렉터리에서)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from daangn_ext.app_api import to_article


def main():
    ok = True
    def chk(name, got, exp):
        nonlocal ok
        r = got == exp; ok = ok and r
        print(f"  {'OK ' if r else 'FAIL'} {name}: {got!r}" + ("" if r else f" (기대 {exp!r})"))

    doc = {
        "id": 1235065827, "title": "샤넬 클래식 플랩백", "content": "정품",
        "price": "1900000", "firstImage": {"url": "https://img/x.webp"},
        "regionName": "강남구 논현동", "categoryId": 2, "watchesCount": 12,
    }
    a = to_article(doc)
    chk("id", a["id"], "1235065827")
    chk("title", a["title"], "샤넬 클래식 플랩백")
    chk("price", a["price"], "1900000")
    chk("thumbnail", a["thumbnail"], "https://img/x.webp")
    chk("href", a["href"], "https://www.daangn.com/kr/buy-sell/-1235065827/")
    chk("region", a["region"], "강남구 논현동")
    chk("watchesCount", a["watchesCount"], 12)

    chk("price 폴백(priceInfo)", to_article({"id": 5, "priceInfo": {"price": "500000"}})["price"], "500000")
    empty = to_article({})
    chk("빈doc id", empty["id"], "")
    chk("빈doc href", empty["href"], "")

    print("결과:", "전부 통과" if ok else "실패 있음")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

"""프록시 풀 차단 진단 러너.

    python delivery/health_check.py [proxies.txt] [키워드] [지역코드]

요청 수 = 프록시 수 + 1(직결). 각 IP 1회씩만 찌른다.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from daangn_ext.health import health_check, print_report

path = sys.argv[1] if len(sys.argv) > 1 else "proxies.txt"
kw = sys.argv[2] if len(sys.argv) > 2 else "구찌"
reg = sys.argv[3] if len(sys.argv) > 3 else "역삼동-6035"
pool = [l.strip() for l in open(path, encoding="utf-8") if l.strip()]
print(f"풀 {len(pool)}개 진단 — '{kw}' @ {reg}\n")
print_report(health_check(pool, keyword=kw, region=reg))

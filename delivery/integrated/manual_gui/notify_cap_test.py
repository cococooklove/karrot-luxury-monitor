"""알림 물량 상한 — 설정 실수 하나가 받는 사람 폰을 못 쓰게 만들지 않는가.

스윕 범위는 지역 x 키워드로 곱해진다. 실측으로 강남 한 동의 '샤넬' 하나가
시간당 신규 13건이었다. 브랜드 20개 x 서울 806동이면 시간당 수백 건이고,
그건 알림이 아니라 소음이다 — 진짜 급매가 그 안에 묻힌다.

상한을 넘긴 건 **버리지 않고 요약해서** 알린다. 조용히 사라지면 운영자가
"알림이 안 온다"고 오해하고, 그게 더 나쁘다.

실행: python notify_cap_test.py
"""
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

from daangn import notify as N

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


def sender(cap=5):
    s = N.TelegramSender("tok", "chat", log=lambda m: logs.append(m),
                         hourly_cap=cap)
    return s


logs = []
print("=== 1. 상한 안에서는 그대로 쌓인다 ===")
s = sender(5)
for i in range(5):
    s.enqueue(f"매물 {i}")
ck("5건 전부 큐에", s.pending() == 5, f"{s.pending()}건")

print("\n=== 2. 상한을 넘으면 큐에 안 쌓고 센다 ===")
for i in range(7):
    s.enqueue(f"초과 {i}")
ck("큐는 늘지 않는다", s.pending() == 5, f"{s.pending()}건")
ck("눌린 건수를 센다", s._suppressed == 7, f"{s._suppressed}건")
ck("상한 도달을 한 번만 로그로 알린다",
   len([m for m in logs if "상한" in m]) == 1, str(logs))

print("\n=== 3. 창이 지나면 다시 열리고, 눌린 건 요약된다 ===")
s._window_start -= N.TG_CAP_WINDOW + 1        # 한 시간 지난 것처럼
s.enqueue("새 창 첫 건")
joined = " ".join(s._q)
ck("요약 줄이 들어간다", "보내지 않았습니다" in joined, joined[-80:])
ck("몇 건이 눌렸는지 적는다", "7건" in joined)
ck("새 건도 들어간다", "새 창 첫 건" in joined)
ck("카운터가 리셋된다", s._suppressed == 0)

print("\n=== 4. 상한 0 이면 제한 없음(옛 동작) ===")
# TG_QUEUE_SOFT_CAP(40) 을 넘기면 큐가 스스로 flush 하며 실제 전송을 시도한다.
# 여기서 보려는 건 '상한 0 = 무제한'이므로 그 아래로 둔다.
s2 = N.TelegramSender("tok", "chat", hourly_cap=0)
n = N.TG_QUEUE_SOFT_CAP - 1
for i in range(n):
    s2.enqueue(f"m{i}")
ck("전부 통과", s2.pending() == n, f"{s2.pending()}/{n}건")
ck("눌린 건 없다", s2._suppressed == 0)

print("\n=== 5. 미설정이면 여전히 조용히 버린다 ===")
s3 = N.TelegramSender("", "", hourly_cap=5)
s3.enqueue("x")
ck("큐가 비어 있다", s3.pending() == 0)
ck("상한 카운터도 안 움직인다", s3._suppressed == 0)

print("\n=== 6. 기본 상한이 사람이 읽을 수 있는 수준 ===")
ck("기본 상한이 있다", N.TG_HOURLY_CAP > 0, str(N.TG_HOURLY_CAP))
ck("시간당 수백 건은 막힌다", N.TG_HOURLY_CAP <= 200, str(N.TG_HOURLY_CAP))
ck("창은 1시간", N.TG_CAP_WINDOW == 3600.0)

bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패:", bad)
sys.exit(1 if bad else 0)

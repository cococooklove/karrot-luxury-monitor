"""워치리스트 배선 중 순수 함수만 확인 (Qt 창 안 띄움).

    python article_watch_wiring_test.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, app_dir)
os.chdir(app_dir)  # Ensure OUT.json is found regardless of where test is run from

import main as m

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


print("=== A. watch_event_lines ===")
EV = [
    {"kind": "price_down", "id": "1", "title": "샤넬 클래식", "url": "u1",
     "old": 1000000, "new": 800000, "at": 0},
    {"kind": "price_up", "id": "2", "title": "디올 백", "url": "u2",
     "old": 500000, "new": 600000, "at": 0},
    {"kind": "sold", "id": "3", "title": "구찌 지갑", "url": "u3",
     "old": "ongoing", "new": "closed", "at": 0},
    {"kind": "deleted", "id": "4", "title": "펜디 백", "url": "u4",
     "old": "ongoing", "new": "gone", "at": 0},
    {"kind": "republished", "id": "5", "title": "프라다 백", "url": "u5",
     "old": 0, "new": 1, "at": 0},
]
lines = m.watch_event_lines(EV)
ck("이벤트 수만큼", len(lines) == 5, len(lines))
ck("인하 제목", "샤넬 클래식" in lines[0], lines[0])
ck("인하 금액 천단위", "800,000" in lines[0], lines[0])
ck("인하 표시", "↓" in lines[0], lines[0])
ck("인상 표시", "↑" in lines[1], lines[1])
ck("판매완료 문구", "판매완료" in lines[2], lines[2])
ck("삭제 문구", "삭제" in lines[3], lines[3])
ck("끌올 문구", "끌올" in lines[4], lines[4])
ck("링크 포함", "u1" in lines[0], lines[0])
ck("빈 입력 → 빈 목록", m.watch_event_lines([]) == [])
ck("None → 빈 목록", m.watch_event_lines(None) == [])
ck("모르는 kind 는 건너뜀", m.watch_event_lines([{"kind": "zzz", "id": "9"}]) == [])

print("=== B. watch_sweep_budget ===")
ck("활성 0 → 0", m.watch_sweep_budget(0, 600) == 0)
ck("활성 300, 10분 → 양수", m.watch_sweep_budget(300, 600) > 0)
ck("주기 길수록 예산 큼",
   m.watch_sweep_budget(300, 1200) > m.watch_sweep_budget(300, 600))
ck("활성 많을수록 예산 큼",
   m.watch_sweep_budget(300, 600) > m.watch_sweep_budget(30, 600))
ck("최소 1 보장", m.watch_sweep_budget(1, 600) >= 1)
ck("스윕 주기 상수", m.WATCH_SWEEP_INTERVAL == 600)

print("=== C. watch_status_text ===")
s = m.watch_status_text(42, 1000 + 3600, 1000)
ck("건수 포함", "42" in s, s)
ck("시간 표기", "1시간" in s, s)
ck("추적 0건", m.watch_status_text(0, 0, 1000) == "추적 중 0건",
   m.watch_status_text(0, 0, 1000))
ck("분 단위 표기", "5분" in m.watch_status_text(5, 1300, 1000),
   m.watch_status_text(5, 1300, 1000))
ck("다음 점검 지남", "대기" in m.watch_status_text(5, 900, 1000),
   m.watch_status_text(5, 900, 1000))

print("=== D. headless_watch_due ===")
ck("주기 안 지남 → False", m.headless_watch_due(1000, 1100, 600) is False)
ck("주기 지남 → True", m.headless_watch_due(1000, 1700, 600) is True)
ck("경계 포함", m.headless_watch_due(1000, 1600, 600) is True)
ck("처음(0) → True", m.headless_watch_due(0, 10, 600) is True)

passed = sum(1 for _, ok in R if ok)
print(f"\n===== {passed}/{len(R)} PASS =====")
for name, ok in R:
    if not ok:
        print("  실패:", name)
sys.exit(0 if passed == len(R) else 1)

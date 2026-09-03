"""조건 그리드 ↔ 룰 변환 순수 로직 (PyQt 불필요).

    python rule_grid_test.py

화면 표(브랜드·제품명·최소가격·최대가격·제외)를 엑셀 대신 직접 편집한다.
표 셀 → parse_rule_rows 가 먹는 행 튜플, 룰 → 표 셀, 엑셀에서 복사한
클립보드 텍스트 → 셀. 셋 다 엑셀과 같은 행 번호(머리글 = 1행)를 지킨다.
"""
import os
import sys

app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, app_dir)
os.chdir(app_dir)

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


from daangn_ext.rule_grid import (RULE_COLS, paste_cells, grid_to_rows,
                                  rules_to_grid, grid_row_label)
from daangn_ext.alert_rules import AlertRule, parse_rule_rows

print("=== A. 클립보드 → 셀 ===")
ck("탭·줄바꿈으로 나눈다",
   paste_cells("루이비통\t오버 더 문\t500000\t1500000\t\n보테가\t카세트백\t1000000")
   == [["루이비통", "오버 더 문", "500000", "1500000", ""],
       ["보테가", "카세트백", "1000000"]])
ck("CRLF 와 끝 줄바꿈은 행을 만들지 않는다",
   paste_cells("a\tb\r\nc\td\r\n") == [["a", "b"], ["c", "d"]])
ck("가운데 빈 줄은 빈 행으로 남는다(엑셀 행 번호 유지)",
   paste_cells("a\n\nb") == [["a"], [""], ["b"]])
ck("빈 텍스트는 빈 목록", paste_cells("") == [] and paste_cells("\n") == [])
ck("한 칸짜리도 행 하나", paste_cells("루이비통") == [["루이비통"]])

print("=== B. 셀 → 파서 행 ===")
cells = [["루이비통", "오버 더 문", "500,000", "1500000", "레플리카, 부속품"],
         ["", "반둘리에 50", "", "2000000", ""],
         ["", "", "", "", ""],
         ["보테가베네타", "", "1000000", "500000", ""]]
rows = grid_to_rows(cells)
ck("첫 행은 머리글", tuple(rows[0]) == tuple(RULE_COLS))
ck("빈 행도 그대로 넘겨 행 번호를 지킨다", len(rows) == 5)
rules, errs = parse_rule_rows(rows)
ck("파서가 그대로 먹는다 — 브랜드 이어받기·쉼표 가격",
   [r.keyword for r in rules] == ["루이비통 오버 더 문", "루이비통 반둘리에 50"]
   and rules[0].min_price == 500000 and rules[0].exclude == ("레플리카", "부속품")
   and rules[1].brand == "루이비통", str([r.to_dict() for r in rules]))
ck("오류 행 번호는 엑셀과 같다(머리글=1행 → 표 4번째 줄 = 5행)",
   errs and errs[0].startswith("5행"), str(errs))
ck("행 라벨은 엑셀 번호", grid_row_label(0) == "2" and grid_row_label(3) == "5")
ck("짧은 행은 빈 칸으로 채운다",
   len(grid_to_rows([["루이비통"]])[1]) == len(RULE_COLS))
ck("셀 값 None 은 빈 칸", grid_to_rows([[None, "x"]])[1][0] == "")

print("=== C. 룰 → 셀 ===")
rs = [AlertRule(keyword="루이비통 오버 더 문", brand="루이비통", product="오버 더 문",
                min_price=500000, max_price=1500000, exclude=("레플리카", "부속품")),
      AlertRule(keyword="루이비통", brand="루이비통"),
      AlertRule(keyword="샤넬 클래식 미디움")]        # 옛 시트: 브랜드 열 없음
g = rules_to_grid(rs)
ck("브랜드·제품명·가격(쉼표)·제외(쉼표+공백)",
   g[0] == ["루이비통", "오버 더 문", "500,000", "1,500,000", "레플리카, 부속품"], str(g[0]))
ck("제품명 없음 = 브랜드 전체 → 빈 칸, 가격 없음 → 빈 칸",
   g[1] == ["루이비통", "", "", "", ""], str(g[1]))
ck("옛 키워드 시트는 첫 어절이 브랜드·나머지가 제품명",
   g[2] == ["샤넬", "클래식 미디움", "", "", ""], str(g[2]))
ck("룰 → 셀 → 룰 왕복이 같다",
   [r.keyword for r in parse_rule_rows(grid_to_rows(g))[0]]
   == ["루이비통 오버 더 문", "루이비통", "샤넬 클래식 미디움"])
ck("빈 룰은 빈 표", rules_to_grid([]) == [])

n_ok = sum(1 for _, c in R if c)
print(f"\n{n_ok}/{len(R)} PASS")
sys.exit(0 if n_ok == len(R) else 1)

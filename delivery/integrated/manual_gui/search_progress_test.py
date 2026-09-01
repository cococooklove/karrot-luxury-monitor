"""검색 진행 표시 계약 — 누르고 나서 무슨 일이 일어나는지 화면이 말해야 한다.

현상(2026-09-01, 클라): 수동 검색에서 '검색'을 누르면 확인창만 닫히고 한참
아무 변화가 없다. 전국이면 결과가 나오기까지 수십 초~분이 걸린다.

원인은 두 겹이다.
  1) 검색 직전 `_refresh_tokens()` 가 GUI 스레드에서 동기로 돌았다. 그 안의
     `ld_autoharvest.harvest_all(nudge=True)` 는 LDPlayer 함대를 깨우는 일이라
     수십 초가 걸리고, 그동안 이벤트 루프가 멈춘다 → 창이 얼어 리페인트조차
     안 된다. 진행 문구를 찍어도 안 그려지므로 "표시를 추가한다"만으로는
     못 고친다. 스레드로 내보내는 것이 진행 표시의 **전제**다.
  2) 진행률은 CrawlThread 가 `completed/total` 문자열로만 알렸고 상태바 한 줄에
     묻혔다. 전국 230개 지역에서는 눈에 띄지 않는다.

Qt 를 띄우지 않고 소스 수준에서 계약을 고정한다(서버·CI 에 디스플레이가 없다).

실행: python search_progress_test.py
"""
import ast
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


def fn_src(src, tree, *names):
    """중첩 포함해 이름이 일치하는 함수 소스를 이어 붙인다."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            out.append(ast.get_source_segment(src, node) or "")
    return "\n".join(out)


def cls_node(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


main_src = open("main.py", encoding="utf-8").read()
main_tree = ast.parse(main_src)
wsrc = open("daangn/workers.py", encoding="utf-8").read()
wtree = ast.parse(wsrc)
csrc = open("daangn/controller.py", encoding="utf-8").read()

print("=== 1. 토큰 확보는 GUI 스레드를 멈추지 않는다 ===")
tok = cls_node(main_tree, "_TokenRefreshThread")
ck("_TokenRefreshThread 가 있다", tok is not None)
ck("QThread 를 상속한다",
   tok is not None and any("QThread" in ast.unparse(b) for b in tok.bases))
tok_src = ast.get_source_segment(main_src, tok) if tok else ""
ck("done 시그널로 토큰을 돌려준다", "done = QtCore.pyqtSignal" in tok_src)
# 워커 스레드에서 위젯을 만지면 Qt 는 경고 없이 죽는다.
ck("워커 스레드가 위젯을 직접 만지지 않는다",
   "self.alert(" not in tok_src and "self.sb." not in tok_src)

print("\n=== 2. 검색 경로가 그 스레드를 탄다 ===")
start = fn_src(main_src, main_tree, "on_start_btn_clicked")
excel = fn_src(main_src, main_tree, "crawl_from_excel")
ck("on_start_btn_clicked 가 동기 _refresh_tokens 를 부르지 않는다",
   "self._refresh_tokens()" not in start)
ck("엑셀 크롤링도 마찬가지", "self._refresh_tokens()" not in excel)
ck("둘 다 _start_crawl 로 들어간다",
   "self._start_crawl(" in start and "self._start_crawl(" in excel)
begin = fn_src(main_src, main_tree, "_start_crawl")
ck("_start_crawl 이 토큰 스레드를 띄운다", "_TokenRefreshThread(" in begin)

print("\n=== 3. 화면 안 진행바 ===")
tab = fn_src(main_src, main_tree, "_build_manual_tab")
ck("진행바 위젯을 만든다", "self.searchProgress" in tab)
ck("진행 문구 라벨을 만든다", "self.searchProgressLabel" in tab)
ck("평소엔 숨어 있다", "self.searchProgress.setVisible(False)" in tab)

print("\n=== 4. 진행률은 문자열 파싱이 아니라 시그널로 온다 ===")
crawl = cls_node(wtree, "CrawlThread")
crawl_src = ast.get_source_segment(wsrc, crawl) if crawl else ""
ck("CrawlThread.progress 시그널", "progress = pyqtSignal(int, int)" in crawl_src)
ck("지역 하나 끝날 때마다 emit", "self.progress.emit(" in crawl_src)
ck("controller 가 task_progress 로 중계",
   "task_progress = pyqtSignal(int, int)" in csrc
   and "self.task.progress.connect(self.task_progress.emit)" in csrc)
conn = fn_src(main_src, main_tree, "_connect_signals")
ck("MainWindow 가 task_progress 를 받는다",
   "self.controller.task_progress.connect(self._handle_task_progress)" in conn)

print("\n=== 5. 끝나면 진행 표시를 걷는다 ===")
fin = fn_src(main_src, main_tree, "_handle_task_finished", "_handle_task_error")
ck("정상 종료·오류 양쪽에서 숨긴다",
   fin.count("self._hide_search_progress()") >= 2)

print("\n=== 6. 토큰 준비 중에 다시 눌러도 두 번 돌지 않는다 ===")
# 이 구간에는 controller.task 가 아직 없다. is_task_running() 만 보면 두 번째
# 검색이 그대로 시작된다.
ck("토큰 준비 중인지 먼저 본다", "_token_thread" in start)
ck("취소 경로가 있다", "_search_cancelled" in start)

print("\n=== 7. 취소 확인창이 중첩 이벤트루프라는 것 ===")
# ask() 가 도는 동안 done 시그널이 배달돼 검색이 이미 시작될 수 있다.
# 그때 _search_cancelled 를 세워봐야 지나간 분기다 — 실제 작업을 세워야 한다.
ck("ask 뒤에 토큰 스레드 상태를 다시 본다",
   "if self._token_thread is None:" in start)
ck("이미 시작됐으면 작업을 정지시킨다", "self.controller.stop_task()" in start)

print("\n=== 8. 종료할 때 토큰 스레드를 두고 가지 않는다 ===")
# 이 구간에는 controller.task 가 없어 기존 running 분기가 못 잡는다.
# 살아있는 QThread 를 남기고 창을 부수면 SIGABRT.
close = fn_src(main_src, main_tree, "closeEvent")
ck("_token_thread 를 기다린다", "_token_thread" in close and "tok.wait(" in close)

bad = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("실패:", bad)
sys.exit(1 if bad else 0)

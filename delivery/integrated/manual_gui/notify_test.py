"""알림 설정 전체 테스트 — 실패노출 / 배치전송 / 설정저장 / 테스트발송.

실행: ../../../.venv/bin/python notify_test.py
"""
import json
import os
import stat
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


from daangn.notify import TelegramSender, SheetWriter, run_test, TG_MAX_CHARS


class FakeResp:
    def __init__(self, status, body=None, text=""):
        self.status_code = status
        self._body = body
        self.text = text or json.dumps(body or {})

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


print("=== A. 텔레그램 실패 노출 (구멍 #1) ===")

logs = []
tg = TelegramSender("1:X", "9", log=logs.append, min_interval=0)
tg._post = lambda text, timeout=10: FakeResp(401, {"ok": False, "description": "Unauthorized"})
ok, err = tg.send("x")
ck("401 → 실패로 판정", ok is False, err)
ck("401 → 원인 힌트 포함", "봇 토큰이 잘못됨" in err and "401" in err)
tg._report_failure(err)
ck("401 → 로그 노출(무음 아님)", any("텔레그램 실패" in l for l in logs), logs[-1][:60] if logs else "로그없음")

logs2 = []
tg2 = TelegramSender("1:X", "9", log=logs2.append, min_interval=0)
tg2._post = lambda text, timeout=10: FakeResp(400, {"ok": False, "description": "chat not found"})
ok2, err2 = tg2.send("x")
ck("400 → chat_id 힌트", ok2 is False and "chat_id" in err2, err2)

tg3 = TelegramSender("1:X", "9", min_interval=0)
tg3._post = lambda text, timeout=10: FakeResp(403, {"ok": False, "description": "bot was blocked"})
ok3, err3 = tg3.send("x")
ck("403 → 차단/초대 안내", ok3 is False and "/start" in err3, err3)

# 429 → retry_after 만큼 대기 후 재시도 → 성공
calls = []
tg4 = TelegramSender("1:X", "9", min_interval=0)


def post429(text, timeout=10):
    calls.append(time.monotonic())
    if len(calls) == 1:
        return FakeResp(429, {"ok": False, "description": "Too Many Requests",
                              "parameters": {"retry_after": 1}})
    return FakeResp(200, {"ok": True})


tg4._post = post429
t0 = time.monotonic()
ok4, err4 = tg4.send("x")
elapsed = time.monotonic() - t0
ck("429 → retry_after 대기 후 재전송 성공", ok4 and len(calls) == 2, f"{elapsed:.1f}s 대기")
ck("429 → 대기시간 실제 적용", elapsed >= 0.9, f"{elapsed:.2f}s")

# 5xx → 재시도
calls5 = []
tg5 = TelegramSender("1:X", "9", min_interval=0)


def post500(text, timeout=10):
    calls5.append(1)
    return FakeResp(200, {"ok": True}) if len(calls5) > 1 else FakeResp(502, None, "bad gateway")


tg5._post = post500
ok5, _ = tg5.send("x")
ck("5xx → 재시도 후 성공", ok5 and len(calls5) == 2)

# 네트워크 예외 → 실패 반환(크래시 아님)
tg6 = TelegramSender("1:X", "9", min_interval=0)


def boom(text, timeout=10):
    raise ConnectionError("dns fail")


tg6._post = boom
ok6, err6 = tg6.send("x", retries=0)
ck("네트워크 예외 → 크래시 없이 실패 반환", ok6 is False and "네트워크 오류" in err6, err6)

# 실패 로그 억제 정책: 1~3 항상, 이후 20배수만
logs7 = []
tg7 = TelegramSender("1:X", "9", log=logs7.append, min_interval=0)
tg7._post = lambda text, timeout=10: FakeResp(401, {"ok": False, "description": "Unauthorized"})
for _ in range(21):
    tg7._report_failure(*tg7.send("x", retries=0)[1:])
ck("실패로그 억제(1~3회 + 20배수)", len(logs7) == 4, f"{len(logs7)}줄 / 21실패")

print("\n=== B. 배치 전송 (레이트리밋 유실 방지) ===")

sent_chunks = []
tg8 = TelegramSender("1:X", "9", min_interval=0)
tg8._post = lambda text, timeout=10: (sent_chunks.append(text), FakeResp(200, {"ok": True}))[1]
msgs = [f"🆕 신규\n[강남구] 샤넬백{i}\n1,000,000원\nhttp://x/{i}" for i in range(200)]
for m in msgs:
    tg8._q.append(m)          # 자동 flush 안 타게 직접 적재
s, f = tg8.flush()
ck("200건 → 소수 묶음으로 전송", len(sent_chunks) < 30 and f == 0,
   f"{len(msgs)}건 → {len(sent_chunks)}묶음")
ck("묶음 길이 한도 준수", all(len(c) <= TG_MAX_CHARS for c in sent_chunks),
   f"max={max(len(c) for c in sent_chunks)}자")
joined = "\n\n".join(sent_chunks)
ck("전체 내용 유실 없음", all(m in joined for m in msgs))

# 한도 초과 단건 → 잘라서 전송
sent_big = []
tg9 = TelegramSender("1:X", "9", min_interval=0)
tg9._post = lambda text, timeout=10: (sent_big.append(text), FakeResp(200, {"ok": True}))[1]
tg9._q.append("A" * (TG_MAX_CHARS * 2 + 10))
tg9.flush()
ck("초과 단건 분할 전송", len(sent_big) == 3 and all(len(c) <= TG_MAX_CHARS for c in sent_big),
   f"{len(sent_big)}조각")

# 큐 소프트캡 자동 flush
auto = []
tg10 = TelegramSender("1:X", "9", min_interval=0)
tg10._post = lambda text, timeout=10: (auto.append(text), FakeResp(200, {"ok": True}))[1]
for i in range(45):
    tg10.enqueue(f"m{i}")
ck("큐 40건 초과 시 자동 전송", len(auto) > 0 and tg10.pending() < 40,
   f"자동 {len(auto)}묶음, 잔여 {tg10.pending()}")

# 마감시간 초과 → 남은 건 재큐 + 로그
logs11 = []
tg11 = TelegramSender("1:X", "9", log=logs11.append, min_interval=0)
tg11._post = lambda text, timeout=10: (time.sleep(0.15), FakeResp(200, {"ok": True}))[1]
for i in range(30):
    tg11._q.append("X" * 3800)
tg11.flush(deadline=time.monotonic() + 0.3)
ck("마감 초과 → 잔여 재큐 + 로그", tg11.pending() > 0 and any("미전송" in l for l in logs11),
   f"잔여 {tg11.pending()}건")

# 미설정 → 무크래시, 큐 비움
tg12 = TelegramSender("", "", min_interval=0)
tg12.enqueue("x")
ck("미설정 → 크래시 없이 무시", tg12.flush() == (0, 0) and tg12.pending() == 0)
ck("미설정 send → 명확한 사유 반환", tg12.send("x")[1].startswith("텔레그램 미설정"))

print("\n=== C. 구글시트 (구멍 #3) ===")

sw = SheetWriter("", log=print)
ok_v, msg_v = sw.verify()
ck("시트 주소 없음 → 선택기능 안내", ok_v is False and "미입력" in msg_v, msg_v)

sw2 = SheetWriter("https://docs.google.com/spreadsheets/d/FAKE/edit", cred="./nope.json")
ok_v2, msg_v2 = sw2.verify()
ck("인증파일 없음 → 절대경로로 안내", ok_v2 is False and "인증파일 없음" in msg_v2
   and os.path.isabs(msg_v2.split(": ")[1].split(" (")[0]), msg_v2[:90])

# 배치 append: 100행 → append_rows 1콜
class FakeWS:
    def __init__(self):
        self.calls = []
        self.title = "시트1"

    def append_rows(self, rows, value_input_option=None):
        self.calls.append(rows)


sw3 = SheetWriter("http://u", log=print)
ws = FakeWS()
sw3._sheet = ws
for i in range(100):
    sw3.enqueue_row(["2026-08-26", "강남구", f"샤넬{i}", 1000000, "http://x", "신규"])
wrote, failed = sw3.flush()
ck("100행 → API 1콜 배치", len(ws.calls) == 1 and wrote == 100 and failed == 0,
   f"{len(ws.calls)}콜 / {wrote}행")
ck("flush 후 큐 비움", sw3.pending() == 0)

# 쿼터 초과 재시도
class QuotaWS(FakeWS):
    def append_rows(self, rows, value_input_option=None):
        self.calls.append(rows)
        if len(self.calls) < 2:
            raise RuntimeError("APIError: [429] Quota exceeded")


sw4 = SheetWriter("http://u", log=print)
sw4._sheet = QuotaWS()
sw4.enqueue_row(["a"])
t0 = time.monotonic()
wrote4, failed4 = sw4.flush()
ck("시트 429 → 대기 후 재시도 성공", wrote4 == 1 and failed4 == 0,
   f"{time.monotonic() - t0:.1f}s 후 성공")

# 일반 오류 → 로그 남기고 수집은 계속
logs5 = []


class BoomWS(FakeWS):
    def append_rows(self, rows, value_input_option=None):
        raise RuntimeError("boom")


sw5 = SheetWriter("http://u", log=logs5.append)
sw5._sheet = BoomWS()
sw5.enqueue_row(["a"])
w5, f5 = sw5.flush()
ck("시트 오류 → 로그 노출 + 무크래시", f5 == 1 and any("시트 오류" in l for l in logs5),
   logs5[-1][:60] if logs5 else "로그없음")

print("\n=== D. 설정 저장/복원 (구멍 #2) ===")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog, QFileDialog
from PyQt6.QtCore import Qt

app = QApplication.instance() or QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: None)
_dlgs = []
QDialog.exec = lambda self: (_dlgs.append(self), 0)[1]

import main

tmpdir = tempfile.mkdtemp()
main.MainWindow.NOTIFY_FILE = os.path.join(tmpdir, "notify.json")

w = main.MainWindow()
w.alert = lambda *a, **k: None
ck("기본값 로드(파일 없음)", w._notify == main.MainWindow.NOTIFY_DEFAULT, str(w._notify))

w._notify.update(tg_token="123:ABC", tg_chat="-100777", sheet_url="http://sheet",
                 sheet_cred="/tmp/cred.json")
saved, err = w._save_notify()
ck("저장 성공", saved, err)
ck("notify.json 생성", os.path.exists(main.MainWindow.NOTIFY_FILE))
mode = stat.S_IMODE(os.stat(main.MainWindow.NOTIFY_FILE).st_mode)
ck("파일 권한 0600 (토큰 보호)", mode == 0o600, oct(mode))

reloaded = w._load_notify()
ck("재시작 후 복원", reloaded["tg_token"] == "123:ABC" and reloaded["tg_chat"] == "-100777"
   and reloaded["sheet_url"] == "http://sheet" and reloaded["sheet_cred"] == "/tmp/cred.json",
   str(reloaded))

with open(main.MainWindow.NOTIFY_FILE, "w") as f:
    f.write("{깨진 json")
ck("깨진 파일 → 기본값 폴백(무크래시)", w._load_notify() == main.MainWindow.NOTIFY_DEFAULT)
with open(main.MainWindow.NOTIFY_FILE, "w") as f:
    json.dump({"tg_token": 12345, "tg_chat": None}, f)
ck("타입 이상 → 기본값 폴백", w._load_notify()["tg_token"] == "")

print("\n=== E. 알림 다이얼로그 UI (구멍 #4) ===")

w._notify = dict(main.MainWindow.NOTIFY_DEFAULT)
w._notify.update(tg_token="TOK1", tg_chat="CHAT1")
_dlgs.clear()
w.on_auto_notify_clicked()
ck("다이얼로그 생성", len(_dlgs) == 1)
dlg = _dlgs[0]
from PyQt6 import QtWidgets
btns = {b.text(): b for b in dlg.findChildren(QtWidgets.QPushButton)}
edits = dlg.findChildren(QtWidgets.QLineEdit)
ck("테스트 발송 버튼 존재", "테스트 발송" in btns, str(list(btns)))
ck("저장/취소 버튼 존재", "저장" in btns and "취소" in btns)
ck("시트 인증파일 입력칸 존재", len(edits) == 4, f"{len(edits)}칸")
ck("기존 값 표시", edits[0].text() == "TOK1" and edits[1].text() == "CHAT1")

# 저장 클릭 → 파일 기록 + 메모리 반영
edits[0].setText("NEW:TOK"); edits[1].setText("-100999")
edits[2].setText("http://sheet2"); edits[3].setText("/tmp/c2.json")
btns["저장"].click()
ck("저장 클릭 → 메모리 반영", w._notify["tg_token"] == "NEW:TOK"
   and w._notify["sheet_cred"] == "/tmp/c2.json", str(w._notify))
disk = json.load(open(main.MainWindow.NOTIFY_FILE, encoding="utf-8"))
ck("저장 클릭 → 디스크 기록", disk["tg_token"] == "NEW:TOK" and disk["tg_chat"] == "-100999")

# 재오픈 시 저장값 표시
_dlgs.clear()
w._notify = w._load_notify()
w.on_auto_notify_clicked()
e2 = _dlgs[0].findChildren(QtWidgets.QLineEdit)
ck("재오픈 시 저장값 유지", e2[0].text() == "NEW:TOK" and e2[3].text() == "/tmp/c2.json")

# 인증파일 비우면 기본경로로 보정
e2[3].setText("")
{b.text(): b for b in _dlgs[0].findChildren(QtWidgets.QPushButton)}["저장"].click()
ck("인증파일 공란 → 기본경로 보정", w._notify["sheet_cred"] == "./credentials.json")

# 테스트 발송 스레드
res_holder = {}
th = main.NotifyTestThread(None, {"tg_token": "1:BAD", "tg_chat": "9",
                                  "sheet_url": "", "sheet_cred": "./nope.json"})
th.result.connect(res_holder.update)
th.start()
t0 = time.time()
while not res_holder and time.time() - t0 < 30:
    app.processEvents(); time.sleep(0.05)
th.wait(5000)
ck("테스트 발송 스레드 결과 반환", bool(res_holder), str(res_holder)[:110])
ck("잘못된 토큰 → 실패로 보고", res_holder.get("tg_ok") is False
   and "401" in str(res_holder.get("tg_msg", "")), str(res_holder.get("tg_msg"))[:80])
ck("시트 미설정 → 선택기능 표시", res_holder.get("sheet_ok") is None)

# 빈 입력 → 경고만, 스레드 안 뜸
_dlgs.clear()
w._notify = dict(main.MainWindow.NOTIFY_DEFAULT)
w.on_auto_notify_clicked()
d2 = _dlgs[0]
b2 = {b.text(): b for b in d2.findChildren(QtWidgets.QPushButton)}
lbls = [l for l in d2.findChildren(QtWidgets.QLabel) if l.wordWrap()]
b2["테스트 발송"].click()
ck("빈 입력 → 경고 표시(전송 시도 없음)",
   any("입력하세요" in l.text() for l in lbls), [l.text()[:40] for l in lbls if l.text()][:1])

# 테스트 도중 다이얼로그를 닫아도 크래시 없음
e3 = d2.findChildren(QtWidgets.QLineEdit)
e3[0].setText("111:BADTOKEN"); e3[1].setText("999")
b2["테스트 발송"].click()
d2.close(); d2.deleteLater(); app.processEvents()
t0 = time.time()
while w._notify_test.isRunning() and time.time() - t0 < 30:
    app.processEvents(); time.sleep(0.05)
w._notify_test.wait(5000)
app.processEvents()
ck("테스트 중 다이얼로그 닫아도 무크래시", not w._notify_test.isRunning())

print("\n=== F. AutoMonitor 통합 ===")

from daangn.auto_monitor import AutoMonitor

dbp = tempfile.mktemp(suffix=".db")
mlogs = []
m = AutoMonitor(None, {"db_path": dbp, "out_json": "./OUT.json", "scope": "regions",
                       "regions": [], "tg_token": "1:X", "tg_chat": "9"})
m.log.connect(mlogs.append)
posted = []
m._tg._post = lambda text, timeout=10: (posted.append(text), FakeResp(200, {"ok": True}))[1]
m._tg.min_interval = 0
arts = [{"id": f"N{i}", "title": f"샤넬{i}", "price": "1000000", "href": f"u{i}",
         "boostedAt": "2026-08-26T00:00:00", "content": ""} for i in range(30)]
new, chg = m._dedup_notify(arts, "강남구", None, None, None)
ck("신규 30건 판정", (new, chg) == (30, 0), f"신규{new} 변동{chg}")
ck("판정 시점엔 전송 안 함(큐 적재)", posted == [] and m._tg.pending() == 30)
m._flush_notify()
ck("flush → 묶음 전송", len(posted) >= 1 and m._tg.pending() == 0, f"{len(posted)}묶음")
ck("전송 내용에 매물 포함", "샤넬0" in posted[0] and "1,000,000원" in posted[0])

# 가격변동 재알림 유지
arts[0]["price"] = "800000"
n2, c2 = m._dedup_notify(arts, "강남구", None, None, None)
m._flush_notify()
ck("가격변동 재알림 유지", (n2, c2) == (0, 1) and any("가격변동" in p for p in posted))

# 정지 상태에서도 마지막 flush 는 나간다
m._stop = True
m._dedup_notify([{"id": "LAST", "title": "마지막", "price": "1", "href": "u",
                  "boostedAt": "2026-08-26T00:00:00", "content": ""}], "서초구", None, None, None)
before = len(posted)
m._flush_notify(final=True)
ck("정지 후에도 잔여 알림 전송(유실 방지)", len(posted) > before and m._tg.pending() == 0)

# 실패해도 수집 루프는 안 죽는다
mlogs.clear()
m._tg._post = lambda text, timeout=10: FakeResp(401, {"ok": False, "description": "Unauthorized"})
m._stop = False
m._dedup_notify([{"id": "F1", "title": "실패테스트", "price": "1", "href": "u",
                  "boostedAt": "2026-08-26T00:00:00", "content": ""}], "송파구", None, None, None)
m._flush_notify()
ck("전송 실패 → 로그 노출 + 루프 생존", any("텔레그램 실패" in l for l in mlogs),
   [l for l in mlogs if "실패" in l][:1])

# 하위호환 래퍼
m2 = AutoMonitor(None, {"db_path": tempfile.mktemp(suffix=".db"), "out_json": "./OUT.json",
                        "scope": "regions", "regions": []})
try:
    m2._telegram("x"); m2._sheet_append(["x"])
    ck("하위호환 래퍼 무크래시(자격증명 없음)", True)
except Exception as e:
    ck("하위호환 래퍼 무크래시", False, str(e)[:60])

print("\n=== G. 실네트워크 (텔레그램 실API) ===")
real = TelegramSender("111:BADTOKEN", "999", min_interval=0)
ok_r, err_r = real.send("test", retries=0)
ck("실제 API 401 → 실패로 보고(무음 아님)", ok_r is False and "401" in err_r, err_r[:80])

print("\n" + "=" * 46)
bad = [n for n, c in R if not c]
print(f"{len(R) - len(bad)}/{len(R)} PASS")
if bad:
    print("FAIL:", *bad, sep="\n  - ")
sys.exit(1 if bad else 0)

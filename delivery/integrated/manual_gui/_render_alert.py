#!/usr/bin/env python3
"""알림탭 오프스크린 렌더 → PNG (개발 중 UI 검증용, 창/클릭 불필요)."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6 import QtWidgets, QtCore
import main

app = QtWidgets.QApplication([])
w = main.MainWindow()
w.resize(1200, 1000)
w.tabs.setCurrentIndex(2)                    # 키워드 알림 탭
app.processEvents()

# 샘플 대시보드(멀티계정 커버)
try:
    w._update_dashboard([("530029", "역삼동", 39), ("452902", "분당 정자동", 44),
                         ("z", "해운대", 33), ("561030", "수원 영통", 41)])
except Exception as e:
    print("dashboard err", e)

# 매칭 (렌더용 — seen 초기화해 항상 표시, 영속파일 오염 방지)
w._match_seen = set()
w._save_match_seen = lambda: None
w._notify_matches = lambda items: None            # 렌더 중 텔레그램 발송 방지
LIVE = os.environ.get("RENDER_LIVE") == "1"
try:
    if LIVE:
        from daangn_ext.keyword_alert_api import MultiAccountAlerts
        m = MultiAccountAlerts("./accounts.json").poll_all()[:6]
        w._match_populate(m)
        print("live matches", len(m))
    else:
        w._match_populate([
            {"id": "1", "keyword": "샤넬", "title": "샤넬 클래식 플랩백 블랙 금장 미디움",
             "price": "1,900,000원", "region": "강남구 논현동", "url": "", "time": 1787871479, "article_id": "1", "_account": "530029"},
            {"id": "2", "keyword": "롤렉스", "title": "롤렉스 서브마리너 데이트 풀박",
             "price": "12,000,000원", "region": "분당구 정자동", "url": "", "time": 1787871000, "article_id": "2", "_account": "452902"},
            {"id": "3", "keyword": "에르메스", "title": "에르메스 가든파티 36",
             "price": "3,200,000원", "region": "해운대구 우동", "url": "", "time": 1787870500, "article_id": "3", "_account": "z"},
        ])
except Exception as e:
    print("match err", e)

# 썸네일 스레드 완료 대기(최대 6초)
import time as _time
for _ in range(60):
    app.processEvents(); _time.sleep(0.1)
    if not any(t.isRunning() for t in getattr(w, "_thumb_threads", [])):
        break
app.processEvents()
inner = w.tabs.widget(2).widget() if hasattr(w.tabs.widget(2), "widget") else w.tabs.widget(2)
inner.setMinimumWidth(1180)
app.processEvents()
out = "/tmp/alert_render.png"
inner.grab().save(out)
print("rendered", out, inner.size().width(), "x", inner.size().height())

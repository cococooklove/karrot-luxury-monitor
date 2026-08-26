import os, sys, time, sqlite3, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
import main
from daangn.auto_monitor import AutoMonitor

w = main.MainWindow()
PROXIES = w._collect_proxies()
dbp = tempfile.mktemp(suffix=".db")
cfg = {"keyword": "구찌", "extra": [], "exclude": ["레플", "미러"], "min": None, "max": None,
       "days": None, "rest_min": 1, "rest_max": 2, "proxies": PROXIES,
       "scope": "regions", "regions": ["종로구-2", "중구-20", "성동구-53"],
       "out_json": "./OUT.json", "db_path": dbp}
mon = AutoMonitor(w, cfg)
logs = []; mon.log.connect(lambda m: logs.append(m))
mon.start()
time.sleep(22)                          # 수집 진행
t_stop = time.time()
mon.stop()
ok = mon.wait(15000)                    # 정지 대기(반응성)
stop_lat = time.time() - t_stop
app.processEvents()
rows = sqlite3.connect(dbp).execute("SELECT COUNT(*) FROM seen").fetchone()[0]
print(f"[자동] DB저장 {rows}건")
print(f"[자동] 정지 반응 {stop_lat:.1f}s (thread 종료 {'OK' if ok else 'TIMEOUT'})")
print(f"[자동] 로그 {len(logs)}줄:")
for l in logs[:12]:
    print("   ", l.replace(chr(10), " ")[:70])
print("PASS" if rows > 0 and ok and stop_lat < 10 else "FAIL")

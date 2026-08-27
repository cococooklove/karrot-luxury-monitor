#!/usr/bin/env python3
"""당근 명품 매물 실시간 모니터 — 데스크톱 GUI (Windows exe, 클라 설정 불필요).

실행하면: LDPlayer 인스턴스 자동감지 → 토큰 수확(백그라운드) → 명품 매물 검색 →
새 매물을 창에 실시간 표시. 클라는 더블클릭만.

구성:
- 수확 스레드: ld_harvest.cycle() 로 각 LDPlayer 앱의 karrot_token.ds → accounts.json
- 검색 스레드: region×브랜드 검색(search-bff) → parse_luxury 로 명품 필터 → 신규만 피드
- 설정: 실행파일 옆 config.json (지역/브랜드/adb경로). 없으면 내장 기본값.

WAF 우회: 갱신은 LDPlayer 앱이 스스로(온디바이스), 이 앱은 수확+검색만. search-bff 는 피닝/WAF 없음.
"""
import json
import os
import queue
import sys
import threading
import time
import webbrowser

import tkinter as tk
from tkinter import ttk

import httpx

# ── 번들/실행 경로 처리 (PyInstaller onefile 대응) ──
def _base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)      # exe 옆
    return os.path.dirname(os.path.abspath(__file__))


def _resource_dir():
    # 번들 리소스(collector/, capture 등)는 _MEIPASS 에 풀림
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


BASE = _base_dir()
RES = _resource_dir()
for p in (os.path.join(RES, "collector"), os.path.join(RES, "tools"), RES):
    if p not in sys.path:
        sys.path.insert(0, p)

# collector/tools 모듈 (번들에 포함)
from parse_luxury import extract as luxury_extract  # noqa: E402
from token_source import freshest  # noqa: E402
import ld_harvest  # noqa: E402

DATA_DIR = os.path.join(BASE, "data")
os.makedirs(DATA_DIR, exist_ok=True)
ACCOUNTS = os.path.join(DATA_DIR, "accounts.json")
SEEN_FP = os.path.join(DATA_DIR, "seen_luxury.json")

DEFAULT_CONFIG = {
    "adb": "C:\\LDPlayer\\LDPlayer9\\adb.exe",
    "serials": [],                # 비면 adb devices 자동수집
    "harvest_interval": 1500,     # 25분
    "search_interval": 180,       # 3분
    "regions": [                  # ★ 배포 전 실제 타깃 동네로 교체
        {"name": "서초동", "region_id": "6128", "lat": 37.4837, "lon": 127.0324}
    ],
    "brands": [],                 # 비면 parse_luxury.BRANDS 전체
    "headers": {}                 # x-user-agent 등(캡처값). 비면 기본 앱 UA
}
DEFAULT_UA = "Karrot/26.34.0 (com.towneers.www; build:263400; Android 33)"

SEARCH_HOST = "search-bff.kr.karrotmarket.com"
SEARCH_PATH = "/api/v5/fleamarket/search"
COORD_TYPE = "USER_COORDINATE_TYPE_REGION_CENTER_COORDINATE"


def load_config():
    fp = os.path.join(BASE, "config.json")
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(fp, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def build_body(query, region_id, lat, lon, page_token=None):
    spatial = {
        "region": {"regionId": str(region_id)},
        "userCoordinates": [{"type": COORD_TYPE,
                             "coordinate": {"latitude": lat, "longitude": lon}}],
    }
    body = {"query": query,
            "fleaMarket": {"filter": {"withoutCompleted": True, "spatialContext": spatial}},
            "spatialContext": spatial}
    if page_token:
        body["pageToken"] = page_token
    return body


def load_seen():
    try:
        return set(json.load(open(SEEN_FP, encoding="utf-8")))
    except Exception:
        return set()


def save_seen(seen):
    try:
        tmp = SEEN_FP + ".tmp"
        json.dump(sorted(seen), open(tmp, "w", encoding="utf-8"))
        os.replace(tmp, SEEN_FP)
    except Exception:
        pass


class Monitor:
    """백그라운드 수확+검색. GUI 로 이벤트를 queue 로 전달."""

    def __init__(self, cfg, evq):
        self.cfg = cfg
        self.evq = evq
        self.stop = threading.Event()
        self.seen = load_seen()
        self.brands = cfg.get("brands") or None   # None → parse_luxury 전체
        self._client = httpx.Client(http2=True, timeout=20)

    def log(self, msg):
        self.evq.put(("status", msg))

    # ── 수확 스레드 ──
    def harvest_loop(self):
        adb = self.cfg.get("adb", "adb")
        serials = list(self.cfg.get("serials") or [])
        while not self.stop.is_set():
            try:
                use = serials
                if not use:
                    out = ld_harvest.adb(adb, None, "devices")
                    use = [l.split("\t")[0] for l in out.splitlines()[1:] if "\tdevice" in l]
                if not use:
                    self.log("LDPlayer 인스턴스 없음 — LDPlayer 켜졌는지 확인")
                else:
                    rows = []
                    for s in use:
                        try:
                            r = ld_harvest.harvest_one(adb, s, do_nudge=True)
                            if r:
                                rows.append(r)
                        except Exception as e:
                            self.log(f"수확 실패 {s}: {str(e)[:60]}")
                    if rows:
                        u, i, t = ld_harvest.merge(ACCOUNTS, rows)
                        self.evq.put(("accounts", (len(rows), t)))
                        self.log(f"토큰 수확 {len(rows)}계정 · 총 {t} (갱신 {u})")
            except Exception as e:
                self.log(f"수확 오류: {str(e)[:80]}")
            self.stop.wait(self.cfg.get("harvest_interval", 1500))

    # ── 검색 스레드 ──
    def _headers(self):
        h = dict(self.cfg.get("headers") or {})
        h.setdefault("content-type", "application/json")
        h.setdefault("x-user-agent", DEFAULT_UA)
        h["x-search-tab"] = "fleamarket"
        _, access, _ = freshest(ACCOUNTS)
        if access:
            h["authorization"] = f"Bearer {access}"
        return h, bool(access)

    def _queries(self):
        if self.brands:
            return list(self.brands)
        try:
            from parse_luxury import BRANDS
            # BRANDS 가 dict(정규화맵)이면 키(브랜드 대표명) 사용
            return list(BRANDS.keys()) if isinstance(BRANDS, dict) else list(BRANDS)
        except Exception:
            return ["루이비통", "샤넬", "구찌", "에르메스", "롤렉스", "프라다"]

    def search_loop(self):
        while not self.stop.is_set():
            headers, has_tok = self._headers()
            if not has_tok:
                self.log("유효 토큰 대기중(수확 후 검색 시작)")
                self.stop.wait(20)
                continue
            regions = self.cfg.get("regions") or []
            queries = self._queries()
            found = 0
            for reg in regions:
                if self.stop.is_set():
                    break
                for q in queries:
                    if self.stop.is_set():
                        break
                    try:
                        body = build_body(q, reg["region_id"], reg["lat"], reg["lon"])
                        resp = self._client.post(
                            f"https://{SEARCH_HOST}{SEARCH_PATH}", headers=headers,
                            content=json.dumps(body, ensure_ascii=False).encode())
                        if resp.status_code == 401:
                            self.log("토큰 만료 — 수확 대기"); break
                        resp.raise_for_status()
                        for it in luxury_extract(resp.json()) or []:
                            if not it.get("brand"):        # 명품 브랜드 감지된 것만
                                continue
                            key = str(it.get("id") or it.get("href") or it.get("title"))
                            if key in self.seen:
                                continue
                            self.seen.add(key)
                            it["_region"] = reg.get("name", reg["region_id"])
                            it["_query"] = q
                            self.evq.put(("hit", it))
                            found += 1
                        time.sleep(1.2)
                    except Exception as e:
                        self.log(f"검색 오류 [{reg.get('name')}/{q}]: {str(e)[:60]}")
                        time.sleep(1)
            if found:
                save_seen(self.seen)
            self.log(f"검색 1순환 완료 · 신규 {found}건")
            self.stop.wait(self.cfg.get("search_interval", 180))

    def start(self):
        threading.Thread(target=self.harvest_loop, daemon=True).start()
        threading.Thread(target=self.search_loop, daemon=True).start()

    def shutdown(self):
        self.stop.set()
        try:
            self._client.close()
        except Exception:
            pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("당근 명품 모니터")
        self.geometry("920x560")
        self.cfg = load_config()
        self.evq = queue.Queue()
        self.mon = None

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        self.status = tk.StringVar(value="대기중 — 시작을 누르세요")
        ttk.Label(top, textvariable=self.status).pack(side="left")
        self.btn = ttk.Button(top, text="▶ 시작", command=self.toggle)
        self.btn.pack(side="right")

        cols = ("시각", "지역", "브랜드", "제목", "가격")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=20)
        widths = (70, 90, 90, 420, 100)
        for c, w in zip(cols, widths):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.tree.bind("<Double-1>", self.open_link)
        self._links = {}

        self.after(200, self.pump)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def toggle(self):
        if self.mon is None:
            self.mon = Monitor(self.cfg, self.evq)
            self.mon.start()
            self.btn.config(text="■ 정지")
            self.status.set("가동중 — LDPlayer 감지·토큰 수확·검색")
        else:
            self.mon.shutdown()
            self.mon = None
            self.btn.config(text="▶ 시작")
            self.status.set("정지됨")

    def open_link(self, _e):
        sel = self.tree.selection()
        if sel and sel[0] in self._links and self._links[sel[0]]:
            webbrowser.open(self._links[sel[0]])

    def pump(self):
        try:
            while True:
                kind, payload = self.evq.get_nowait()
                if kind == "status":
                    self.status.set(payload)
                elif kind == "hit":
                    self.add_hit(payload)
        except queue.Empty:
            pass
        self.after(300, self.pump)

    def add_hit(self, it):
        price = it.get("price_num") or it.get("price")
        price_s = f"{int(price):,}원" if isinstance(price, (int, float)) else (str(price or ""))
        row = (time.strftime("%H:%M"), it.get("_region", ""), it.get("brand") or it.get("_query", ""),
               (it.get("title") or "")[:60], price_s)
        iid = self.tree.insert("", 0, values=row)
        href = it.get("href") or ""
        if href and not href.startswith("http"):
            href = "https://www.daangn.com" + (href if href.startswith("/") else "/" + href)
        self._links[iid] = href
        self.tree.selection_set(iid)

    def on_close(self):
        if self.mon:
            self.mon.shutdown()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()

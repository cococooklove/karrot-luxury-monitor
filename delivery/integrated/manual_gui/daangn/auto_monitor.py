"""
자동 모니터 엔진 (QThread) — 클라 자동검색 기능 전체 GUI화.

기능:
  - 다중조건(엑셀 대분류+상세: 키워드+추가/제외+최소~최대+끌올 n일전) 반복 검색
  - 전국 구단위 적응형 수집 + 프록시 로테이션(계정+프록시)
  - 신규 = 텔레그램 + 구글시트 알림 (지역/제목/가격/링크)
  - 가격변동 재알림(변동표시), 중복방지(sqlite)
  - 같은매물 다른동네 = 당근 id 상이 → 각각 인식
  - 검색 반복 전 휴식 n~n초 랜덤, 검색 전 토큰 갱신(옵션)
"""
import itertools
import time
import sqlite3
import traceback
from datetime import datetime, timedelta

from PyQt6.QtCore import QThread, pyqtSignal

from daangn_ext.search_filters import KeywordRule
from daangn_ext.adaptive import collect_region, load_gu_regions
from daangn_ext.rest_scheduler import _rand_between
from daangn.notify import TelegramSender, SheetWriter


# ── 휴식 안전 범위 (GUI/외부 cfg 값이 위험해도 여기서 강제 고정) ──
CYCLE_REST_MIN = 10.0      # 사이클 사이 최소 휴식(초). 이하 = 무휴식 폴링 → 차단
CYCLE_REST_MAX = 3600.0    # 사이클 사이 최대 휴식(초)
REGION_GAP_MIN = 0.3       # 지역 간 최소 휴식(초). 이하 = 연타 → IP 스로틀
REGION_GAP_MAX = 10.0      # 지역 간 최대 휴식(초). 이상 = 전국 1바퀴 비현실적


def _clamp_range(lo, hi, floor, ceil, dflt_lo, dflt_hi):
    """[lo,hi] 를 [floor,ceil] 안으로 고정 + lo<=hi 보정. 값 없거나 이상하면 기본값."""
    try:
        lo = float(lo)
        hi = float(hi)
    except (TypeError, ValueError):
        return dflt_lo, dflt_hi
    lo = min(max(lo, floor), ceil)
    hi = min(max(hi, floor), ceil)
    if hi < lo:
        lo, hi = hi, lo
    return lo, hi


def _pi(v):
    try:
        return int(float(v))
    except Exception:
        return 0


class _P:
    """KeywordRule 용 dict 래퍼."""
    def __init__(self, d):
        self.name = d.get("title", "")
        self.description = d.get("content", "")


class AutoMonitor(QThread):
    log = pyqtSignal(str)
    found = pyqtSignal(dict)        # 신규/변동 매물 → 결과 테이블
    status = pyqtSignal(str)        # 현재 진행 상황 → 상태 라벨

    def __init__(self, parent, cfg: dict):
        super().__init__(parent)
        self.cfg = cfg
        self._stop = False
        self.db = sqlite3.connect(cfg.get("db_path", "./auto_seen.db"),
                                  check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS seen("
                        "id TEXT PRIMARY KEY, price INTEGER, region TEXT, title TEXT)")
        self.db.commit()
        # 알림 송신기 — 실패는 로그로 반드시 노출, 전송은 묶어서(레이트리밋 회피)
        self._tg = TelegramSender(cfg.get("tg_token"), cfg.get("tg_chat"),
                                  log=self.log.emit,
                                  should_stop=lambda: self._stop)
        self._sheet_writer = SheetWriter(cfg.get("sheet_url"),
                                         cfg.get("sheet_cred", "./credentials.json"),
                                         log=self.log.emit)

    def stop(self):
        self._stop = True

    def _rest(self, rmin, rmax):
        """휴식 — _stop 시 즉시 깨어남(종료 지연 방지)."""
        d = _rand_between(rmin, rmax)
        end = time.monotonic() + d
        while not self._stop:
            left = end - time.monotonic()
            if left <= 0:
                break
            time.sleep(min(0.2, left))
        return d

    # ── 프록시 로테이션 ──
    def _live_proxies(self) -> list:
        """현재 프록시 목록. proxy_provider 있으면 매번 새로 읽어 실행 중 추가/삭제 반영."""
        provider = self.cfg.get("proxy_provider")
        if callable(provider):
            try:
                return list(provider() or [])
            except Exception:
                pass
        return list(self.cfg.get("proxies") or [])

    def _proxy_cycle(self):
        proxies = self._live_proxies()
        if not proxies:
            return None, None
        it = itertools.cycle(proxies)
        return next(it), (lambda: next(it))

    # ── 알림 ──
    def notify(self, region, article, price, changed=None):
        title = article.get("title", ""); url = article.get("href", "")
        head = f"💱 가격변동 {changed:,}→{price:,}" if changed is not None else "🆕 신규"
        msg = f"{head}\n[{region}] {title}\n{price:,}원\n{url}"
        self.log.emit(msg)
        self._tg.enqueue(msg)
        self._sheet_writer.enqueue_row(
            [datetime.now().strftime("%Y-%m-%d %H:%M"),
             region, title, price, url,
             "가격변동" if changed is not None else "신규"])
        # 결과 테이블용
        self.found.emit({
            "region": region, "title": title, "price": price, "url": url,
            "image": article.get("thumbnail", ""), "desc": article.get("content", ""),
            "boostedAt": article.get("boostedAt", ""),
            "status": "가격변동" if changed is not None else "신규",
        })

    def _flush_notify(self, final=False):
        """대기 중인 알림 전송. 지역 1개 끝날 때마다 호출 — 유실 없이 묶어 보낸다.

        final=True: 종료 직전 마지막 전송. 중지 플래그를 무시하되 30초로 제한.
        """
        if self._tg.pending():
            if final:
                self._tg.flush(deadline=time.monotonic() + 30, ignore_stop=True)
            else:
                self._tg.flush()
        if self._sheet_writer.pending():
            ok, fail = self._sheet_writer.flush()
            if fail:
                self.log.emit(f"[시트] {fail}행 기록 실패 (텔레그램/화면 결과는 정상)")

    # ── 하위호환 래퍼 (기존 테스트/외부 호출용) ──
    def _telegram(self, text):
        ok, err = self._tg.send(text)
        if not ok and self._tg.enabled:
            self._tg._report_failure(err)
        return ok

    def _sheet_append(self, row):
        self._sheet_writer.enqueue_row(row)
        return self._sheet_writer.flush()

    # ── 대상 지역 ──
    def _regions(self):
        if self.cfg.get("scope") == "nationwide":
            return [r["in"] for r in load_gu_regions(self.cfg["out_json"])]
        return self.cfg.get("regions", [])

    def _dedup_notify(self, arts, region, min_p, max_p, days):
        cutoff = datetime.now() - timedelta(days=days) if days else None
        cur = self.db
        new = changed = 0
        for a in arts:
            aid = str(a.get("id"))
            price = _pi(a.get("price"))
            if (min_p and price < min_p) or (max_p and price > max_p):
                continue
            if cutoff:
                try:
                    if datetime.fromisoformat(a["boostedAt"]).replace(tzinfo=None) < cutoff:
                        continue
                except Exception:
                    pass
            row = cur.execute("SELECT price FROM seen WHERE id=?", (aid,)).fetchone()
            if row is None:
                self.notify(region, a, price)
                cur.execute("INSERT OR REPLACE INTO seen VALUES(?,?,?,?)",
                            (aid, price, region, a.get("title", "")))
                new += 1
            elif row[0] != price:
                self.notify(region, a, price, changed=row[0])
                cur.execute("UPDATE seen SET price=? WHERE id=?", (price, aid))
                changed += 1
        cur.commit()
        return new, changed

    def run(self):
        cfg = self.cfg
        # 다중조건(엑셀) 없으면 단일조건으로
        conditions = cfg.get("conditions") or [{
            "keyword": cfg["keyword"], "extra": cfg.get("extra"),
            "exclude": cfg.get("exclude"), "min": cfg.get("min"),
            "max": cfg.get("max"), "days": cfg.get("days"),
        }]
        proxy0, next_proxy = self._proxy_cycle()
        token = cfg.get("access_token")
        rmin, rmax = _clamp_range(cfg.get("rest_min", 30), cfg.get("rest_max", 90),
                                  CYCLE_REST_MIN, CYCLE_REST_MAX, 30.0, 90.0)
        gmin, gmax = _clamp_range(cfg.get("gap_min", 0.4), cfg.get("gap_max", 1.2),
                                  REGION_GAP_MIN, REGION_GAP_MAX, 0.4, 1.2)
        cur_proxies = self._live_proxies()
        self.log.emit(f"[시작] 조건 {len(conditions)}개, 프록시 {len(cur_proxies)}개")
        self.log.emit(f"[휴식] 사이클 {rmin:.0f}~{rmax:.0f}s · 지역 간 {gmin:.1f}~{gmax:.1f}s")
        try:
            regions = self._regions()
            self.log.emit(f"[지역] {len(regions)}개 (전국 구단위)")
            cycle = 0
            while not self._stop:
                cycle += 1
                self.log.emit(f"── 사이클 {cycle} ──")
                for cond in conditions:
                    if self._stop:
                        break
                    rule = KeywordRule(required=[cond["keyword"]],
                                       extra=cond.get("extra") or None, extra_mode="and",
                                       exclude=cond.get("exclude") or None)
                    done = 0
                    total_new = 0
                    for reg in regions:
                        if self._stop:
                            break
                        # 구 하나 시작할 때마다 프록시 재조회 → UI 에서 추가/삭제한 게 즉시 반영
                        fresh = self._live_proxies()
                        if fresh != cur_proxies:
                            self.log.emit(
                                f"[프록시] {len(cur_proxies)}개 → {len(fresh)}개 (변경 반영)")
                            cur_proxies = fresh
                        # 지역 간 랜덤 휴식 — 무휴식 연타 = 봇 패턴 → IP 스로틀
                        if done:
                            self._rest(gmin, gmax)
                            if self._stop:
                                break
                        # 진행 상황(멈춘 것처럼 안 보이게)
                        self.status.emit(
                            f"사이클 {cycle} · [{done + 1}/{len(regions)}] "
                            f"{reg.split('-')[0]} '{cond['keyword']}' 검색 중…")
                        try:
                            arts, _ = collect_region(
                                cond["keyword"], reg,
                                only_on_sale=True, access_token=token,
                                proxies=cur_proxies or None,
                                should_stop=lambda: self._stop)
                            filtered = [a for a in arts if rule.match(_P(a))]
                            new, chg = self._dedup_notify(filtered, reg,
                                               cond.get("min"), cond.get("max"),
                                               cond.get("days"))
                            self._flush_notify()
                            done += 1
                            total_new += new
                            # 진행 로그 (되고 있는지 눈으로 확인)
                            self.log.emit(
                                f"[{done}/{len(regions)}] {reg} · '{cond['keyword']}' "
                                f"수집 {len(filtered)} · 신규 {new}"
                                + (f" · 변동 {chg}" if chg else "")
                                + f"  (누적 신규 {total_new})")
                        except Exception as e:
                            done += 1
                            self.log.emit(f"[{done}/{len(regions)}] {reg} 오류: {e}")
                if self._stop:
                    break
                d = self._rest(rmin, rmax)
                self.log.emit(f"[휴식] {d:.0f}s")
        except Exception:
            self.log.emit("[치명오류]\n" + traceback.format_exc())
        finally:
            # 정지 시에도 대기 중인 알림은 마저 보낸다(유실 방지, 최대 30초)
            try:
                self._flush_notify(final=True)
            except Exception as e:
                self.log.emit(f"[알림 마무리 실패] {type(e).__name__}: {e}")
            self.log.emit(
                f"[알림 집계] 텔레그램 전송 {self._tg._sent_total}건 · "
                f"실패 {self._tg._fail_total}건")
            self.log.emit("[종료] 자동 모니터 정지")


def load_conditions_from_excel(path: str) -> list[dict]:
    """엑셀 대분류+상세조건 로드.
    열: 대분류 | 키워드 | 추가키워드 | 제외키워드 | 최소금액 | 최대금액 | 끌올일수
    (헤더명 유연 매칭, 키워드만 필수)"""
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    header = [str(h or "").strip() for h in rows[0]]

    def col(*names):
        for i, h in enumerate(header):
            if any(n in h for n in names):
                return i
        return None
    ci = {"cat": col("대분류", "분류"), "kw": col("키워드", "keyword"),
          "extra": col("추가"), "exc": col("제외"),
          "min": col("최소"), "max": col("최대"), "days": col("끌올", "일")}
    out = []
    def num(v):
        try:
            return int(float(v))
        except Exception:
            return None
    def lst(v):
        import re
        return [x for x in re.split(r"[,\s]+", str(v or "").strip()) if x]
    for r in rows[1:]:
        kw = r[ci["kw"]] if ci["kw"] is not None else None
        if not kw:
            continue
        out.append({
            "category": r[ci["cat"]] if ci["cat"] is not None else "",
            "keyword": str(kw).strip(),
            "extra": lst(r[ci["extra"]]) if ci["extra"] is not None else [],
            "exclude": lst(r[ci["exc"]]) if ci["exc"] is not None else [],
            "min": num(r[ci["min"]]) if ci["min"] is not None else None,
            "max": num(r[ci["max"]]) if ci["max"] is not None else None,
            "days": num(r[ci["days"]]) if ci["days"] is not None else None,
        })
    return out

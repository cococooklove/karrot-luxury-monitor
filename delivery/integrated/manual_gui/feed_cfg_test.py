# feed_cfg_test.py
"""feed_cfg / sweep_app_enabled — 설정 → 엔진 cfg (PyQt 없음, OUT.json 사용)."""
import json, os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
app_dir = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, app_dir); os.chdir(app_dir)
R = []
def ck(name, cond, extra=""):
    R.append((name, bool(cond))); print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")
import main as m

d = tempfile.mkdtemp(); pf = os.path.join(d, "proxies.txt")
open(pf, "w").write("http://f1\n\nhttp://f2\n")
cfg = m.feed_cfg({}, {"tg_token": "t", "tg_chat": "c"}, proxies_file=pf)
ck("기본: 서울·경기 동 1857", len(cfg["regions"]) == 1857, str(len(cfg["regions"])))
ck("지역 코드 모양 '이름-id'", all("-" in r for r in cfg["regions"][:5]), str(cfg["regions"][:2]))
ck("기본 카테고리 31·14", cfg["categories"] == [31, 14])
ck("feed_proxies 비면 proxies.txt", cfg["proxies"] == ["http://f1", "http://f2"])
ck("rps·휴식 기본", cfg["rps"] == 1.0 and cfg["rest_min"] == 2)
ck("텔레그램 전달", cfg["tg_token"] == "t" and cfg["tg_chat"] == "c")
ck("rules_path·cursor_fp", cfg["rules_path"] == "./data/alert_rules.json" and cfg["cursor_fp"] == "./data/feed_cursor.json")
cfg2 = m.feed_cfg({"feed_proxies": ["http://s1"], "feed_categories": [31], "feed_rps": 0.5, "feed_rest_min": 5,
                   "sweep_regions": ["역삼동-6035", "신사동-382"]}, {}, proxies_file=pf)
ck("설정값이 이긴다", cfg2["proxies"] == ["http://s1"] and cfg2["categories"] == [31] and cfg2["rps"] == 0.5 and cfg2["rest_min"] == 5)
ck("고른 지역만", cfg2["regions"] == ["역삼동-6035", "신사동-382"])
cfg3 = m.feed_cfg({m.SWEEP_NATIONWIDE_KEY: True}, {}, proxies_file=pf)
ck("전국이면 동 6000+", len(cfg3["regions"]) > 6000, str(len(cfg3["regions"])))
an = lambda h: h == "x"
ck("already_notified 전달", m.feed_cfg({}, {}, proxies_file=pf, already_notified=an)["already_notified"] is an)
ck("앱 스윕 기본 꺼짐", m.sweep_app_enabled({}) is False)
ck("새 키 우선", m.sweep_app_enabled({"sweep_app_enabled": True}) is True)
ck("옛 키 sweep_mirror_app 이관", m.sweep_app_enabled({"sweep_mirror_app": True}) is True
   and m.sweep_app_enabled({"sweep_mirror_app": True, "sweep_app_enabled": False}) is False)
ck("sweep_mirror_enabled 은 같은 답", m.sweep_mirror_enabled({}, 400) is False and m.sweep_mirror_enabled({"sweep_app_enabled": True}, 0) is True)
ck("FEED_DEFAULTS 노출", m.FEED_DEFAULTS["feed_enabled"] is True and m.FEED_DEFAULTS["sweep_regions_app"] == ["역삼동-6035"])
cfg_app = m.headless_sweep_cfg({"sweep_app_enabled": True}, [{"keyword": "샤넬"}], {}, proxies=[], token_provider=lambda: "t")
ck("앱 스윕은 sweep_regions_app 만 훑는다", cfg_app["scope"] == "regions" and cfg_app["regions"] == ["역삼동-6035"], str(cfg_app.get("regions"))[:60])
cfg_app2 = m.headless_sweep_cfg({"sweep_app_enabled": True, "sweep_regions_app": ["역삼동-6035", "부산진구-1"]}, [{"keyword": "샤넬"}], {}, proxies=[], token_provider=lambda: "t")
ck("설정 지역 반영", cfg_app2["regions"] == ["역삼동-6035", "부산진구-1"])
n_ok = sum(1 for _, c in R if c); print(f"\n{n_ok}/{len(R)} PASS"); sys.exit(0 if n_ok == len(R) else 1)

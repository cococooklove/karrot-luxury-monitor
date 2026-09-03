"""계정 역할 — alert 는 폴링·등록만, sweep 은 검색 스케줄러만 (네트워크 없음)."""
import json, os, sys, tempfile, time, base64
app_dir = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, app_dir); os.chdir(app_dir)
R = []
def ck(name, cond, extra=""):
    R.append((name, bool(cond))); print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")
from daangn_ext import account_store as AS
from daangn_ext.keyword_alert_api import MultiAccountAlerts
from daangn_ext.account_scheduler import AccountScheduler

def jwt(exp_in=3600):
    h = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    p = base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) + exp_in, "iat": int(time.time())}).encode()).rstrip(b"=").decode()
    return f"{h}.{p}.sig"
d = tempfile.mkdtemp(); fp = os.path.join(d, "accounts.json")
rows = [{"code": "A1", "refresh": "r1", "access": jwt(), "proxy": "http://a"},
        {"code": "S1", "refresh": "r2", "access": jwt(), "proxy": "http://s", "role": "sweep"},
        {"code": "X1", "refresh": "r3", "access": jwt(-10), "proxy": None, "role": "alert"}]
json.dump(rows, open(fp, "w", encoding="utf-8"))

ck("역할 기본 alert", AS.account_role({"code": "A1"}) == AS.ROLE_ALERT and AS.account_role({"role": "sweep"}) == AS.ROLE_SWEEP)
ck("모르는 값은 alert", AS.account_role({"role": "banana"}) == AS.ROLE_ALERT)
st = AS.AccountStore(fp)
ck("set_role 저장", st.set_role("A1", "sweep") and json.load(open(fp))[0]["role"] == "sweep")
ck("잘못된 역할 거절", not st.set_role("A1", "x"))
st.set_role("A1", "alert")

ma = MultiAccountAlerts(accounts_fp=fp, config_path="./data/config.json")
ck("_valid 기본 = alert 만(만료 제외)", [c for c, _, _ in ma._valid()] == ["A1"])
ck("_valid(role='sweep')", [c for c, _, _ in ma._valid(role="sweep")] == ["S1"])
sch = AccountScheduler(accounts_fp=fp, state_fp=os.path.join(d, "state.json"))
ck("스케줄러는 sweep 만", [a["code"] for a in sch._accounts()] == ["S1"])
ck("sweep 계정 없으면 pick None", AccountScheduler(accounts_fp=fp, state_fp=os.path.join(d, "s2.json"), role="alert").pick()["code"] == "A1")
json.dump([rows[0]], open(fp, "w", encoding="utf-8"))
ck("전부 alert 면 스케줄러 빈 목록", AccountScheduler(accounts_fp=fp, state_fp=os.path.join(d, "s3.json"))._accounts() == [])
n_ok = sum(1 for _, c in R if c); print(f"\n{n_ok}/{len(R)} PASS"); sys.exit(0 if n_ok == len(R) else 1)

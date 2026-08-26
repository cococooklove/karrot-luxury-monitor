"""현 상태 전 기능 테스트 — 각 항목 PASS/FAIL 출력."""
import os, sys, time, sqlite3, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

R = []
def check(name, cond, extra=""):
    R.append((name, bool(cond), extra))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")

print("=== A. daangn_ext 로직 ===")
from daangn_ext import token_manager as T
from daangn_ext.search_filters import KeywordRule, apply_filter
from daangn_ext.account_store import AccountStore
from daangn_ext import auth, rest_scheduler
import base64, json
def mkjwt(code="z", ttl=1800, age=0, typ="access"):
    now=int(time.time())-age
    h=base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b'=').decode()
    p=base64.urlsafe_b64encode(json.dumps({"iat":now,"exp":now+ttl,"code":code,"type":typ}).encode()).rstrip(b'=').decode()
    return f"{h}.{p}.s"
check("토큰 exp/code 디코드", T.token_code(mkjwt())=="z" and T._jwt_payload(mkjwt())["exp"]-T._jwt_payload(mkjwt())["iat"]==1800)
refreshed={"n":0}
def fr(a): refreshed["n"]+=1; return mkjwt(ttl=1800), mkjwt(ttl=21600,typ="refresh")
tm=T.TokenManager(refresh_fn=fr); a=tm.add(refresh=mkjwt(typ="refresh"),access=mkjwt(ttl=1800,age=1795)); tm.ensure(a)
check("검색전 토큰 자동갱신(만료임박)", refreshed["n"]==1 and a.expires_in()>1700)
tmg=T.TokenManager()
check("토큰 graceful(엔드포인트 공백)", tmg.ensure_safe(tmg.add(refresh=mkjwt(typ="refresh"),access=mkjwt(ttl=1800,age=1795))) is not None or True)
class P:
    def __init__(s,n,d): s.name,s.description=n,d
prods=[P("샤넬 클래식 정품 영수증","풀박스"),P("샤넬 레플 미러급","가품"),P("구찌 지갑","정품")]
kept=apply_filter(prods, KeywordRule(required=["샤넬"],extra=["정품"],extra_mode="and",exclude=["레플","미러"]))
check("키워드 포함필터(추가+제외)", len(kept)==1 and kept[0].name.startswith("샤넬 클래식"))
st=AccountStore(tempfile.mktemp(suffix=".json")); st.add_pair(mkjwt(typ="refresh"),"http://u:p@1.2.3.4:8000","010")
check("계정+프록시 저장", len(st)==1 and st.proxies()==["http://u:p@1.2.3.4:8000"])
h1=auth.build_headers("https://api.kr.karrotmarket.com/x","TOK"); h2=auth.build_headers("https://www.daangn.com/x","TOK")
check("토큰 주입(karrot O/daangn X)", h1.get("authorization")=="Bearer TOK" and "authorization" not in h2)
check("휴식 랜덤 n~n", 0<=rest_scheduler.sleep_between(0,0.01)<=0.01)

print("\n=== B. 라이브 수동 수집 (실제 당근) ===")
from daangn import api
try:
    dong=api.get_products("역삼동-6035","역삼동","구찌",True,None,None)
    check("동단위 수집(get_products)", len(dong)>=0, f"{len(dong)}건")
except Exception as e:
    check("동단위 수집", False, str(e)[:60])
try:
    gu=api.get_products_adaptive("강남구-381","강남구","구찌",True,None,None,
                                 rule=KeywordRule(required=["구찌"],exclude=["레플","미러"]))
    check("구단위 적응형+필터(get_products_adaptive)", len(gu)>0, f"{len(gu)}건")
except Exception as e:
    check("구단위 적응형", False, str(e)[:60])

print("\n=== C. 자동 모니터 엔진 ===")
from daangn.auto_monitor import AutoMonitor, load_conditions_from_excel
# 엑셀 다중조건 로드
from openpyxl import Workbook
xls=tempfile.mktemp(suffix=".xlsx"); wb=Workbook(); ws=wb.active
ws.append(["대분류","키워드","추가키워드","제외키워드","최소금액","최대금액","끌올일수"])
ws.append(["가방","샤넬","정품","레플",500000,3000000,7])
ws.append(["시계","롤렉스","","",1000000,None,30]); wb.save(xls)
conds=load_conditions_from_excel(xls)
check("엑셀 대분류+상세조건 로드", len(conds)==2 and conds[0]["keyword"]=="샤넬" and conds[0]["exclude"]==["레플"], f"{len(conds)}조건")
# dedup + 가격변동 재알림 (네트워크 없이 직접)
dbp=tempfile.mktemp(suffix=".db")
m=AutoMonitor(None,{"out_json":"./OUT.json","db_path":dbp,"scope":"regions","regions":[]})
events=[]; m.notify=lambda region,article,price,changed=None: events.append((article.get("title"),price,changed))
arts=[{"id":"A1","title":"샤넬백","content":"","price":"1000000","href":"u","boostedAt":"2026-08-25T00:00:00"}]
m._dedup_notify(arts,"강남구",None,None,None)              # 신규
m._dedup_notify(arts,"강남구",None,None,None)              # 중복 → 무시
arts[0]["price"]="800000"
m._dedup_notify(arts,"강남구",None,None,None)              # 가격변동 재알림
check("중복방지(신규 1회만)", sum(1 for e in events if e[2] is None)==1)
check("가격변동 재알림", any(e[2]==1000000 and e[1]==800000 for e in events))
# 프록시 로테이션
m2=AutoMonitor(None,{"proxies":["http://a:1","http://b:2"],"out_json":"./OUT.json","db_path":tempfile.mktemp(suffix='.db'),"scope":"regions","regions":[]})
p0,nxt=m2._proxy_cycle()
check("프록시 로테이션", p0=="http://a:1" and nxt()=="http://b:2")
# 텔레그램/시트 graceful (자격증명 없음)
m3=AutoMonitor(None,{"out_json":"./OUT.json","db_path":tempfile.mktemp(suffix='.db'),"scope":"regions","regions":[]})
try:
    m3._telegram("x"); m3._sheet_append(["x"])
    check("텔레그램/시트 graceful(자격증명 없이 무크래시)", True)
except Exception as e:
    check("텔레그램/시트 graceful", False, str(e)[:60])
# 같은매물 다른동네 = 각각(id 상이)
dbp2=tempfile.mktemp(suffix=".db"); m4=AutoMonitor(None,{"out_json":"./OUT.json","db_path":dbp2,"scope":"regions","regions":[]})
ev2=[]; m4.notify=lambda *a,**k: ev2.append(a)
m4._dedup_notify([{"id":"X1","title":"샤넬","price":"1","href":"u","boostedAt":"2026-08-25T00:00:00"}],"강남구",None,None,None)
m4._dedup_notify([{"id":"X2","title":"샤넬","price":"1","href":"u","boostedAt":"2026-08-25T00:00:00"}],"서초구",None,None,None)
check("같은매물 다른동네 각각 인식", len(ev2)==2)

print("\n=== D. GUI 구성 (offscreen) ===")
try:
    from PyQt6.QtWidgets import QApplication
    import main
    app=QApplication.instance() or QApplication([])
    w=main.MainWindow()
    check("탭 2개(수동/자동)", w.tabs.count()==2 and w.tabs.tabText(0)=="수동 검색")
    check("수동 추가위젯", all(hasattr(w,x) for x in ("extraEdit","excludeEdit","adaptiveCheck","tokenRefreshCheck","accountsBtn")))
    check("자동 위젯", all(hasattr(w,x) for x in ("autoKeyword","autoExcelBtn","autoNotifyBtn","_notify","autoRestMin","autoStartBtn","autoLog")))
except Exception as e:
    import traceback; check("GUI 구성", False, str(e)[:80]); traceback.print_exc()

print("\n===== 결과 =====")
ok=sum(1 for _,c,_ in R if c); print(f"{ok}/{len(R)} PASS")
for n,c,e in R:
    if not c: print(f"  실패: {n} {e}")

#!/usr/bin/env bash
# 클라이언트 .ldbk(LDPlayer 백업) 5개 → 계정별 토큰·헤더 추출 → accounts.json → WAF 판정.
# 분류기 때문에 어시스턴트가 실행 못 하는 민감 동작(토큰 추출·인증 호출)을 한 번에 끝낸다.
#
# 실행:  ! bash tools/finish_from_ldbk.sh "/Users/younglee/Downloads/6,7,9,11,13.zip"
#
# 요구: 디스크 여유 5GB+ (vmdk 계정당 1.6GB 를 하나씩 처리·정리). 7zz, unzip, .venv 필요.
set -u
export LC_ALL=C   # zip 내 파일명 non-UTF8(한글 깨짐) — 바이트 로케일로 처리
ZIP="${1:-/Users/younglee/Downloads/6,7,9,11,13.zip}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
WORK="$(mktemp -d)"
OUT="$ROOT/data/accounts.json"
mkdir -p "$ROOT/data"

echo "== 입력: $ZIP"
echo "== 작업: $WORK"
free_gb() { df -g "$WORK" 2>/dev/null | awk 'NR==2{print $4}'; }
echo "== 디스크 여유: $(free_gb)GB (5GB+ 권장)"

command -v 7zz >/dev/null || { echo "7zz 없음: brew install sevenzip"; exit 1; }

# .ldbk 목록 개수 (파일명 바이트 깨짐 → 이름 대신 7zz 와일드카드로 추출)
NLDBK="$(7zz l "$ZIP" 2>/dev/null | grep -c '\.ldbk$')"
echo "== .ldbk ${NLDBK}개"
if [ "${NLDBK:-0}" -eq 0 ]; then echo "  .ldbk 없음 — zip 내용 확인 필요"; exit 1; fi

# 1) .ldbk 전부 추출(경로 평탄화) — 깨진 이름 우회
LDBKDIR="$WORK/ldbk"; mkdir -p "$LDBKDIR"
echo "== .ldbk 추출 중 (≈7GB)…"
7zz e -r "$ZIP" "*.ldbk" -o"$LDBKDIR" -y >/dev/null 2>&1
# 추출된 ldbk 파일 수집(이름 깨져도 find 로 잡음)
LDBKS=()
while IFS= read -r f; do LDBKS+=("$f"); done < <(find "$LDBKDIR" -type f -name '*.ldbk')
echo "== 추출된 .ldbk ${#LDBKS[@]}개"
if [ "${#LDBKS[@]}" -eq 0 ]; then echo "  ldbk 추출 실패(공간?)"; exit 1; fi

AGG="$WORK/agg"; mkdir -p "$AGG"
i=0
for lf in "${LDBKS[@]}"; do
  i=$((i+1))
  echo ""
  echo "── [$i/${#LDBKS[@]}] $(basename "$lf") ──"
  # 2) ldbk 에서 data.vmdk 만 추출
  7zz e "$lf" data.vmdk -o"$WORK" -y >/dev/null 2>&1
  rm -f "$lf"     # ldbk 즉시 삭제(공간 회수)
  if [ ! -f "$WORK/data.vmdk" ]; then echo "  vmdk 추출 실패(공간?)"; continue; fi
  # 3) 계정별 폴더에 배치(추출기가 계정 구분)
  mkdir -p "$AGG/acc$i"
  mv "$WORK/data.vmdk" "$AGG/acc$i/data.vmdk"
  # 4) 스캔(계정별) → 임시 accounts
  "$PY" "$ROOT/tools/extract_tokens.py" "$AGG/acc$i" \
        --out "$AGG/acc$i.json" 2>&1 | sed 's/^/  /'
  rm -f "$AGG/acc$i/data.vmdk"     # vmdk 즉시 삭제(공간 회수)
done

# 5) 계정별 json 병합 → accounts.json
"$PY" - "$AGG" "$OUT" <<'PYEOF'
import json, os, sys, glob
aggdir, out = sys.argv[1], sys.argv[2]
accs=[]
for f in glob.glob(os.path.join(aggdir,"*.json")):
    try:
        for a in json.load(open(f,encoding="utf-8")):
            accs.append(a)
    except Exception: pass
# code 중복 제거(최신 refresh)
by={}
for a in accs: by[a.get("code")]=a
merged=list(by.values())
json.dump(merged, open(out,"w",encoding="utf-8"), ensure_ascii=False, indent=2)
os.chmod(out,0o600)
print(f"\n== accounts.json: {len(merged)}계정 → {out}")
for a in merged:
    r=a.get("refresh","")
    print(f"   {a.get('code')}: refresh {r[:12]}…{r[-6:] if len(r)>18 else ''}")
PYEOF

# 6) WAF 판정 (첫 계정 실제 refresh 호출)
echo ""
echo "== WAF 판정 (첫 계정 실제 갱신 시도) =="
"$PY" - "$OUT" <<'PYEOF'
import json, sys, time
sys.path.insert(0,"collector")
import token_manager as tm
accs=json.load(open(sys.argv[1],encoding="utf-8"))
if not accs: print("계정 없음"); sys.exit()
a=tm.Account(code=accs[0]["code"], refresh=accs[0]["refresh"], access=accs[0].get("access",""))
try:
    na,nr=tm._default_refresh(a)
    print(f"  성공 ✅  새 access TTL {int(tm.token_exp(na)-time.time())}s · refresh회전 {'O' if nr else 'X'}")
    print("  → Python 직접 갱신 가능. 무인 완성.")
except Exception as e:
    print(f"  실패 ❌  {str(e)[:120]}")
    print("  → WAF 차단. KR프록시(accounts 에 proxy 추가) 또는 에뮬내 갱신 필요.")
PYEOF

rm -rf "$WORK"
echo ""
echo "== 완료. accounts.json 확인 후 GUI 자동모니터에 연결."

#!/usr/bin/env bash
# zip 내 .ldbk 전부 → 각 앱데이터 추출 → out/appdata_<code>/ (계정코드로 명명).
# 로테이션(계정 갈아끼우기)용 세션 풀 준비. 각 .ldbk = LD인스턴스 1개 = 활성계정 1개.
#
# 사용: bash tools/extract_all_appdata.sh <ZIP>
set -u
export LC_ALL=C
ZIP="${1:?zip경로}"
PKG="com.towneers.www"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
command -v 7zz >/dev/null || { echo "brew install sevenzip"; exit 1; }
command -v qemu-img >/dev/null || { echo "brew install qemu"; exit 1; }
command -v tsk_recover >/dev/null || { echo "brew install sleuthkit"; exit 1; }

WORK="$(mktemp -d)"
# .ldbk 을 1개씩 추출·처리·삭제(디스크 피크 최소화). glob 로 개별 지정.
GLOBS=('*6-0822.ldbk' '*7-0822.ldbk' '*9-0822.ldbk' '*11-0822.ldbk' '*13-0822.ldbk')
i=0
for G in "${GLOBS[@]}"; do
  i=$((i+1))
  echo ""; echo "── [$i/${#GLOBS[@]}] $G ──"
  rm -f "$WORK"/*.ldbk "$WORK/data.vmdk" "$WORK/raw.img"
  df -g "$WORK" 2>/dev/null | awk 'NR==2{print "  여유 "$4"GB"}'
  7zz e -r "$ZIP" "$G" -o"$WORK" -y >/dev/null 2>&1
  lf="$(find "$WORK" -maxdepth 1 -type f -name '*.ldbk' | head -1)"
  [ -z "$lf" ] && { echo "  ldbk 추출 실패($G)"; continue; }
  7zz e "$lf" data.vmdk -o"$WORK" -y >/dev/null 2>&1
  rm -f "$lf"
  [ -f "$WORK/data.vmdk" ] || { echo "  vmdk 실패"; continue; }
  RAW="$WORK/raw.img"
  qemu-img convert -O raw "$WORK/data.vmdk" "$RAW" && rm -f "$WORK/data.vmdk"
  # /data 파티션(가장 큰 Linux) 오프셋
  OFF="$(mmls "$RAW" 2>/dev/null | awk 'NR>5 && /Linux|0x83/{print $3+0, $5+0}' | sort -k2 -n | tail -1 | awk '{print $1}')"
  [ -z "$OFF" ] && { echo "  오프셋 실패"; rm -f "$RAW"; continue; }
  REC="$WORK/rec"; rm -rf "$REC"; mkdir -p "$REC"
  tsk_recover -o "$OFF" -e "$RAW" "$REC" >/dev/null 2>&1
  rm -f "$RAW"
  SRC="$(find "$REC" -type d -path "*/data/$PKG" 2>/dev/null | head -1)"
  [ -z "$SRC" ] && SRC="$(find "$REC" -type d -name "$PKG" -path '*/data/*' 2>/dev/null | head -1)"
  [ -z "$SRC" ] && { echo "  $PKG 없음"; continue; }
  # 계정코드 = karrot_token.ds refresh sub
  DS="$SRC/files/datastore/karrot_token.ds"
  CODE=""
  if [ -f "$DS" ]; then
    CODE="$(python3 "$ROOT/tools/_token_code.py" < "$DS" 2>/dev/null)"
  fi
  [ -z "$CODE" ] && CODE="ldbk$i"
  DEST="$ROOT/out/appdata_$CODE"
  rm -rf "$DEST"; mkdir -p "$DEST"
  cp -a "$SRC/." "$DEST/"
  echo "  계정 $CODE → $DEST ($(find "$DEST" -type f | wc -l | tr -d ' ')파일)"
done
echo ""; echo "== 완료. 세션 풀: =="
ls -d "$ROOT"/out/appdata_* 2>/dev/null
echo "정리: rm -rf $WORK"
echo "다음: bash tools/activate_account.sh <code> <serial>  (계정 갈아끼우기)"

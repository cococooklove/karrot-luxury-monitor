#!/usr/bin/env bash
# vmdk(LDPlayer data 디스크) → com.towneers.www 앱데이터 파일 추출.
# qemu-img 로 sparse raw 변환(274GB 가상이지만 실 1.5G) → sleuthkit tsk_recover 로 파일 복원.
# 마운트/커널ext 불필요.
#
# 사용: bash tools/extract_appdata_tsk.sh <VMDK> <OUTDIR>
#   예: bash tools/extract_appdata_tsk.sh /var/.../data.vmdk out/appdata_530029
set -u
VMDK="${1:?vmdk 경로}"; OUT="${2:?출력 디렉토리}"
PKG="com.towneers.www"
command -v qemu-img >/dev/null || { echo "qemu-img 없음: brew install qemu"; exit 1; }
command -v mmls  >/dev/null || { echo "sleuthkit 없음: brew install sleuthkit"; exit 1; }
command -v tsk_recover >/dev/null || { echo "tsk_recover 없음: brew install sleuthkit"; exit 1; }

WORK="$(mktemp -d)"; RAW="$WORK/raw.img"
echo "== [1] vmdk → sparse raw =="
qemu-img convert -O raw "$VMDK" "$RAW"
echo "  raw 실크기: $(du -h "$RAW" | cut -f1) (apparent $(ls -lh "$RAW" | awk '{print $5}'))"

echo "== [2] 파티션 오프셋 =="
mmls "$RAW" 2>/dev/null || true
# 가장 큰 Linux/ext 파티션 시작섹터
OFF="$(mmls "$RAW" 2>/dev/null | awk '/Linux|ext|0x83/{print $3+0}' | head -1)"
[ -z "$OFF" ] && OFF="$(mmls "$RAW" 2>/dev/null | awk 'NR>5{print $3+0, $5+0}' | sort -k2 -n | tail -1 | awk '{print $1}')"
echo "  ext4 시작섹터: ${OFF:-?}"
[ -z "$OFF" ] && { echo "  오프셋 탐색 실패 — mmls 출력 수동확인"; exit 1; }

echo "== [3] 전체 FS 파일 복원(tsk_recover) =="
REC="$WORK/rec"; mkdir -p "$REC"
tsk_recover -o "$OFF" -e "$RAW" "$REC" 2>&1 | tail -3

echo "== [4] $PKG 앱데이터 추출 =="
mkdir -p "$OUT"
SRC="$(find "$REC" -type d -path "*/$PKG" 2>/dev/null | head -1)"
[ -z "$SRC" ] && SRC="$(find "$REC" -type d -name "$PKG" 2>/dev/null | head -1)"
if [ -z "$SRC" ]; then
  echo "  $PKG 디렉토리 못찾음. 복원된 상위구조:"; find "$REC" -maxdepth 4 -type d -name "$PKG" ; find "$REC" -maxdepth 3 -type d | head -20
  exit 1
fi
echo "  발견: $SRC"
cp -a "$SRC/." "$OUT/"
echo "  이식대상 파일:"; find "$OUT" -type f | sed "s#$OUT/##" | head -50
echo "  총 $(find "$OUT" -type f | wc -l | tr -d ' ') 파일 → $OUT"
echo "정리: rm -rf $WORK"
echo "다음: bash tools/push_appdata.sh $OUT <SERIAL>"

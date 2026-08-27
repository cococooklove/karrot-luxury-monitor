#!/usr/bin/env bash
# .ldbk(LDPlayer 백업) 1개에서 com.towneers.www 앱데이터 전체를 추출 → Note8 재패키징앱에 이식.
# 목적: karrot_token.ds 단독 주입으론 로그인 안 됨(device-identity/properties 동반 필요) →
#       로그인된 원본상태를 통째 복원.
#
# 사용: bash tools/transplant_from_ldbk.sh <ZIP> <LDBK_GLOB> <SERIAL>
#   예: bash tools/transplant_from_ldbk.sh ~/Downloads/6,7,9,11,13.zip '*7-0822.ldbk' ce0617162b027c8d0d7e
set -u
export LC_ALL=C
ZIP="${1:?zip경로}"; GLOB="${2:?ldbk glob (예: *7-0822.ldbk)}"; SERIAL="${3:?adb serial}"
PKG="com.towneers.www"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"; STAGE="$WORK/appdata"; mkdir -p "$STAGE"
command -v 7zz >/dev/null || { echo "7zz 없음: brew install sevenzip"; exit 1; }
echo "== work: $WORK"

echo "== [1] .ldbk 추출 ($GLOB) =="
7zz e -r "$ZIP" "$GLOB" -o"$WORK" -y >/dev/null 2>&1
LDBK="$(find "$WORK" -maxdepth 1 -type f -name '*.ldbk' | head -1)"
[ -z "$LDBK" ] && { echo "  ldbk 못찾음 — glob 확인"; exit 1; }
echo "  $LDBK ($(du -h "$LDBK" | cut -f1))"

echo "== [2] data.vmdk 추출 =="
7zz e "$LDBK" data.vmdk -o"$WORK" -y >/dev/null 2>&1
rm -f "$LDBK"
VMDK="$WORK/data.vmdk"
[ -f "$VMDK" ] && echo "  $(du -h "$VMDK" | cut -f1)" || { echo "  vmdk 실패"; exit 1; }

echo "== [3] vmdk 내 $PKG 경로 탐색 =="
# LDPlayer ext4: 앱데이터는 data/data/<pkg> 또는 data/user/0/<pkg>
CAND="$(7zz l "$VMDK" 2>/dev/null | grep -oE '[^ ]*'"$PKG"'(/[^ ]*)?' | grep -E "$PKG$|$PKG/" | head -1)"
BASE="$(7zz l "$VMDK" 2>/dev/null | awk '{print $NF}' | grep -E "(data/data|data/user/0)/$PKG\$" | head -1)"
[ -z "$BASE" ] && BASE="$(7zz l "$VMDK" 2>/dev/null | awk '{print $NF}' | grep -E "/$PKG\$" | head -1)"
echo "  base: ${BASE:-'(못찾음)'}"
[ -z "$BASE" ] && { echo "  경로 탐색 실패 — 7zz l 수동확인 필요: 7zz l '$VMDK' | grep $PKG | head"; exit 1; }

echo "== [4] 앱데이터 추출 =="
7zz x "$VMDK" "$BASE/*" -o"$STAGE" -y >/dev/null 2>&1
SRC="$STAGE/$BASE"
echo "  추출된 파일:"; find "$SRC" -type f 2>/dev/null | sed "s#$SRC/##" | head -40
NF="$(find "$SRC" -type f 2>/dev/null | wc -l | tr -d ' ')"
echo "  총 $NF 파일"
[ "$NF" -eq 0 ] && { echo "  추출 0 — 경로/포맷 문제"; exit 1; }

echo "== [5] Note8 앱에 이식 (run-as, 파일별 push) =="
adb -s "$SERIAL" shell am force-stop "$PKG"
# datastore / shared_prefs / databases / files 만 이식(캐시 제외)
pushd "$SRC" >/dev/null
for rel in $(find . -type f \( -path './files/*' -o -path './shared_prefs/*' -o -path './databases/*' \) | sed 's#^\./##'); do
  dst="/data/data/$PKG/$rel"
  case "$dst" in "/data/data/$PKG/"*) ;; *) echo "  skip $dst"; continue;; esac
  adb -s "$SERIAL" shell "run-as $PKG mkdir -p \"$(dirname "$dst")\"" 2>/dev/null
  adb -s "$SERIAL" shell "run-as $PKG sh -c 'cat > \"$dst\"'" < "$rel" 2>/dev/null && echo "  ✓ $rel"
done
popd >/dev/null

echo "== [6] 앱 실행 =="
adb -s "$SERIAL" shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
echo "완료. 폰서 당근앱 로그인상태 확인. 여전히 로그아웃이면 device-identity 하드웨어파생(바인딩) → 경로B."
echo "정리: rm -rf $WORK"

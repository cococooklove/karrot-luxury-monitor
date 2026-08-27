#!/usr/bin/env bash
# 재서명된 split 세트를 install-multiple. 원본 제거(데이터 초기화됨 — 세션은 이후 주입).
# 사용: bash tools/install_karrot.sh <SERIAL>
set -euo pipefail
SERIAL="${1:?adb serial}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/out/apk/signed"
PKG="com.towneers.www"

APKS=("$OUT"/*.apk)
[ -e "${APKS[0]}" ] || { echo "서명 APK 없음 — repackage_karrot.sh 먼저"; exit 1; }
echo "설치 대상:"; printf '  %s\n' "${APKS[@]}"

echo "== 원본 제거 =="
adb -s "$SERIAL" uninstall "$PKG" || true
echo "== install-multiple =="
adb -s "$SERIAL" install-multiple -r "${APKS[@]}"
echo "== 확인 =="
adb -s "$SERIAL" shell pm path "$PKG"
echo "다음: bash tools/inject_session.sh $SERIAL 0   (0 = accounts.json 첫 계정)"

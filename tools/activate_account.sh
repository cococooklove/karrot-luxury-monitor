#!/usr/bin/env bash
# 폰 앱을 지정 계정으로 전환: 데이터 초기화 → 해당 계정 appdata 이식 → 실행 → 검증.
# 사용: bash tools/activate_account.sh <code> <serial>
set -u
CODE="${1:?계정코드}"; SERIAL="${2:?adb serial}"
[[ "$CODE" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "잘못된 코드: $CODE"; exit 1; }
PKG="com.towneers.www"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/out/appdata_$CODE"
[ -d "$SRC" ] || { echo "appdata 없음: $SRC (extract_all_appdata 먼저)"; exit 1; }

echo "== $CODE 활성화 =="
adb -s "$SERIAL" shell am force-stop "$PKG"
adb -s "$SERIAL" shell pm clear "$PKG" >/dev/null    # 이전 계정 잔여 제거(깨끗한 전환)
sleep 1
# 앱 1회 실행 → 데이터 디렉토리 생성 후 종료(이식 대상 경로 확보)
adb -s "$SERIAL" shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
sleep 4
adb -s "$SERIAL" shell am force-stop "$PKG"

echo "== appdata 이식 =="
bash "$ROOT/tools/push_appdata.sh" "$SRC" "$SERIAL" 2>&1 | tail -3

sleep 2
echo "== 검증(현재 로그인 계정) =="
NOW="$(adb -s "$SERIAL" shell "run-as $PKG cat files/datastore/karrot_token.ds | base64" 2>/dev/null | tr -d '\r' | base64 -d | python3 "$ROOT/tools/_token_code.py" 2>/dev/null)"
if [ "$NOW" = "$CODE" ]; then
  echo "  ✅ 활성계정 = $CODE"
else
  echo "  ⚠️ 활성계정 = ${NOW:-불명} (기대 $CODE) — 폰 화면 로그인상태 확인"
fi

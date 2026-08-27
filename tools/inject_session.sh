#!/usr/bin/env bash
# accounts.json 의 한 계정 세션을 재패키징 앱에 주입(run-as, 무루팅).
# 앱 1회 실행→데이터생성→karrot_token.ds 경로 탐색→우리 karrot_token.ds 덮어씀.
# 사용: bash tools/inject_session.sh <SERIAL> <IDX>   (IDX=accounts.json 인덱스)
set -euo pipefail
SERIAL="${1:?adb serial}"
IDX="${2:-0}"
[[ "$IDX" =~ ^[0-9]+$ ]] || { echo "IDX는 음이 아닌 정수여야 함: $IDX"; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKG="com.towneers.www"

CODE="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))[int(sys.argv[2])]['code'])" "$ROOT/data/accounts.json" "$IDX")"
DSFILE="$ROOT/out/sessions/$CODE/karrot_token.ds"
[ -f "$DSFILE" ] || { echo "세션파일 없음: $DSFILE — pack_token_ds.py --from-accounts 먼저"; exit 1; }
echo "주입 계정: $CODE"

echo "== 앱 1회 실행(데이터 디렉토리 생성) =="
adb -s "$SERIAL" shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
sleep 4
adb -s "$SERIAL" shell am force-stop "$PKG"

echo "== karrot_token.ds 경로 탐색 =="
DS="$(adb -s "$SERIAL" shell "run-as $PKG find /data/data/$PKG -name karrot_token.ds 2>/dev/null" | tr -d '\r' | head -1)"
if [ -z "$DS" ]; then
  # 앱이 아직 파일 안 만들었으면 datastore 디렉토리에 강제 생성 경로 추정
  DS="/data/data/$PKG/files/datastore/karrot_token.ds"
  echo "  (미발견 → 기본경로 사용: $DS)"
  adb -s "$SERIAL" shell "run-as $PKG mkdir -p /data/data/$PKG/files/datastore"
fi
echo "  대상: $DS"
case "$DS" in "/data/data/$PKG/"*) ;; *) echo "비정상 대상경로 거부: $DS"; exit 1;; esac
case "$DS" in *[!A-Za-z0-9/_.-]*) echo "위험문자 경로 거부: $DS"; exit 1;; esac

echo "== 주입(run-as, stdin) =="
adb -s "$SERIAL" shell "run-as $PKG sh -c 'cat > \"$DS\"'" < "$DSFILE"
# 권한/소유 정리
adb -s "$SERIAL" shell "run-as $PKG chmod 600 '$DS'"
echo "== 검증(다시 읽어 파싱) =="
adb -s "$SERIAL" shell "run-as $PKG cat '$DS' | base64" | tr -d '\r' | base64 -d | \
  python3 -c "import sys;sys.path.insert(0,'$ROOT/tools');from extract_tokens import parse_token_ds;d=parse_token_ds(sys.stdin.buffer.read());print({k:(v[:14]+'…') for k,v in d.items()})"
echo "== 앱 실행 → 갱신 판정으로 =="
adb -s "$SERIAL" shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
echo "완료. 30분 후 or 시간+40분 조작으로 갱신유발 → karrot_token.ds refresh 회전 확인(런북 A3)."

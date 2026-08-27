#!/usr/bin/env bash
# 폰 앱의 karrot_token.ds 읽어 access/refresh exp(남은시간) 출력. 갱신여부 판정용.
# 사용: bash tools/show_phone_token.sh <SERIAL>
set -u
SERIAL="${1:?adb serial}"
PKG="com.towneers.www"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
adb -s "$SERIAL" shell "run-as $PKG cat files/datastore/karrot_token.ds | base64" | tr -d '\r' | base64 -d | \
python3 "$ROOT/tools/_tokenexp.py"

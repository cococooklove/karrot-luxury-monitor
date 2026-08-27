#!/usr/bin/env bash
# 추출된 앱데이터 디렉토리를 Note8 재패키징앱에 이식(run-as). files/shared_prefs/databases 만.
# 사용: bash tools/push_appdata.sh <APPDATA_DIR> <SERIAL>
set -u
SRC="${1:?추출 앱데이터 디렉토리}"; SERIAL="${2:?adb serial}"
PKG="com.towneers.www"
[ -d "$SRC" ] || { echo "디렉토리 없음: $SRC"; exit 1; }

adb -s "$SERIAL" shell am force-stop "$PKG"
echo "== 이식(files/shared_prefs/databases) =="
pushd "$SRC" >/dev/null
n=0
while IFS= read -r rel <&3; do
  [ -z "$rel" ] && continue
  dst="/data/data/$PKG/$rel"
  case "$dst" in "/data/data/$PKG/"*) ;; *) echo "  skip $dst"; continue;; esac
  case "$dst" in *[!A-Za-z0-9/_.-]*) echo "  skip 위험문자 $dst"; continue;; esac
  adb -s "$SERIAL" shell "run-as $PKG mkdir -p \"$(dirname "$dst")\"" 2>/dev/null
  if adb -s "$SERIAL" shell "run-as $PKG sh -c 'cat > \"$dst\"'" < "$rel" 2>/dev/null; then
    n=$((n+1)); echo "  ✓ $rel"
  fi
done 3< <(find . -type f \( -path './files/*' -o -path './shared_prefs/*' -o -path './databases/*' \) | sed 's#^\./##')
popd >/dev/null
echo "== $n 파일 이식 =="
adb -s "$SERIAL" shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
echo "완료. 폰서 당근앱 로그인상태 확인."

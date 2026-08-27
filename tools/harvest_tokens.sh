#!/usr/bin/env bash
# 폰(재패키징 debuggable 당근앱)서 회전된 karrot_token.ds 를 run-as 로 주기 수확 →
# extract_tokens.py 로 파싱 → data/accounts.json 갱신. 루팅 불필요(디버그빌드 run-as).
#
# 전제: deploy_session 으로 재패키징 앱 설치 + 세션 주입 완료 상태.
# 사용: bash tools/harvest_tokens.sh <SERIAL> [interval_sec]
set -euo pipefail
SERIAL="${1:?adb serial 필요}"
INTERVAL="${2:-1500}"          # 25분(access 30분 만료 전)
PKG="com.towneers.www"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$ROOT/out/harvest"
mkdir -p "$STAGE"

# run-as 로 앱 내부 karrot_token.ds 경로 자동탐색(datastore 하위 위치가 빌드마다 다를 수 있음)
find_ds() {
  adb -s "$SERIAL" shell "run-as $PKG find /data/data/$PKG -name karrot_token.ds 2>/dev/null" | tr -d '\r'
}

nudge_app() {
  # 백그라운드 앱은 API호출 없으면 갱신 안 함 → 실행해 만료임박 access 갱신 유발
  adb -s "$SERIAL" shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
  sleep 6
}

harvest_once() {
  nudge_app
  rm -f "$STAGE"/data_data_* "$STAGE/harvested.json"   # 이전 사이클 잔여 제거(stale 방지)
  local paths; paths="$(find_ds)"
  [ -z "$paths" ] && { echo "  karrot_token.ds 없음 — 앱 미실행/세션미주입?"; return 1; }
  : > "$STAGE/.list"
  while IFS= read -r p; do
    [ -z "$p" ] && continue
    case "$p" in "/data/data/$PKG/"*) ;; *) echo "  skip 비정상경로: $p"; continue;; esac
    case "$p" in *[!A-Za-z0-9/_.-]*) echo "  skip 위험문자: $p"; continue;; esac
    local safe; safe="$(echo "$p" | tr '/' '_')"
    # run-as 로 읽어 base64 로 빼옴(바이너리 안전)
    adb -s "$SERIAL" shell "run-as $PKG cat '$p' | base64" | tr -d '\r' | base64 -d > "$STAGE/$safe" 2>/dev/null || continue
    echo "$STAGE/$safe" >> "$STAGE/.list"
  done <<< "$paths"
  # 수확물 파싱 → temp → code기준 병합(미수확 계정·proxy/label 보존)
  python3 "$ROOT/tools/extract_tokens.py" "$STAGE" --out "$STAGE/harvested.json" \
          --headers-out "$ROOT/data/config.json" 2>&1 | sed 's/^/    /'
  python3 "$ROOT/tools/_merge_accounts.py" "$ROOT/data/accounts.json" "$STAGE/harvested.json"
}

if [ "${2:-}" = "once" ]; then
  echo "── 1회 수확 ──"
  harvest_once || true
  exit 0
fi

echo "수확 루프 시작 · serial=$SERIAL · 주기=${INTERVAL}s"
while true; do
  echo "── $(date '+%H:%M:%S') 수확 ──"
  harvest_once || true
  sleep "$INTERVAL"
done

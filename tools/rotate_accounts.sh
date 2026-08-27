#!/usr/bin/env bash
# 계정 풀을 순환하며 폰에 갈아끼움: 활성화 → (선택)검색 → 수확 → 다음.
# 밴분산 + 전계정 토큰 신선유지. 검색은 SEARCH_CMD 환경변수로 주입(비면 수확만).
#
# 사용:
#   bash tools/rotate_accounts.sh <serial> [dwell_sec]
#   SEARCH_CMD='python tools/unattended.py --no-monitor ...' bash tools/rotate_accounts.sh <serial> 600
set -u
SERIAL="${1:?adb serial}"; DWELL="${2:-600}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
POOL=()
while IFS= read -r c; do POOL+=("$c"); done < <(ls -d "$ROOT"/out/appdata_* 2>/dev/null | sed 's#.*/appdata_##')
[ "${#POOL[@]}" -eq 0 ] && { echo "세션 풀 없음 — extract_all_appdata.sh 먼저"; exit 1; }
echo "풀 ${#POOL[@]}계정: ${POOL[*]}"

while true; do
  for CODE in "${POOL[@]}"; do
    echo ""; echo "════ $(date '+%H:%M:%S') 계정 $CODE ════"
    bash "$ROOT/tools/activate_account.sh" "$CODE" "$SERIAL" || { echo "  활성화 실패, 다음"; continue; }
    # 검색(주입시): 활성계정 access 로 모니터 1창
    if [ -n "${SEARCH_CMD:-}" ]; then
      echo "── 검색: $SEARCH_CMD"; ( cd "$ROOT" && timeout "$DWELL" bash -c "$SEARCH_CMD" ) || true
    else
      sleep "$DWELL"
    fi
    # 회전토큰 수확 → accounts.json 병합
    bash "$ROOT/tools/harvest_tokens.sh" "$SERIAL" once 2>&1 | sed 's/^/  /' | tail -4
  done
done

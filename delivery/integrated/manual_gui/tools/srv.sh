#!/usr/bin/env bash
# 운영 서버(Windows) 원격 실행 헬퍼.
#
# 왜 있나: 수확·재설치처럼 5~15분 걸리는 작업을 ssh 포그라운드로 돌리면
# 클라이언트 타임아웃에 걸려 죽고, 결과를 못 본다. 그렇다고 Start-Process 로
# 던져만 두면 (1) 파이썬 stdout 이 블록버퍼라 로그가 비어 보이고
# (2) 끝났는지 실패했는지 구분할 표식이 없어 무한정 기다리게 된다.
#
# 그래서 모든 백그라운드 작업은 끝에 __DONE__ exit=N 을 찍고, wait 는 항상
# 마감시한을 갖는다. 대기가 무한정으로 늘어지는 경로를 만들지 않는다.
#
# 사용:
#   srv.sh run  '<powershell>'            짧은 작업, 포그라운드
#   srv.sh bg   <이름> '<powershell>'      길게 걸리는 작업, 즉시 반환
#   srv.sh log  <이름> [줄수]              로그 꼬리
#   srv.sh wait <이름> [초]                끝날 때까지(기본 900초 마감)
#   srv.sh push <로컬> <원격>              scp 업로드
#   srv.sh pull <원격> <로컬>              scp 다운로드
#   srv.sh clean <이름>                    남은 작업·로그 삭제
#
# 파이썬을 부를 땐 반드시 `python -X utf8 -u` — -u 가 없으면 로그가 비어 보인다.
set -uo pipefail

HOST="${KARROT_HOST:-Administrator@108.181.252.171}"
KEY="${KARROT_KEY:-$HOME/.ssh/karrot_server}"
APP='C:\karrot\delivery\integrated\manual_gui'
SPOOL='C:\Windows\Temp\srv'

# 끊긴 연결에 매달리지 않는다 — 죽은 세션은 60초 안에 스스로 끝난다.
SSH_OPTS=(-i "$KEY" -o BatchMode=yes -o ConnectTimeout=10
          -o ServerAliveInterval=15 -o ServerAliveCountMax=4)

die() { echo "srv: $*" >&2; exit 1; }

# PowerShell 한 줄 실행. 인용부호 지옥을 피하려고 본문은 base64 로 넘긴다.
psrun() {
  local b64
  b64=$(printf '%s' "$1" | base64 | tr -d '\n')
  ssh "${SSH_OPTS[@]}" "$HOST" \
    "powershell -NoProfile -ExecutionPolicy Bypass -Command \"chcp 65001 > \$null; [Console]::OutputEncoding=[Text.Encoding]::UTF8; \$s=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('$b64')); Invoke-Expression \$s\""
}

need_name() { [[ -n "${1:-}" ]] || die "이름이 필요하다"; }

case "${1:-}" in
  run)
    [[ -n "${2:-}" ]] || die "명령이 필요하다"
    psrun "Set-Location '$APP'
$2"
    ;;

  bg)
    need_name "${2:-}"; [[ -n "${3:-}" ]] || die "명령이 필요하다"
    name="$2"
    # 러너 본문을 통째로 만들어 base64 로 넘긴다. 서버에서는 파일로 쓰고 던지기만.
    runner="\$ErrorActionPreference = 'Continue'
Set-Location '$APP'
\$code = 0
try {
$3
  if (\$null -ne \$LASTEXITCODE) { \$code = \$LASTEXITCODE }
} catch {
  Write-Output ('__ERR__ ' + \$_.Exception.Message)
  \$code = 99
}
Write-Output ('__DONE__ exit=' + \$code)"
    rb64=$(printf '%s' "$runner" | base64 | tr -d '\n')
    # 작업 스케줄러로 띄운다. Start-Process 로 던지면 ssh 세션이 닫힐 때
    # 자식까지 같이 죽어(실측: 로그 0바이트, 프로세스 없음) 백그라운드가 안 된다.
    # karrotgui 와 같은 방식 — Interactive 원칙, 트리거 없이 손으로 /run.
    psrun "New-Item -ItemType Directory -Force -Path '$SPOOL' | Out-Null
\$r = '$SPOOL\\$name.ps1'
[System.IO.File]::WriteAllText(\$r, [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('$rb64')), (New-Object System.Text.UTF8Encoding \$true))
Remove-Item '$SPOOL\\$name.log','$SPOOL\\$name.err' -Force -EA SilentlyContinue
# 출력 리다이렉션은 작업이 아니라 감싸는 셸이 한다.
\$wrap = '$SPOOL\\$name.wrap.ps1'
# PowerShell 이스케이프(백틱)는 bash 안에서 명령치환이 되니 쓰지 않는다.
# 리터럴은 PS 작은따옴표로, 줄바꿈은 [Environment]::NewLine 으로 잇는다.
[System.IO.File]::WriteAllText(\$wrap,
  ('chcp 65001 > \$null' + [Environment]::NewLine +
   '[Console]::OutputEncoding=[Text.Encoding]::UTF8' + [Environment]::NewLine +
   '\$OutputEncoding=[Text.Encoding]::UTF8' + [Environment]::NewLine +
   \"& '\$r' *>&1 | Out-File -FilePath '$SPOOL\\$name.log' -Encoding utf8\"),
  (New-Object System.Text.UTF8Encoding \$true))
\$act = New-ScheduledTaskAction -Execute 'powershell' \`
  -Argument ('-NoProfile -ExecutionPolicy Bypass -File \"' + \$wrap + '\"') -WorkingDirectory '$APP'
\$prin = New-ScheduledTaskPrincipal -UserId \$env:USERNAME -LogonType Interactive -RunLevel Highest
\$set = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'srv_$name' -Action \$act -Principal \$prin -Settings \$set -Force | Out-Null
Start-ScheduledTask -TaskName 'srv_$name'
'started: $name'"
    ;;

  log)
    need_name "${2:-}"
    n="${3:-40}"
    psrun "Get-Content '$SPOOL\\$2.log' -Tail $n -Encoding UTF8 -EA SilentlyContinue
if ((Get-Item '$SPOOL\\$2.err' -EA SilentlyContinue).Length -gt 0) {
  '--- stderr ---'
  Get-Content '$SPOOL\\$2.err' -Tail $n -Encoding UTF8
}"
    ;;

  wait)
    need_name "${2:-}"
    name="$2"; budget="${3:-900}"; waited=0; step=15
    while :; do
      out=$(psrun "\$l = Get-Content '$SPOOL\\$name.log' -Tail 3 -Encoding UTF8 -EA SilentlyContinue
if (\$l -match '__DONE__') { (\$l | Select-String '__DONE__').Line } else { 'RUNNING' }" 2>/dev/null)
      case "$out" in
        *__DONE__*)
          echo "$out"
          # 표식만 보고 성공이라 하지 않는다. exit=0 이 아니면 실패로 돌려준다.
          [[ "$out" == *"exit=0"* ]] || { echo "srv: 실패 — 로그 확인" >&2; exit 1; }
          exit 0 ;;
      esac
      if (( waited >= budget )); then
        echo "srv: $budget 초 안에 안 끝났다. 마지막 로그:" >&2
        psrun "Get-Content '$SPOOL\\$name.log' -Tail 15 -Encoding UTF8 -EA SilentlyContinue" >&2
        exit 2
      fi
      sleep "$step"; waited=$(( waited + step ))
    done
    ;;

  clean)
    need_name "${2:-}"
    psrun "Unregister-ScheduledTask -TaskName 'srv_$2' -Confirm:\$false -EA SilentlyContinue
Remove-Item '$SPOOL\\$2.*' -Force -EA SilentlyContinue
'cleaned: $2'" ;;

  push)
    [[ -n "${3:-}" ]] || die "srv.sh push <로컬> <원격>"
    scp "${SSH_OPTS[@]}" "$2" "$HOST:$3" ;;

  pull)
    [[ -n "${3:-}" ]] || die "srv.sh pull <원격> <로컬>"
    scp "${SSH_OPTS[@]}" "$HOST:$2" "$3" ;;

  *)
    sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
    exit 1 ;;
esac

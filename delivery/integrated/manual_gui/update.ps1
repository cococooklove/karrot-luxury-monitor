# Karrot monitor - 운영 서버를 최신 코드로 올린다. RDP PowerShell 에서:
#   iwr https://raw.githubusercontent.com/cococooklove/karrot-luxury-monitor/master/delivery/integrated/manual_gui/update.ps1 -OutFile $env:TEMP\upd.ps1; & $env:TEMP\upd.ps1
#
# install.ps1 은 C:\karrot 을 통째로 갈아끼운다 → 앱이 돌고 있으면 잠김으로 멈춘다.
# 그리고 끝나도 앱을 다시 띄우지 않는다. 그 앞뒤를 이 스크립트가 맡는다:
#   앱 정지 → 최신 ZIP → install.ps1 → 앱 재기동.
#
# LDPlayer 함대는 건드리지 않는다. 토큰 수확이 계속 돌아도 무해하고, 함대를
# 내리면 순차 기동(동시 기동 금지)을 처음부터 다시 기다려야 한다.
#
# ZIP 을 여기서 받아 그 안의 install.ps1 을 부르는 이유: raw.githubusercontent 는
# CDN 캐시가 있어 푸시 직후 옛 install.ps1 을 내줄 수 있다. codeload 의 ZIP 은
# 요청 시 생성되므로 이 경로가 항상 최신이다.
#
# -Check: 아무것도 바꾸지 않고 "서버가 최신인가"만 답한다.
param([switch]$Check)
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
function Log($m){ Write-Host ("[update] " + $m) -ForegroundColor Cyan }
function Fail($m){ Write-Host ("[update][FAIL] " + $m) -ForegroundColor Red; exit 1 }

$appRel = "delivery\integrated\manual_gui"
$app = "C:\karrot\$appRel"

# C:\karrot 안에 서 있으면 install.ps1 의 Move-Item 이 막힌다.
Set-Location $env:SystemRoot

# 0) 지금 뭐가 깔려 있나 — 끝나고 비교해 준다.
function Read-Stamp($path) {
  try {
    if (Test-Path $path) { return (Get-Content $path -Raw | ConvertFrom-Json) }
  } catch { }
  $null
}
$before = Read-Stamp (Join-Path $app "data\deployed.json")
if ($before) { Log ("현재 배포: " + $before.short + "  (" + $before.installed + ")") }
else { Log "현재 배포: 각인 없음(이 스크립트 이전에 설치된 판)" }

function Get-RemoteSha {
  try {
    (Invoke-RestMethod "https://api.github.com/repos/cococooklove/karrot-luxury-monitor/commits/master" `
       -Headers @{ "User-Agent" = "karrot-update" }).sha
  } catch {
    Write-Host ("[update] master SHA 조회 실패: " + $_.Exception.Message) -ForegroundColor Yellow
    $null
  }
}

if ($Check) {
  $remote = Get-RemoteSha
  if (-not $remote) { Fail "master SHA 를 못 읽어 비교할 수 없습니다." }
  Log ("master:  " + $remote.Substring(0, 7))
  if ($before -and $before.sha -eq $remote) {
    Write-Host "[update] 최신입니다. 할 일 없음." -ForegroundColor Green
  } elseif ($before) {
    Write-Host ("[update] 구버전입니다: " + $before.short + " -> " + $remote.Substring(0, 7) +
                "   업데이트하려면 인자 없이 다시 실행하세요.") -ForegroundColor Yellow
  } else {
    Write-Host "[update] 각인이 없어 비교 불가 — 한 번 업데이트하면 이후로는 비교됩니다." -ForegroundColor Yellow
  }
  exit 0
}

# 1) 앱 정지. install.ps1 은 잠긴 폴더를 만나면 아무것도 지우지 않고 멈추므로
#    여기서 확실히 내려놔야 한다. 함대(LDPlayer)는 그대로 둔다.
Log "1/4 앱 정지"
# 네이티브 schtasks 대신 cmdlet — ErrorActionPreference=Stop 에서 네이티브 stderr 는
# NativeCommandError 로 튄다. 작업이 없거나 안 돌고 있어도 조용히 넘어가야 한다.
Stop-ScheduledTask -TaskName karrotgui -ErrorAction SilentlyContinue

function Get-KarrotHolders {
  $hold = @()
  $hold += Get-Process -ErrorAction SilentlyContinue |
           Where-Object { $_.Path -like "C:\karrot\*" } |
           ForEach-Object { $_ }
  # cmdline 에 karrot 이 안 들어가는 판이 있다. 작업 폴더가 C:\karrot 이라 pythonw 는
  # "pythonw.exe main.py" 로만 뜨는데(작업 스케줄러가 -WorkingDirectory 로 띄운다),
  # 그러면 여기 안 걸리고 install 이 잠긴 폴더를 만나 멈춘다. main.py 도 같이 본다.
  $hold += Get-CimInstance Win32_Process -ErrorAction SilentlyContinue `
             -Filter "Name='python.exe' OR Name='pythonw.exe'" |
           Where-Object { $_.CommandLine -and
                          ($_.CommandLine -like "*karrot*" -or $_.CommandLine -like "*main.py*") } |
           ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
  @($hold | Where-Object { $_ } | Sort-Object Id -Unique)
}

# --watchdog 이 자식을 되살리므로 부모(watchdog)부터 죽여야 한다. 한 번에 다
# 잡고, 되살아난 놈이 있으면 다시 잡는다.
for ($i = 0; $i -lt 6; $i++) {
  $holders = Get-KarrotHolders
  if (-not $holders.Count) { break }
  Log ("  종료: " + (($holders | ForEach-Object { "{0}(pid {1})" -f $_.ProcessName, $_.Id }) -join ", "))
  $holders | Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 2
}
$holders = Get-KarrotHolders
if ($holders.Count) {
  $holders | ForEach-Object { Write-Host ("  - {0} (pid {1})" -f $_.ProcessName, $_.Id) -ForegroundColor Yellow }
  Fail "앱이 계속 살아납니다. Stop-ScheduledTask -TaskName karrotgui 후 위 프로세스를 직접 끄고 다시 실행하세요."
}
Log "  정지 완료"

# 2) 최신 ZIP
Log "2/4 최신 ZIP 내려받기"
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$zip = "$env:TEMP\karrot_upd_$ts.zip"
$ext = "$env:TEMP\karrot_upd_$ts"
Invoke-WebRequest "https://github.com/cococooklove/karrot-luxury-monitor/archive/refs/heads/master.zip" -OutFile $zip
Expand-Archive $zip -DestinationPath $ext -Force
$ins = Join-Path $ext "karrot-luxury-monitor-master\$appRel\install.ps1"
if (-not (Test-Path $ins)) { Fail ("ZIP 안에 install.ps1 이 없습니다: " + $ins) }

# 3) 재설치 — 설정 백업/복원·의존성·스모크·자동실행 등록은 전부 install.ps1 몫이다.
Log "3/4 install.ps1 실행"
$global:LASTEXITCODE = 0
try {
  & $ins -ZipPath $zip
} catch {
  Fail ("install.ps1 오류: " + $_.Exception.Message + "`n앱은 정지 상태입니다 — 고친 뒤 다시 실행하세요.")
}
if ($LASTEXITCODE -ne 0) {
  Fail ("install.ps1 실패 (exit " + $LASTEXITCODE + "). 앱은 정지 상태입니다 — 고친 뒤 다시 실행하세요.")
}

# 4) 앱 재기동. install.ps1 이 karrotgui 작업을 다시 등록해 두었고, 이 작업에는
#    트리거가 없다(부팅 때 함대와 동시에 뜨면 게스트가 hang). 그래서 손으로 부른다.
Log "4/4 앱 재기동"
# install.ps1 은 작업 등록에 실패해도 경고만 하고 넘어간다. 여기서 던져 버리면
# 설치는 끝났는데 스크립트가 예외로 죽는 꼴이라, 아래 확인 단계에 맡긴다.
Start-ScheduledTask -TaskName karrotgui -ErrorAction SilentlyContinue
Start-Sleep -Seconds 5
$live = Get-KarrotHolders
if ($live.Count) {
  Log ("  실행 중: " + (($live | ForEach-Object { "{0}(pid {1})" -f $_.ProcessName, $_.Id }) -join ", "))
} else {
  Write-Host "[update] 주의: 앱이 아직 안 보입니다. 작업 스케줄러에서 karrotgui 를 확인하세요." -ForegroundColor Yellow
}

$after = Read-Stamp (Join-Path $app "data\deployed.json")
$from = if ($before) { $before.short } else { "unknown" }
$to = if ($after) { $after.short } else { "unknown" }
Write-Host ("[update] DONE. " + $from + " -> " + $to) -ForegroundColor Green
Remove-Item $ext -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $zip -Force -ErrorAction SilentlyContinue

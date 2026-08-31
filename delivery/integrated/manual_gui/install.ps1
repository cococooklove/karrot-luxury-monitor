# Karrot monitor - one-shot server install (Windows Server). No git/winget needed.
# Run in RDP PowerShell:
#   iwr <raw>/install.ps1 -OutFile $env:TEMP\ins.ps1; & $env:TEMP\ins.ps1
#
# -ZipPath: 이미 받아 둔 master.zip 을 재사용한다. update.ps1 이 zip 을 먼저 받아
#   그 안의 install.ps1 을 부르므로(raw CDN 캐시 회피), 같은 zip 을 두 번 받지 않는다.
param([string]$ZipPath = "")
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
function Log($m){ Write-Host ("[install] " + $m) -ForegroundColor Cyan }
function Fail($m){ Write-Host ("[install][FAIL] " + $m) -ForegroundColor Red; exit 1 }

# 1) Python
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
  Log "1/6 Installing Python 3.12 (direct download)"
  $ver = "3.12.7"
  $url = "https://www.python.org/ftp/python/$ver/python-$ver-amd64.exe"
  $exe = "$env:TEMP\python-$ver.exe"
  Invoke-WebRequest $url -OutFile $exe
  Start-Process -FilePath $exe -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait
  $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
  if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Fail "python not found after install (PATH). Re-login RDP and retry." }
} else {
  Log ("1/6 Python present: " + ((python --version) 2>&1))
}

# 2) Repo ZIP (no git)
Log "2/6 Downloading repo (ZIP)"
Set-Location $env:SystemRoot   # cwd out of C:\karrot so it can be replaced on re-run
$zip = "$env:TEMP\karrot.zip"
$appRel = "delivery\integrated\manual_gui"

# 재설치는 C:\karrot 을 통째로 지운다. 거기 있는 자격증명·상태 파일은
# gitignore 라 ZIP 에 없다 — 특히 accounts.json 은 폰 앱스택으로만 복구되고,
# watch.db 를 잃으면 이미 알린 매물을 전부 다시 알린다. 먼저 빼돌린다.
#
# gitignore 된 것만 넣는다. OUT.json 은 저장소에 추적되므로 여기 넣으면
# ZIP 이 가져온 새 지역 데이터를 옛 파일로 덮어쓴다.
$keep = @("accounts.json", "notify.json", "credentials.json", "settings.txt",
          "proxies.txt", "auto_seen.db",
          "data\config.json", "data\watch.db", "data\alert_settings.json",
          "data\keyword_routes.json", "data\sweep_queue.json",
          "data\watch_budget.json",
          # 잃어도 다시 쌓이지만, account_state 를 잃으면 격리해 둔 정지 계정을
          # 처음부터 다시 두드리고 account_regions 를 잃으면 커버 집계가 0 이 된다.
          "data\account_state.json", "data\account_regions.json")
# 백업 폴더는 실행마다 새로 만든다. 예전에는 고정 경로를 먼저 지웠는데,
# 앞선 실행이 백업을 마치고 삭제 도중 실패해 C:\karrot 이 반쯤 파인 상태였다면
# 재실행이 멀쩡한 백업을 지우고 파인 트리에서 다시 백업해 자격증명을 영영
# 잃는다. 지난 백업은 절대 건드리지 않는다.
$stash = "$env:TEMP\karrot_keep_" + (Get-Date -Format "yyyyMMdd_HHmmss")
New-Item -ItemType Directory -Force -Path $stash | Out-Null
$prior = @(Get-ChildItem "$env:TEMP" -Directory -Filter "karrot_keep*" -EA 0 |
           Where-Object { $_.FullName -ne $stash })
if ($prior.Count) {
  Log ("  지난 백업 " + $prior.Count + "개가 남아 있습니다(지우지 않음): " +
       ($prior[-1].FullName))
}
$saved = @()
if (Test-Path C:\karrot) {
  foreach ($rel in $keep) {
    $src = Join-Path "C:\karrot\$appRel" $rel
    if (Test-Path $src) {
      $dst = Join-Path $stash $rel
      New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
      Copy-Item $src $dst -Force
      $saved += $rel
    }
  }
  if ($saved.Count) { Log ("  기존 설정 " + $saved.Count + "개 백업: " + ($saved -join ", ")) }
}

if ($ZipPath -and (Test-Path $ZipPath)) {
  $zip = $ZipPath
  Log ("  ZIP 재사용: " + $zip)
} else {
  Invoke-WebRequest "https://github.com/cococooklove/karrot-luxury-monitor/archive/refs/heads/master.zip" -OutFile $zip
}

# 지우기 **전에** 점유를 확인한다. Remove-Item -Recurse -Force 는 지울 수 있는
# 것만 지우고 잠긴 것은 조용히 건너뛰므로, 먼저 지우고 나중에 확인하면 실패할
# 때마다 C:\karrot 이 반쯤 파인 채로 남는다.
function Get-KarrotHolders {
  $hold = @()
  # 실행 파일이 C:\karrot 안에 있는 프로세스
  $hold += Get-Process -ErrorAction SilentlyContinue |
           Where-Object { $_.Path -like "C:\karrot\*" } |
           ForEach-Object { "{0} (pid {1})" -f $_.ProcessName, $_.Id }
  # C:\karrot 안의 스크립트를 실행 중인 python/pythonw
  # cmdline 에 karrot 이 안 들어가는 판이 있다. 작업 폴더가 C:\karrot 이라 pythonw 는
  # "pythonw.exe main.py" 로만 뜨는데(작업 스케줄러가 -WorkingDirectory 로 띄운다),
  # 그러면 여기 안 걸리고 install 이 잠긴 폴더를 만나 멈춘다. main.py 도 같이 본다.
  $hold += Get-CimInstance Win32_Process -ErrorAction SilentlyContinue `
             -Filter "Name='python.exe' OR Name='pythonw.exe'" |
           Where-Object { $_.CommandLine -and
                          ($_.CommandLine -like "*karrot*" -or $_.CommandLine -like "*main.py*") } |
           ForEach-Object { "python (pid {0}): {1}" -f $_.ProcessId, $_.CommandLine }
  $hold
}

if (Test-Path C:\karrot) {
  $holders = @(Get-KarrotHolders)
  if ($holders.Count) {
    Write-Host "[install][FAIL] C:\karrot 을 다음이 사용 중입니다:" -ForegroundColor Red
    $holders | ForEach-Object { Write-Host ("  - " + $_) -ForegroundColor Yellow }
    Write-Host ("[install] 백업은 그대로 있습니다: " + $stash) -ForegroundColor Green
    Write-Host "[install] 위 프로세스를 끄고 다시 실행하세요. 모니터라면 창을 닫거나:" -ForegroundColor Yellow
    Write-Host '[install]   Get-Process python,pythonw -EA 0 | Stop-Process -Force' -ForegroundColor Yellow
    exit 1
  }
  # 프로세스는 안 잡혔는데 탐색기·백신·다른 셸이 잡고 있을 수 있다. 통째로
  # 지우는 대신 옆으로 밀어 본다 — 실패하면 아무것도 안 지운 상태로 멈춘다.
  $old = "C:\karrot_old_" + (Get-Date -Format "yyyyMMdd_HHmmss")
  try { Move-Item C:\karrot $old -ErrorAction Stop }
  catch {
    Write-Host "[install][FAIL] C:\karrot 을 옮길 수 없습니다(잠김). 아무것도 지우지 않았습니다." -ForegroundColor Red
    Write-Host ("[install] 사유: " + $_.Exception.Message) -ForegroundColor Yellow
    Write-Host "[install] 탐색기 창·다른 PowerShell·백신 실시간 검사를 확인하세요." -ForegroundColor Yellow
    Write-Host ("[install] 백업은 그대로 있습니다: " + $stash) -ForegroundColor Green
    exit 1
  }
  Remove-Item $old -Recurse -Force -ErrorAction SilentlyContinue
  if (Test-Path $old) { Log ("  옛 폴더 일부가 남았습니다(무해): " + $old) }
}
if (Test-Path C:\karrot_tmp) { Remove-Item C:\karrot_tmp -Recurse -Force }
Expand-Archive $zip -DestinationPath C:\karrot_tmp -Force
Move-Item C:\karrot_tmp\karrot-luxury-monitor-master C:\karrot
Remove-Item C:\karrot_tmp -Recurse -Force -ErrorAction SilentlyContinue

$app = "C:\karrot\$appRel"

# 빼돌린 것 되돌리기. 이번 백업에 없으면 지난 백업들에서 최신 것을 찾는다 —
# 앞선 실행이 백업 후 삭제에서 실패해 트리가 파였다면, 이번 백업에는 그 파일이
# 아예 없다. 그 경우 지난 백업이 유일한 사본이다.
$stashes = @(Get-ChildItem "$env:TEMP" -Directory -Filter "karrot_keep*" -EA 0 |
             Sort-Object Name -Descending)
$restored = @(); $missing = @()
foreach ($rel in $keep) {
  $src = $null
  foreach ($s in $stashes) {
    $cand = Join-Path $s.FullName $rel
    if (Test-Path $cand) { $src = $cand; break }
  }
  if (-not $src) { $missing += $rel; continue }
  $dst = Join-Path $app $rel
  New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
  Copy-Item $src $dst -Force
  if (-not (Test-Path $dst)) { Fail ("복원 실패: " + $rel + "  (백업본: " + $src + ")") }
  $restored += $rel
  if ($src -notlike "$stash*") { Log ("  지난 백업에서 복구: " + $rel) }
}
if ($restored.Count) {
  Log ("  기존 설정 " + $restored.Count + "개 복원: " + ($restored -join ", "))
  Log ("  백업 사본은 남겨둔다: " + $stash)
}
# accounts.json / data\config.json 없이는 폴링이 0건이다. 조용히 넘어가면
# '설치는 됐는데 아무것도 안 잡힘'의 원인을 찾는 데 한참 걸린다.
foreach ($critical in @("accounts.json", "data\config.json")) {
  if ($missing -contains $critical) {
    Write-Host ("[install] 주의: " + $critical + " 이 없습니다 — 백업에도 없었습니다.") -ForegroundColor Yellow
  }
}
Set-Location $app

# 3) Dependencies
Log "3/6 Installing Python deps (pip)"
python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Fail "pip upgrade failed" }
python -m pip install -e .
if ($LASTEXITCODE -ne 0) { Fail "dependency install failed" }
New-Item -ItemType Directory -Force -Path "$app\data" | Out-Null

# 4) Headless smoke
Log "4/6 Headless smoke (--once)"
python main.py --headless --once --no-harvest
if ($LASTEXITCODE -ne 0) { Fail ("headless smoke failed (exit " + $LASTEXITCODE + ")") }

# 5) Desktop shortcuts (best-effort: RDP session with no desktop still installs fine)
Log "5/6 Desktop shortcuts"
try {
  & "$app\make_shortcuts.ps1" -AppDir $app
} catch {
  Write-Host ("[install] shortcut skipped: " + $_.Exception.Message) -ForegroundColor Yellow
}

# 6) 부팅 자동실행 등록
# 서버는 재부팅 뒤 사람 없이 스스로 올라와야 한다. 그런데 자동실행 진입점은
# C:\karrot\ldboot.ps1 로 고정돼 있는 반면, 이 스크립트는 C:\karrot 을 통째로
# 리포지토리로 갈아끼운다 → 재설치 한 번에 그 파일이 사라지고, 부팅해도 함대도
# 앱도 안 뜬다(운영 서버에서 실제로 이렇게 깨져 있었다).
# 그래서 고정 경로에는 리포 사본을 부르는 shim 만 두고 내용은 리포에서 관리한다.
Log "6/6 Boot autostart (shim + Run + karrotgui task)"

$shimPath = "C:\karrot\ldboot.ps1"
$shim = @"
# 자동실행이 가리키는 고정 경로. 실제 내용은 리포지토리 사본이 갖는다.
# install.ps1 이 매 설치마다 다시 만든다 — 직접 고치지 말 것.
& "`$PSScriptRoot\$appRel\ldboot.ps1"
"@
# PowerShell 5.1 은 BOM 없는 UTF-8 을 cp949 로 읽어 한글 주석을 깨뜨린다 → BOM 필수.
[System.IO.File]::WriteAllText($shimPath, $shim, (New-Object System.Text.UTF8Encoding $true))
Log ("  shim: " + $shimPath)

# 로그온 시 함대 기동. ldboot.ps1 이 루프백 RDP 로 세션을 승격시켜야 하므로
# SYSTEM 이 아니라 로그온 사용자로 돈다.
try {
  Set-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" `
    -Name "LDPlayerBoot" `
    -Value ('powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $shimPath + '"') `
    -Force
  Log "  HKCU Run: LDPlayerBoot"
} catch {
  Write-Host ("[install] Run 등록 실패(수동 등록 필요): " + $_.Exception.Message) -ForegroundColor Yellow
}

# ldboot.ps1 은 인스턴스를 다 띄운 뒤 schtasks /run /tn karrotgui 로 앱을 부른다.
# 이 작업이 없으면 함대만 뜨고 모니터는 영영 안 뜬다. 트리거는 두지 않는다 —
# 부팅 경로에서 앱과 인스턴스가 동시에 뜨면 게스트 커널이 hang 하기 때문이다.
try {
  $pyw = Join-Path (Split-Path (Get-Command python -ErrorAction Stop).Source) "pythonw.exe"
  if (-not (Test-Path $pyw)) { $pyw = "pythonw.exe" }
  # --watchdog: 앱을 자식으로 띄우고 비정상 종료면 되살린다(정상 종료면 같이 끝난다).
  # 이게 빠지면 앱이 크래시했을 때 아무도 다시 띄우지 않는다.
  $act = New-ScheduledTaskAction -Execute $pyw -Argument "main.py --watchdog" -WorkingDirectory $app
  $prin = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
  # IgnoreNew: 이미 돌고 있으면 두 번째 인스턴스를 만들지 않는다. 손으로 schtasks /run 을
  # 다시 눌러도 수확을 다투는 프로세스가 둘로 늘지 않는다.
  $set = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
  Register-ScheduledTask -TaskName "karrotgui" -Action $act -Principal $prin -Settings $set -Force | Out-Null
  Log ("  task karrotgui: pythonw main.py --watchdog  (작업 폴더 " + $app + ")")
} catch {
  Write-Host ("[install] karrotgui 작업 등록 실패(수동 등록 필요): " + $_.Exception.Message) -ForegroundColor Yellow
}

# 손으로 만들어 둔 옛 작업이 남아 있으면 순차 기동을 깨거나 앱을 중복 실행한다.
# 지우는 건 사람이 판단할 일이라 여기서는 알리기만 한다.
$stale = @("karrotgui2","karrotgui3","karrotbat","ldboot","ldboot1","ldq1","rdpsess",
           "ldlaunch0","ldlaunch1","ldlaunch2","ldlaunch3","ldlaunch4","ldlaunch5")
$found = @($stale | Where-Object { Get-ScheduledTask -TaskName $_ -ErrorAction SilentlyContinue })
if ($found.Count) {
  Write-Host ("[install] 주의: 겹치는 옛 작업이 남아 있습니다 - " + ($found -join ", ")) -ForegroundColor Yellow
  Write-Host "[install]   ldlaunch* 가 동시에 돌면 LDPlayer 가 hang 하고, karrotgui2/3 는 앱을 중복 실행합니다." -ForegroundColor Yellow
  Write-Host "[install]   확인 후 지우세요:  schtasks /delete /tn <이름> /f" -ForegroundColor Yellow
}

# 배포 각인 — 서버에는 git 이 없다(ZIP 설치). 이 파일이 없으면 "서버가 최신인가"에
# 답할 방법이 로그인해서 소스를 눈으로 읽는 것뿐이다. $keep 에 넣지 않는다 —
# 매 설치마다 새로 써야 하는 값이다.
try {
  $sha = "unknown"
  try {
    $c = Invoke-RestMethod "https://api.github.com/repos/cococooklove/karrot-luxury-monitor/commits/master" `
           -Headers @{ "User-Agent" = "karrot-install" }
    $sha = $c.sha
  } catch {
    Write-Host ("[install] 커밋 SHA 조회 실패(각인은 남긴다): " + $_.Exception.Message) -ForegroundColor Yellow
  }
  $short = if ($sha -eq "unknown") { "unknown" } else { $sha.Substring(0, 7) }
  $stamp = [ordered]@{
    sha        = $sha
    short      = $short
    installed  = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    zip_reused = [bool]$ZipPath
  }
  # BOM 없는 UTF-8 — 파이썬이 읽어도 걸리지 않게. (PS 5.1 의 -Encoding UTF8 은 BOM 을 붙인다)
  [System.IO.File]::WriteAllText((Join-Path $app "data\deployed.json"),
                                 ($stamp | ConvertTo-Json),
                                 (New-Object System.Text.UTF8Encoding $false))
  Log ("  배포 각인: " + $short + "  (data\deployed.json)")
} catch {
  Write-Host ("[install] 배포 각인 실패(무해): " + $_.Exception.Message) -ForegroundColor Yellow
}

Write-Host ("[install] DONE. path: " + $app) -ForegroundColor Green
Write-Host "[install] next: place notify.json/accounts.json/config.json + LDPlayer, then: python main.py --headless" -ForegroundColor Green
Write-Host "[install] desktop icons: '당근 명품 모니터' (GUI) / '당근 모니터 (서버·무인)' (headless)" -ForegroundColor Green

# Karrot monitor - one-shot server install (Windows Server). No git/winget needed.
# Run in RDP PowerShell:
#   iwr <raw>/install.ps1 -OutFile $env:TEMP\ins.ps1; & $env:TEMP\ins.ps1
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
function Log($m){ Write-Host ("[install] " + $m) -ForegroundColor Cyan }
function Fail($m){ Write-Host ("[install][FAIL] " + $m) -ForegroundColor Red; exit 1 }

# 1) Python
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
  Log "1/5 Installing Python 3.12 (direct download)"
  $ver = "3.12.7"
  $url = "https://www.python.org/ftp/python/$ver/python-$ver-amd64.exe"
  $exe = "$env:TEMP\python-$ver.exe"
  Invoke-WebRequest $url -OutFile $exe
  Start-Process -FilePath $exe -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait
  $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
  if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Fail "python not found after install (PATH). Re-login RDP and retry." }
} else {
  Log ("1/5 Python present: " + ((python --version) 2>&1))
}

# 2) Repo ZIP (no git)
Log "2/5 Downloading repo (ZIP)"
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
          "data\watch_budget.json")
$stash = "$env:TEMP\karrot_keep"
if (Test-Path $stash) { Remove-Item $stash -Recurse -Force }
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

Invoke-WebRequest "https://github.com/cococooklove/karrot-luxury-monitor/archive/refs/heads/master.zip" -OutFile $zip
if (Test-Path C:\karrot) { Remove-Item C:\karrot -Recurse -Force -ErrorAction SilentlyContinue }
if (Test-Path C:\karrot) { Fail "C:\karrot in use (close other shells/programs using it) and retry" }
if (Test-Path C:\karrot_tmp) { Remove-Item C:\karrot_tmp -Recurse -Force }
Expand-Archive $zip -DestinationPath C:\karrot_tmp -Force
Move-Item C:\karrot_tmp\karrot-luxury-monitor-master C:\karrot
Remove-Item C:\karrot_tmp -Recurse -Force -ErrorAction SilentlyContinue

$app = "C:\karrot\$appRel"

# 빼돌린 것 되돌리기. 실패하면 여기서 멈춘다 — 자격증명 없이 돌려봐야
# 폴링 0건이고, 조용히 넘어가면 원인을 찾는 데 한참 걸린다.
if ($saved.Count) {
  foreach ($rel in $saved) {
    $src = Join-Path $stash $rel
    $dst = Join-Path $app $rel
    New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
    Copy-Item $src $dst -Force
    if (-not (Test-Path $dst)) { Fail ("복원 실패: " + $rel + "  (백업본: " + $src + ")") }
  }
  Log ("  기존 설정 " + $saved.Count + "개 복원 완료")
  Log ("  백업 사본은 남겨둔다: " + $stash)
}
Set-Location $app

# 3) Dependencies
Log "3/5 Installing Python deps (pip)"
python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Fail "pip upgrade failed" }
python -m pip install -e .
if ($LASTEXITCODE -ne 0) { Fail "dependency install failed" }
New-Item -ItemType Directory -Force -Path "$app\data" | Out-Null

# 4) Headless smoke
Log "4/5 Headless smoke (--once)"
python main.py --headless --once --no-harvest
if ($LASTEXITCODE -ne 0) { Fail ("headless smoke failed (exit " + $LASTEXITCODE + ")") }

# 5) Desktop shortcuts (best-effort: RDP session with no desktop still installs fine)
Log "5/5 Desktop shortcuts"
try {
  & "$app\make_shortcuts.ps1" -AppDir $app
} catch {
  Write-Host ("[install] shortcut skipped: " + $_.Exception.Message) -ForegroundColor Yellow
}

Write-Host ("[install] DONE. path: " + $app) -ForegroundColor Green
Write-Host "[install] next: place notify.json/accounts.json/config.json + LDPlayer, then: python main.py --headless" -ForegroundColor Green
Write-Host "[install] desktop icons: '당근 명품 모니터' (GUI) / '당근 모니터 (서버·무인)' (headless)" -ForegroundColor Green

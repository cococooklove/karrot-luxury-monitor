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
  Log "1/4 Installing Python 3.12 (direct download)"
  $ver = "3.12.7"
  $url = "https://www.python.org/ftp/python/$ver/python-$ver-amd64.exe"
  $exe = "$env:TEMP\python-$ver.exe"
  Invoke-WebRequest $url -OutFile $exe
  Start-Process -FilePath $exe -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait
  $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
  if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Fail "python not found after install (PATH). Re-login RDP and retry." }
} else {
  Log ("1/4 Python present: " + ((python --version) 2>&1))
}

# 2) Repo ZIP (no git)
Log "2/4 Downloading repo (ZIP)"
Set-Location $env:SystemRoot   # cwd out of C:\karrot so it can be replaced on re-run
$zip = "$env:TEMP\karrot.zip"
Invoke-WebRequest "https://github.com/cococooklove/karrot-luxury-monitor/archive/refs/heads/master.zip" -OutFile $zip
if (Test-Path C:\karrot) { Remove-Item C:\karrot -Recurse -Force -ErrorAction SilentlyContinue }
if (Test-Path C:\karrot) { Fail "C:\karrot in use (close other shells/programs using it) and retry" }
if (Test-Path C:\karrot_tmp) { Remove-Item C:\karrot_tmp -Recurse -Force }
Expand-Archive $zip -DestinationPath C:\karrot_tmp -Force
Move-Item C:\karrot_tmp\karrot-luxury-monitor-master C:\karrot
Remove-Item C:\karrot_tmp -Recurse -Force -ErrorAction SilentlyContinue

$app = "C:\karrot\delivery\integrated\manual_gui"
Set-Location $app

# 3) Dependencies
Log "3/4 Installing Python deps (pip)"
python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Fail "pip upgrade failed" }
python -m pip install -e .
if ($LASTEXITCODE -ne 0) { Fail "dependency install failed" }
New-Item -ItemType Directory -Force -Path "$app\data" | Out-Null

# 4) Headless smoke
Log "4/4 Headless smoke (--once)"
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

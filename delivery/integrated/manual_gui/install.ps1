# 서버 원샷 설치 (Windows Server) — git/winget 불필요. Python 직접설치 + 레포 ZIP.
# 실행(RDP PowerShell): iwr <raw url>/install.ps1 -OutFile $env:TEMP\ins.ps1; & $env:TEMP\ins.ps1
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
function Log($m){ Write-Host ("[install] " + $m) -ForegroundColor Cyan }
function Fail($m){ Write-Host ("[install][실패] " + $m) -ForegroundColor Red; exit 1 }

# 1) Python
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
  Log "1/4 Python 3.12 설치(직접 다운로드)"
  $ver = "3.12.7"
  $url = "https://www.python.org/ftp/python/$ver/python-$ver-amd64.exe"
  $exe = "$env:TEMP\python-$ver.exe"
  Invoke-WebRequest $url -OutFile $exe
  Start-Process -FilePath $exe -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait
  $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
  if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Fail "Python 설치 후에도 python 없음(PATH). RDP 재로그인 후 재시도" }
} else { Log "1/4 Python 이미 있음: $((python --version) 2>&1)" }

# 2) 레포 ZIP (git 불필요)
Log "2/4 레포 다운로드(ZIP)"
$zip = "$env:TEMP\karrot.zip"
Invoke-WebRequest "https://github.com/cococooklove/karrot-luxury-monitor/archive/refs/heads/master.zip" -OutFile $zip
if (Test-Path C:\karrot) { Remove-Item C:\karrot -Recurse -Force }
Expand-Archive $zip -DestinationPath C:\karrot_tmp -Force
Move-Item C:\karrot_tmp\karrot-luxury-monitor-master C:\karrot
Remove-Item C:\karrot_tmp -Recurse -Force -ErrorAction SilentlyContinue

$app = "C:\karrot\delivery\integrated\manual_gui"
Set-Location $app

# 3) 의존성
Log "3/4 의존성 설치(pip)"
python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Fail "pip 업그레이드 실패" }
python -m pip install -e .
if ($LASTEXITCODE -ne 0) { Fail "의존성 설치 실패" }
New-Item -ItemType Directory -Force -Path "$app\data" | Out-Null

# 4) 헤드리스 스모크
Log "4/4 헤드리스 스모크(--once)"
python main.py --headless --once --no-harvest
if ($LASTEXITCODE -ne 0) { Fail "헤드리스 스모크 실패(exit $LASTEXITCODE)" }

Write-Host "[install] 완료 ✅  경로: $app" -ForegroundColor Green
Write-Host "[install] 다음: notify.json/accounts.json/config.json 배치 + LDPlayer 세팅 → python main.py --headless" -ForegroundColor Green

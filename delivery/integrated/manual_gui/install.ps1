# 서버 원샷 설치 — SSH 접속 후 이 스크립트 1개만 실행하면 런타임 준비 완료.
# 실행: powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Continue"
function Log($m){ Write-Host ("[install] " + $m) }

Log "1/5 Python + Git 설치(winget)"
winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements 2>$null
winget install -e --id Git.Git --silent --accept-package-agreements --accept-source-agreements 2>$null

# winget 직후 PATH 갱신
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

Log "2/5 레포 클론"
if (Test-Path C:\karrot) { git -C C:\karrot pull } else { git clone https://github.com/cococooklove/karrot-luxury-monitor C:\karrot }

$app = "C:\karrot\delivery\integrated\manual_gui"
Set-Location $app

Log "3/5 파이썬 의존성 설치"
python -m pip install --upgrade pip 2>$null
python -m pip install -e . 2>$null

Log "4/5 데이터 폴더 준비"
New-Item -ItemType Directory -Force -Path "$app\data" | Out-Null

Log "5/5 헤드리스 스모크(--once, 토큰없어도 무크래시 확인)"
python main.py --headless --once --no-harvest

Log "완료. 다음: notify.json/accounts.json/config.json 배치 + LDPlayer 세팅 후 'python main.py --headless' 상시 실행."
Log "자동시작+크래시복구: SERVER_SETUP.md 5번(작업 스케줄러) 참고."

# 서버 원샷 설치 — SSH 접속 후 이 스크립트 1개만 실행하면 런타임 준비 완료.
# 실행: powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"      # 오류 즉시 중단(실패를 '완료'로 위장 금지)
function Log($m){ Write-Host ("[install] " + $m) }
function Fail($m){ Write-Host ("[install][실패] " + $m) -ForegroundColor Red; exit 1 }
function Need($name){ if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { Fail "$name 없음 — 설치/PATH 확인" } }

Log "1/5 Python + Git 설치(winget)"
winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
winget install -e --id Git.Git --silent --accept-package-agreements --accept-source-agreements

# winget 직후 PATH 갱신(안 하면 python/git 못 찾음)
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
Need python
Need git

Log "2/5 레포 클론"
if (Test-Path C:\karrot) { git -C C:\karrot pull } else { git clone https://github.com/cococooklove/karrot-luxury-monitor C:\karrot }
if ($LASTEXITCODE -ne 0) { Fail "git 클론/풀 실패" }

$app = "C:\karrot\delivery\integrated\manual_gui"
Set-Location $app

Log "3/5 파이썬 의존성 설치"
python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Fail "pip 업그레이드 실패" }
python -m pip install -e .
if ($LASTEXITCODE -ne 0) { Fail "의존성 설치 실패" }

Log "4/5 데이터 폴더 준비"
New-Item -ItemType Directory -Force -Path "$app\data" | Out-Null

Log "5/5 헤드리스 스모크(--once, 토큰없어도 무크래시 확인)"
python main.py --headless --once --no-harvest
if ($LASTEXITCODE -ne 0) { Fail "헤드리스 스모크 실패(exit $LASTEXITCODE) — 의존성/코드 확인" }

Log "완료. 다음: notify.json/accounts.json/config.json 배치 + LDPlayer 세팅 후 'python main.py --headless' 상시 실행."
Log "키워드 등록(최초 1회): python main.py --headless --register --once"
Log "자동시작+크래시복구: SERVER_SETUP.md 5번(작업 스케줄러) 참고."

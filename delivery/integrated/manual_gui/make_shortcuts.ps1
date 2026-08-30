# 바탕화면 실행 아이콘 생성 (Windows). 관리자 권한 불필요.
#
#   powershell -ExecutionPolicy Bypass -File make_shortcuts.ps1
#
# 만드는 것:
#   "당근 명품 모니터"        → 창 있는 GUI (pythonw, 콘솔 안 뜸)
#   "당근 모니터 (서버·무인)" → 헤드리스, 콘솔에 로그가 계속 찍힘
#
# 두 바로가기 모두 작업 디렉토리를 이 폴더로 고정한다. main.py 가 OUT.json 을
# cwd 상대경로로 열기 때문에, 작업 디렉토리가 다르면 지역 트리 로딩이 실패한다.
param(
    [string]$AppDir = $PSScriptRoot,
    [switch]$NoHeadless,   # GUI 아이콘만 만든다
    [switch]$NoGui         # 헤드리스 아이콘만 만든다 (서버용)
)
$ErrorActionPreference = "Stop"
function Log($m) { Write-Host ("[shortcut] " + $m) -ForegroundColor Cyan }
function Fail($m) { Write-Host ("[shortcut][FAIL] " + $m) -ForegroundColor Red; exit 1 }

if (-not (Test-Path (Join-Path $AppDir "main.py"))) {
    Fail ("main.py 가 없습니다: " + $AppDir + "  (-AppDir 로 경로를 지정하세요)")
}
$AppDir = (Resolve-Path $AppDir).Path

# python.exe / pythonw.exe 를 PATH 에서 찾는다. 바로가기에는 절대경로를 박는다 —
# PATH 에 의존하면 다른 계정으로 로그인했을 때 조용히 깨진다.
$py = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $py) { Fail "python.exe 를 PATH 에서 못 찾았습니다. install.ps1 을 먼저 돌리세요." }
$pyw = Join-Path (Split-Path $py) "pythonw.exe"
if (-not (Test-Path $pyw)) { $pyw = $py }   # pythonw 없으면 콘솔 뜨는 걸 감수

$icon = Join-Path $AppDir "assets\icon.ico"
if (-not (Test-Path $icon)) { $icon = $py }

$desktop = [Environment]::GetFolderPath("Desktop")
$ws = New-Object -ComObject WScript.Shell

function New-Shortcut($name, $exe, $args, $desc) {
    $path = Join-Path $desktop ($name + ".lnk")
    $sc = $ws.CreateShortcut($path)
    $sc.TargetPath = $exe
    $sc.Arguments = $args
    $sc.WorkingDirectory = $AppDir     # OUT.json 이 cwd 상대경로다 — 반드시 필요
    $sc.IconLocation = $icon
    $sc.Description = $desc
    $sc.Save()
    Log ("만듦: " + $path)
}

if (-not $NoGui) {
    New-Shortcut "당근 명품 모니터" $pyw "main.py" `
        "매물 감시 GUI — 키워드 등록, 매물 표, 가격 추적"
}
if (-not $NoHeadless) {
    New-Shortcut "당근 모니터 (서버·무인)" $py "main.py --headless" `
        "무인 감시 — 창 없이 폴링·가격추적·검색스윕, 콘솔에 로그"
}

Log "완료. 바탕화면에서 더블클릭하세요."
Log ("작업 폴더: " + $AppDir)
if (-not (Test-Path (Join-Path $AppDir "accounts.json"))) {
    Write-Host "[shortcut] 주의: accounts.json 이 없습니다 — 계정 없이는 폴링이 0건입니다." -ForegroundColor Yellow
}
if (-not (Test-Path (Join-Path $AppDir "data\config.json"))) {
    Write-Host "[shortcut] 주의: data\config.json 이 없습니다 — 앱 API 헤더가 없으면 매칭 조회가 실패합니다." -ForegroundColor Yellow
}

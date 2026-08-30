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
if (-not $desktop -or -not (Test-Path $desktop)) {
    Fail ("바탕화면 폴더를 찾을 수 없습니다: '" + $desktop + "'  (데스크톱 없는 세션?)")
}
Log ("바탕화면: " + $desktop)
$ws = New-Object -ComObject WScript.Shell

# $args 를 파라미터 이름으로 쓰면 안 된다 — PowerShell 자동 변수라 언바운드
# 인자 배열(Object[])로 덮여서 $sc.Arguments 에 넣을 때 형변환이 터진다.
#
# 이름을 둘 받는다. 시스템 로캘이 한국어가 아닌 서버에서는 WScript.Shell 이
# 한글 파일명을 ANSI 로 낮추면서 '?' 로 바꾸는데, '?' 는 Windows 파일명에 쓸 수
# 없어 Save() 가 FileNotFoundException 을 던진다. 그래서 한글로 먼저 시도하고
# 실패하면 ASCII 이름으로 떨어진다 — 한국어 PC 에서는 한글 이름이 그대로 나오고,
# 영문 서버에서는 아이콘이 아예 안 생기는 대신 영문 이름으로라도 생긴다.
function New-Shortcut($name, $fallback, $exe, $argline, $desc) {
    foreach ($try in @($name, $fallback)) {
        $path = Join-Path $desktop ($try + ".lnk")
        try {
            $sc = $ws.CreateShortcut($path)
            $sc.TargetPath = $exe
            $sc.Arguments = [string]$argline
            $sc.WorkingDirectory = $AppDir   # OUT.json 이 cwd 상대경로다 — 반드시 필요
            $sc.IconLocation = $icon
            $sc.Description = $desc
            $sc.Save()
        } catch {
            if ($try -eq $fallback) {
                Fail ("바로가기 저장 실패: " + $path + "  (" + $_.Exception.Message + ")")
            }
            Write-Host ("[shortcut] 한글 이름 실패(시스템 로캘이 한국어가 아님) — 영문 이름으로 다시 시도") -ForegroundColor Yellow
            continue
        }
        if (-not (Test-Path $path)) {
            if ($try -eq $fallback) { Fail ("바로가기가 만들어지지 않았습니다: " + $path) }
            continue
        }
        Log ("만듦: " + $path)
        return
    }
}

if (-not $NoGui) {
    New-Shortcut "당근 명품 모니터" "Karrot Monitor (GUI)" $pyw "main.py" `
        "매물 감시 GUI — 키워드 등록, 매물 표, 가격 추적"
}
if (-not $NoHeadless) {
    New-Shortcut "당근 모니터 (서버·무인)" "Karrot Monitor (headless)" $py "main.py --headless" `
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

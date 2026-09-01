# 바탕화면 실행 아이콘 생성 (Windows). 관리자 권한 불필요.
#
#   powershell -ExecutionPolicy Bypass -File make_shortcuts.ps1
#
# 만드는 것:
#   "당근 명품 모니터"        → 창 있는 GUI 3탭 전부 (pythonw, 콘솔 안 뜸)
#   "당근 수동 검색"          → 수동 검색만 (--manual). 수확·폴링 안 함
#   "당근 매물 감시"          → 매물 감시 + 에뮬레이터 (--watch). 수확·폴링은 여기서만
#   "당근 모니터 (서버·무인)" → 헤드리스, 콘솔에 로그가 계속 찍힘
#
# 수동과 감시를 동시에 띄워도 된다 — 수확기는 감시 쪽만 돌리고, accounts.json
# 동시 쓰기는 프로세스 간 파일락이 막는다.
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
# 없어 Save() 가 FileNotFoundException 을 던진다.
#
# 그 한계는 COM 에 넘기는 **경로**에만 있다. 파일 이름 자체는 NTFS 에서 유니코드고
# .lnk 안에 이름이 들어가지도 않는다. 그래서 ASCII 이름으로 만든 뒤 .NET 으로
# 이름만 바꾼다 — 영문 로캘 서버에서도 한글 아이콘이 나오고, 시스템 로캘을
# 바꿀 필요가 없다(그건 재부팅을 부르고, 이 서버는 재부팅하면 사람이 RDP 로
# 붙기 전까지 함대가 안 뜬다).
function New-Shortcut($name, $fallback, $exe, $argline, $desc) {
    # 1) COM 이 확실히 다룰 수 있는 ASCII 이름으로 먼저 만든다.
    $tmp = Join-Path $desktop ($fallback + ".lnk")
    try {
        $sc = $ws.CreateShortcut($tmp)
        $sc.TargetPath = $exe
        $sc.Arguments = [string]$argline
        $sc.WorkingDirectory = $AppDir   # OUT.json 이 cwd 상대경로다 — 반드시 필요
        $sc.IconLocation = $icon
        $sc.Description = $desc
        $sc.Save()
    } catch {
        Fail ("바로가기 저장 실패: " + $tmp + "  (" + $_.Exception.Message + ")")
    }
    if (-not (Test-Path $tmp)) { Fail ("바로가기가 만들어지지 않았습니다: " + $tmp) }

    # 2) 이름만 한글로 바꾼다. 파일 이름은 유니코드라 로캘과 무관하고,
    #    .lnk 내용에는 이름이 안 들어가므로 바로가기는 그대로 동작한다.
    $final = Join-Path $desktop ($name + ".lnk")
    if ($final -eq $tmp) { Log ("만듦: " + $tmp); return }
    try {
        # 재설치는 이 스크립트를 다시 돌린다. 옛 아이콘이 남아 있으면 이름이
        # 겹쳐 Move 가 실패하므로 먼저 치운다.
        if (Test-Path $final) { Remove-Item $final -Force }
        [System.IO.File]::Move($tmp, $final)
        Log ("만듦: " + $final)
    } catch {
        # 이름 바꾸기가 실패해도 아이콘은 이미 있다 — 영문 이름으로 남기고 끝낸다.
        Write-Host ("[shortcut] 한글 이름으로 바꾸지 못했습니다(" +
                    $_.Exception.Message + ") — 영문 이름으로 둡니다") -ForegroundColor Yellow
        Log ("만듦: " + $tmp)
    }
}

if (-not $NoGui) {
    # 클라 요구(2026-09-01): 수동 검색과 '매물 감시+에뮬레이터'를 별도 프로그램으로.
    # 한 코드베이스에 실행 모드만 다르다(main.py --manual / --watch). 상태는
    # accounts.json 으로 공유되고, 동시 쓰기는 프로세스 간 파일락이 막는다.
    # 종전 3탭짜리 아이콘도 남긴다 — 기존 사용자가 쓰던 것이 사라지면 안 된다.
    New-Shortcut "당근 명품 모니터" "Karrot Monitor (GUI)" $pyw "main.py" `
        "매물 감시 GUI — 키워드 등록, 매물 표, 가격 추적"
    New-Shortcut "당근 수동 검색" "Karrot Manual Search" $pyw "main.py --manual" `
        "수동 검색 전용 — 감시·수확은 돌지 않는다"
    New-Shortcut "당근 매물 감시" "Karrot Watch" $pyw "main.py --watch" `
        "매물 감시 + 에뮬레이터 — 토큰 수확과 폴링은 이쪽만 한다"
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

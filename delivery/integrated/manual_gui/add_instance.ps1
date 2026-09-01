# 계정 추가 — .ldbk 백업을 새 LDPlayer 인스턴스로 복원한다.
#
#   powershell -ExecutionPolicy Bypass -File add_instance.ps1 -Ldbk D:\ldbk\inst6.ldbk -Name 정지6
#   powershell -ExecutionPolicy Bypass -File add_instance.ps1 -Ldbk D:\ldbk\inst6.ldbk -Name 정지6 -NoFleet
#
# 계정을 늘리는 유일한 방법이 이것이다. 프로그램의 'refresh 토큰 추가'는 당근 WAF
# 이전에 만든 경로라 지금은 동작하지 않는다 — 토큰은 에뮬레이터 안의 당근 앱에서만
# 나온다. 그래서 '계정을 추가한다 = 그 계정으로 로그인된 인스턴스를 만든다' 이다.
#
# 손으로 ldconsole 을 두드리지 말고 이 스크립트를 쓸 것. 아래 함정들 때문이다:
#   · 복원이 leidian<N>.config 를 초기화한다(해상도·ADB·루트 설정이 통째로 날아간다).
#     실제로 5개를 한꺼번에 복원했다가 전부 851바이트로 줄어든 적이 있다.
#   · 그 config 를 ConvertFrom-Json | ConvertTo-Json 으로 고치면 LDPlayer 가 파일을
#     기본값으로 리셋해 버린다. 반드시 텍스트 치환으로 고쳐야 한다.
#   · ADB 가 꺼진 백업이 있다(adbDebug=0). 그러면 VM 은 뜨는데 adb 에 안 잡혀
#     토큰 수확이 영영 안 된다.
#   · data/fleet.json 에 인덱스를 안 넣으면 새 인스턴스는 감시 대상에서 빠진다.
param(
    [Parameter(Mandatory = $true)][string]$Ldbk,
    [Parameter(Mandatory = $true)][string]$Name,
    [string]$AppDir = $PSScriptRoot,
    [switch]$NoFleet          # fleet.json 은 건드리지 않는다(수동으로 넣을 때)
)
$ErrorActionPreference = "Stop"
function Log($m) { Write-Host ("[계정추가] " + $m) -ForegroundColor Cyan }
function Fail($m) { Write-Host ("[계정추가][실패] " + $m) -ForegroundColor Red; exit 1 }

if (-not (Test-Path $Ldbk)) { Fail (".ldbk 파일이 없습니다: " + $Ldbk) }
$Ldbk = (Resolve-Path $Ldbk).Path

# ── ldconsole 찾기 ──
$console = $null
foreach ($p in @("D:\LDPlayer\LDPlayer9\ldconsole.exe",
                 "C:\LDPlayer\LDPlayer9\ldconsole.exe",
                 "D:\LDPlayer\LDPlayer64\ldconsole.exe",
                 "C:\LDPlayer\LDPlayer64\ldconsole.exe")) {
    if (Test-Path $p) { $console = $p; break }
}
if (-not $console) {
    $g = Get-ChildItem "C:\LDPlayer", "D:\LDPlayer" -Recurse -Filter ldconsole.exe -EA 0 |
         Select-Object -First 1
    if ($g) { $console = $g.FullName }
}
if (-not $console) { Fail "ldconsole.exe 를 못 찾았습니다. LDPlayer 설치 경로를 확인하세요." }
Log ("ldconsole: " + $console)
$ldDir = Split-Path $console
$vmsDir = Join-Path $ldDir "vms"

function Get-Indexes {
    (& $console list2) | ForEach-Object {
        $c = $_ -split ","
        if ($c.Length -ge 2 -and $c[0] -match '^\d+$') { [int]$c[0] }
    }
}

# ── 1. config 를 통째로 백업한다 ──
# 복원이 남의 config 까지 건드린 전례가 있다. 되돌릴 수 있게 먼저 떠 둔다.
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backup = Join-Path $env:TEMP ("ld_config_" + $stamp)
New-Item -ItemType Directory -Force -Path $backup | Out-Null
Get-ChildItem $vmsDir -Filter "leidian*.config" -EA 0 | ForEach-Object {
    Copy-Item $_.FullName $backup -Force
}
Log ("config 백업: " + $backup)

$before = @(Get-Indexes)
Log ("현재 인스턴스 " + $before.Count + "개")

# ── 2. 새 인스턴스 만들기 ──
Log ("새 인스턴스 만드는 중: " + $Name)
& $console add --name $Name | Out-Null
Start-Sleep -Seconds 2
$after = @(Get-Indexes)
$new = @($after | Where-Object { $before -notcontains $_ })
if ($new.Count -ne 1) {
    Fail ("새 인스턴스를 특정하지 못했습니다(추가 전 " + $before.Count +
          "개 → 후 " + $after.Count + "개). 같은 이름이 이미 있는지 확인하세요.")
}
$idx = $new[0]
Log ("새 인덱스: " + $idx)

# ── 3. 복원 ──
Log ("복원 중(파일 크기에 따라 수 분): " + (Split-Path $Ldbk -Leaf))
& $console restore --index $idx --file $Ldbk
if ($LASTEXITCODE -ne 0) { Fail ("restore 실패 (exit " + $LASTEXITCODE + ")") }
Start-Sleep -Seconds 2

# ── 4. config 점검 — ADB·루트가 켜져 있어야 토큰을 읽는다 ──
# JSON 왕복 금지. LDPlayer 가 그걸 보면 설정을 기본값으로 리셋한다.
$cfgPath = Join-Path $vmsDir ("leidian" + $idx + ".config")
if (-not (Test-Path $cfgPath)) {
    Log ("경고: " + $cfgPath + " 이 없습니다. 인스턴스를 한 번 켰다 끄면 생깁니다.")
} else {
    $raw = Get-Content $cfgPath -Raw
    $fixed = $raw
    if ($fixed -match '"basicSettings\.adbDebug"\s*:\s*0') {
        $fixed = $fixed -replace '("basicSettings\.adbDebug"\s*:\s*)0', '${1}1'
        Log "  adbDebug 0 → 1 (이게 0이면 adb 에 안 잡혀 토큰 수확이 안 됩니다)"
    }
    if ($fixed -notmatch '"basicSettings\.adbDebug"') {
        Log "  경고: adbDebug 항목이 없습니다. 인스턴스 설정 → 기타 → ADB '로컬 연결 열기' 를 켜세요."
    }
    if ($fixed -ne $raw) {
        Copy-Item $cfgPath ($cfgPath + ".bak-" + $stamp) -Force
        Set-Content -Path $cfgPath -Value $fixed -Encoding utf8 -NoNewline
        Log "  config 수정함(.bak 남김)"
    }
    if ((Get-Item $cfgPath).Length -lt 1200) {
        Log ("  경고: config 가 " + (Get-Item $cfgPath).Length +
             "바이트로 작습니다 — 복원이 설정을 초기화했을 수 있습니다.")
        Log ("  되돌리려면: " + $backup + " 의 파일을 " + $vmsDir + " 로 복사")
    }
}

# ── 5. 감시 대상에 넣기 ──
$fleet = Join-Path $AppDir "data\fleet.json"
if ($NoFleet) {
    Log ("fleet.json 은 건드리지 않았습니다. 감시하려면 인덱스 " + $idx + " 를 직접 넣으세요: " + $fleet)
} elseif (Test-Path $fleet) {
    $j = Get-Content $fleet -Raw | ConvertFrom-Json
    $list = @($j.indexes)
    if ($list -contains $idx) {
        Log ("fleet.json 에 이미 " + $idx + " 있음")
    } else {
        $list = @($list + $idx | Sort-Object)
        Copy-Item $fleet ($fleet + ".bak-" + $stamp) -Force
        # 여긴 우리 파일이라 JSON 으로 써도 된다(LDPlayer config 와 다르다).
        ('{"indexes": [' + ($list -join ", ") + ']}') |
            Set-Content -Path $fleet -Encoding utf8 -NoNewline
        Log ("fleet.json 에 " + $idx + " 추가 → [" + ($list -join ", ") + "]")
    }
} else {
    Log ("fleet.json 이 없어 만들지 않았습니다(없으면 전체 인스턴스가 대상입니다): " + $fleet)
}

Write-Host ""
Log "완료. 남은 순서:"
Log ("  1) RDP 로 서버에 접속한 상태에서 인스턴스를 켠다 (인덱스 " + $idx + ")")
Log "     — LDPlayer 는 실제 RDP 세션이 붙어 있어야 게스트를 띄웁니다."
Log "  2) 앱이 로그인돼 있으면 다음 수확에서 토큰이 잡히고 계정 목록에 나타납니다."
Log "     로그아웃 상태면 개조앱의 'Enter code' 가 필요합니다(우리가 못 만듭니다)."
Log "  3) 매물 감시 탭 → 계정+프록시 → 그 계정을 골라 프록시를 지정합니다."

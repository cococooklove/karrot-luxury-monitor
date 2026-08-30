# LDPlayer 순차 기동 (부팅 자동실행용).
#
# 무인 부팅에서 지켜야 하는 두 가지:
#  1) 콘솔 세션(사람이 RDP 로 붙지 않은 자동로그온 상태)에서는 LDPlayer 가 게스트를
#     띄우지 못한다. VM 은 RUNNING 까지 가지만 게스트 커널이 실행되지 않아 adb 기기가
#     끝내 안 뜬다. → 루프백 RDP 로 세션을 승격시킨 뒤에 기동한다.
#  2) 인스턴스를 동시에 launch 하면 같은 증상으로 hang 한다. → 1개씩, 그리고 다음 것을
#     띄우기 전에 adb 기기 수가 실제로 늘었는지 확인한다.
$log = "C:\karrot\ldboot.log"
function W($m) { "$([DateTime]::Now.ToString('HH:mm:ss')) $m" | Out-File $log -Append -Encoding UTF8 }

# LDPlayer 설치 경로는 서버마다 다르다(현행 운영 서버는 D:, 문서 예시는 C:).
# 하드코딩하면 다른 서버로 그대로 옮겼을 때 launch 가 조용히 아무 일도 안 하고 끝난다.
# → 후보 루트를 훑어 adb.exe + ldconsole.exe 가 실제로 있는 폴더를 찾는다.
$ld = $null
foreach ($root in @("D:\LDPlayer", "C:\LDPlayer", "C:\Program Files\LDPlayer", "C:\Program Files (x86)\LDPlayer")) {
    if (-not (Test-Path $root)) { continue }
    $cands = @($root) + @(Get-ChildItem $root -Directory -ErrorAction SilentlyContinue |
                          Sort-Object Name -Descending | ForEach-Object { $_.FullName })
    foreach ($c in $cands) {
        if ((Test-Path "$c\adb.exe") -and ((Test-Path "$c\ldconsole.exe") -or (Test-Path "$c\dnconsole.exe"))) {
            $ld = $c; break
        }
    }
    if ($ld) { break }
}
if (-not $ld) { W "LDPlayer 설치 경로를 찾지 못했습니다 - 중단"; exit 1 }
$adb = "$ld\adb.exe"
$console = if (Test-Path "$ld\ldconsole.exe") { "$ld\ldconsole.exe" } else { "$ld\dnconsole.exe" }
W "LDPlayer 경로: $ld"
function DevCount { (& $adb devices | Select-String "device$").Count }
W "=== ldboot 시작 ==="

# 부팅 직후 시스템 안정화 대기
Start-Sleep 60

# --- 1) 콘솔 세션이면 루프백 RDP 로 승격 ---
if ((quser 2>$null) -match "rdp-tcp") {
    W "이미 RDP 세션 - 승격 생략"
}
else {
    $w = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
    if (-not $w.DefaultPassword) {
        W "DefaultPassword 없음 - RDP 승격 불가(콘솔 세션에서는 기동 실패함)"
    }
    else {
        # RDP 포트는 기본 3389 가 아닐 수 있다(이 서버는 1098) → 레지스트리에서 읽는다.
        $port = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp").PortNumber
        if (-not $port) { $port = 3389 }
        $target = "localhost:$port"
        cmdkey /generic:TERMSRV/localhost /user:$($w.DefaultUserName) /pass:$($w.DefaultPassword) | Out-Null
        cmdkey /generic:TERMSRV/$target /user:$($w.DefaultUserName) /pass:$($w.DefaultPassword) | Out-Null
        # 자체 서명 인증서 경고 모달이 뜨면 무인 진행이 막힌다 → 경고 무시
        New-Item -Path "HKCU:\Software\Microsoft\Terminal Server Client" -Force | Out-Null
        Set-ItemProperty "HKCU:\Software\Microsoft\Terminal Server Client" -Name AuthenticationLevelOverride -Value 0 -Type DWord
        # 접속 설정은 .rdp 파일로 넘긴다(자격증명 프롬프트/인증서 확인 끔)
        $rdp = "C:\karrot\loopback.rdp"
        @(
          "full address:s:$target"
          "username:s:$($w.DefaultUserName)"
          "authentication level:i:0"
          "prompt for credentials:i:0"
          "promptcredentialonce:i:0"
          "negotiate security layer:i:1"
          "screen mode id:i:1"
          "desktopwidth:i:1920"
          "desktopheight:i:1080"
          "session bpp:i:32"
        ) | Set-Content $rdp -Encoding ASCII
        # 부팅 직후엔 RDP 리스너가 아직 안 떠 있을 수 있으므로 포트가 열릴 때까지 대기
        for ($i = 0; $i -lt 30; $i++) {
            if ((Test-NetConnection -ComputerName localhost -Port $port -WarningAction SilentlyContinue).TcpTestSucceeded) { break }
            Start-Sleep 5
        }
        for ($try = 1; $try -le 3; $try++) {
            W "루프백 RDP 접속 시도 $try ($target)"
            # .rdp 파일로 띄우면 "게시자를 확인할 수 없습니다" 경고가 뜬다 → /v 인수로 직접 접속
            Start-Process mstsc -ArgumentList "/v:$target", "/w:1920", "/h:1080"
            for ($i = 0; $i -lt 12; $i++) {
                Start-Sleep 5
                if ((quser 2>$null) -match "rdp-tcp") { break }
            }
            if ((quser 2>$null) -match "rdp-tcp") { W "RDP 세션 승격 완료"; break }
            taskkill /IM mstsc.exe /F 2>$null | Out-Null   # 실패 팝업 정리
            Start-Sleep 10
        }
        if (-not ((quser 2>$null) -match "rdp-tcp")) { W "RDP 승격 실패 - 그대로 진행(기동 실패 예상)" }
        Start-Sleep 10
    }
}

# --- 2) 인스턴스 순차 기동 ---
# 1=정지6, 2=정지7, 3=정지9, 4=정지11, 5=정지13. 0=클라 원본 제외.
$indexes = 1, 2, 3, 4, 5
$bootWait = 180     # 인스턴스당 최대 대기(초)
$retry = 1          # 실패시 재기동 횟수

foreach ($i in $indexes) {
    $before = DevCount
    $ok = $false
    for ($a = 0; $a -le $retry -and -not $ok; $a++) {
        if ($a -gt 0) {
            W "index $i 기동 실패 - 재기동 $a/$retry"
            $procid = (Get-CimInstance Win32_Process -Filter "name='dnplayer.exe'" | Where-Object { $_.CommandLine -match "index=$i\|" }).ProcessId
            if ($procid) { Stop-Process -Id $procid -Force -ErrorAction SilentlyContinue }
            Start-Sleep 10
        }
        W "launch index $i"
        & $console launch --index $i
        $waited = 0
        while ($waited -lt $bootWait) {
            Start-Sleep 5; $waited += 5
            if ((DevCount) -gt $before) { $ok = $true; W "index $i 기동 완료 (${waited}s)"; break }
        }
    }
    if (-not $ok) { W "index $i 기동 실패 - 건너뜀" }
    Start-Sleep 5
}

$n = DevCount
W "최종 adb devices=$n / $($indexes.Count)"
& $adb devices | Out-File $log -Append -Encoding UTF8
W "=== ldboot 완료 ==="

# --- 3) 인스턴스가 다 올라온 뒤에야 모니터 앱 시작 ---
# 앱의 ensure_ldplayer 가 동시 기동을 하지 않도록 HKCU Run 에서 앱은 빼고 여기서만 띄운다.
W "모니터 앱 시작"
schtasks /run /tn karrotgui | Out-File $log -Append -Encoding UTF8

# LDPlayer 순차 기동 (부팅 자동실행용).
#
# 무인 부팅에서 지켜야 하는 두 가지:
#  1) 콘솔 세션(사람이 RDP 로 붙지 않은 자동로그온 상태)에서는 LDPlayer 가 게스트를
#     띄우지 못한다. VM 은 RUNNING 까지 가지만 게스트 커널이 실행되지 않아 adb 기기가
#     끝내 안 뜬다. → 루프백 RDP 로 세션을 승격시킨 뒤에 기동한다.
#  2) 인스턴스를 동시에 launch 하면 같은 증상으로 hang 한다. → 1개씩, 그리고 다음 것을
#     띄우기 전에 adb 기기 수가 실제로 늘었는지 확인한다.
$ld = "D:\LDPlayer\LDPlayer9"
$adb = "$ld\adb.exe"
$console = "$ld\ldconsole.exe"
$log = "C:\karrot\ldboot.log"
function W($m) { "$([DateTime]::Now.ToString('HH:mm:ss')) $m" | Out-File $log -Append -Encoding UTF8 }
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
        cmdkey /generic:TERMSRV/localhost /user:$($w.DefaultUserName) /pass:$($w.DefaultPassword) | Out-Null
        W "루프백 RDP 접속 시도"
        Start-Process mstsc -ArgumentList "/v:localhost", "/w:1920", "/h:1080"
        for ($i = 0; $i -lt 24; $i++) {
            Start-Sleep 5
            if ((quser 2>$null) -match "rdp-tcp") { W "RDP 세션 승격 완료 ($($i * 5 + 5)s)"; break }
        }
        if (-not ((quser 2>$null) -match "rdp-tcp")) { W "RDP 승격 실패 - 그대로 진행" }
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

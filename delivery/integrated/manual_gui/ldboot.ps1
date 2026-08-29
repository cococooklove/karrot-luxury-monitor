# LDPlayer 순차 기동 (부팅 자동실행용).
# 동시 기동하면 게스트 커널이 시작조차 못하고 VM 이 hang → 반드시 1개씩,
# 그리고 "다음 것 띄우기 전에 adb 기기 수가 실제로 늘었는지" 확인한다.
$ld = "D:\LDPlayer\LDPlayer9"
$adb = "$ld\adb.exe"
$console = "$ld\ldconsole.exe"
$log = "C:\karrot\ldboot.log"
function W($m) { "$([DateTime]::Now.ToString('HH:mm:ss')) $m" | Out-File $log -Append -Encoding UTF8 }
function DevCount { (& $adb devices | Select-String "device$").Count }
W "=== ldboot 시작 ==="

# 부팅 직후 시스템 안정화 대기
Start-Sleep 60

# 수확 대상 인스턴스 (1=정지6, 2=정지7, 3=정지9, 4=정지11, 5=정지13). 0=클라 원본 제외.
$indexes = 1, 2, 3, 4, 5
$bootWait = 180     # 인스턴스당 최대 대기(초)
$retry = 1          # 실패시 재기동 횟수

foreach ($i in $indexes) {
    $before = DevCount
    $ok = $false
    for ($a = 0; $a -le $retry -and -not $ok; $a++) {
        if ($a -gt 0) {
            W "index $i 기동 실패 → 재기동 $a/$retry"
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
    if (-not $ok) { W "index $i 기동 실패 — 건너뜀" }
    Start-Sleep 5
}

$n = DevCount
W "최종 adb devices=$n / $($indexes.Count)"
& $adb devices | Out-File $log -Append -Encoding UTF8
W "=== ldboot 완료 ==="

# 인스턴스 기동 끝난 뒤에야 모니터 앱 시작(동시 기동 충돌 방지).
# 앱은 HKCU Run 에서 제거하고 여기서만 띄운다.
W "모니터 앱 시작"
schtasks /run /tn karrotgui | Out-File $log -Append -Encoding UTF8

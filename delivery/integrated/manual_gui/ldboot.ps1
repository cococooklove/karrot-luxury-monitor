# LDPlayer 순차 기동 (부팅 자동실행용).
#
# 무인 부팅에서 지켜야 하는 두 가지:
#  1) 콘솔 세션(사람이 RDP 로 붙지 않은 자동로그온 상태)에서는 LDPlayer 가 게스트를
#     띄우지 못한다. VM 은 RUNNING 까지 가지만 게스트 커널이 실행되지 않아 adb 기기가
#     끝내 안 뜬다. → tscon 으로 세션을 콘솔에 붙인 뒤에 기동한다(안 되면 루프백 RDP).
#  2) 인스턴스를 동시에 launch 하면 같은 증상으로 hang 한다. → 1개씩, 그리고 다음 것을
#     띄우기 전에 adb 기기 수가 실제로 늘었는지 확인한다.
#  3) LDPlayer 를 못 찾아도 모니터 앱은 반드시 띄운다. 앱은 HKCU Run 에서 빠져 있어
#     이 스크립트가 유일한 기동 경로이고, 앱 자신의 ensure_ldplayer 가 뒤늦게 복구할
#     여지가 있기 때문이다. 여기서 중단해 버리면 아무것도 안 뜬 채 조용히 끝난다.
$log = "C:\karrot\ldboot.log"
function W($m) { "$([DateTime]::Now.ToString('HH:mm:ss')) $m" | Out-File $log -Append -Encoding UTF8 }

function DevCount { (& $adb devices | Select-String "device$").Count }

# 인덱스 하나가 실제로 응답하는지 본다. 전체 기기 수 증가로 판정하면 안 된다 —
# 이미 떠 있는 상태에서 이 스크립트를 다시 돌리면 수가 안 늘어 전부 '기동 실패'가
# 되고, 재시도 단계가 멀쩡히 돌던 인스턴스를 taskkill 해 함대를 되레 무너뜨린다.
# (androidStarted=1 인데 게스트가 hang 한 인스턴스도 이 프로브로만 걸러진다.)
# 창 없이(-WindowStyle Hidden) 돌 때 네이티브 명령 출력 캡처가 막혀 스크립트가
# 통째로 멈춘 적이 있다(부팅 자동실행에서 15분 무응답, 로그도 안 찍힘).
# 자식 잡으로 돌리고 시한을 둬서, 막히더라도 그 인덱스만 실패로 넘긴다.
function Probe($i) {
    $j = Start-Job -ArgumentList $console, $i -ScriptBlock {
        param($c, $idx)
        & $c adb --index $idx --command "shell echo PROBE_OK" 2>&1
    }
    $done = Wait-Job $j -Timeout 60
    $out = if ($done) { Receive-Job $j 2>$null } else { $null }
    Remove-Job $j -Force -ErrorAction SilentlyContinue
    if (-not $done) { W "index $i 프로브 시한 초과(60s) - 응답 없음으로 처리" }
    return (($out -join " ") -match "PROBE_OK")
}

# 반쯤 뜬 인스턴스를 확실히 지운다. quit 만으로는 안 죽는 경우가 있어 프로세스까지 본다.
function Reset($i) {
    Start-Process -FilePath $console -ArgumentList @("quit", "--index", "$i") -WindowStyle Hidden -Wait
    # LDPlayer 는 종료할 때 vms\config\leidian<N>.config 를 다시 쓴다. 그 도중에
    # 강제 종료하면 파일이 잘린 채 남고, 해상도가 0 이 된 인스턴스는 다시는 안 뜬다.
    # 실측(2026-08-30): index 1 이 이렇게 3945바이트 → 1015바이트로 잘려 죽었다.
    # 그래서 스스로 사라질 시간을 충분히 준 뒤에만 손을 댄다.
    for ($w = 0; $w -lt 30; $w += 3) {
        Start-Sleep 3
        $alive = (Get-CimInstance Win32_Process -Filter "name='dnplayer.exe'" |
                  Where-Object { $_.CommandLine -match "index=$i\|" })
        if (-not $alive) { return }
    }
    $procid = (Get-CimInstance Win32_Process -Filter "name='dnplayer.exe'" |
               Where-Object { $_.CommandLine -match "index=$i\|" }).ProcessId
    if ($procid) {
        W "index $i 30초 안에 안 죽음 - 강제 종료 (pid $procid). 설정 파일이 손상될 수 있다"
        Stop-Process -Id $procid -Force -ErrorAction SilentlyContinue
        Start-Sleep 5
    }
}
W "=== ldboot 시작 ==="

# 부팅 직후 시스템 안정화 대기
Start-Sleep 60

# --- 0) LDPlayer 설치 폴더 탐색 ---
# 경로는 서버마다 다르다(현행 운영 서버는 D:, 문서 예시는 C:). 하드코딩하면 다른
# 서버로 옮겼을 때 ldconsole 호출이 빈 명령이 되어 조용히 아무것도 안 뜬다.
# 탐색 순서는 앱(ld_autoharvest._LD_DIRS)과 반드시 같아야 한다 — 다르면 이 스크립트가
# 띄운 인스턴스와 앱이 토큰을 수확하는 인스턴스가 서로 다른 설치본이 된다.
# 볼륨이 아직 안 붙었을 수 있으므로 안정화 대기 뒤에 찾는다.
$ld = $null
foreach ($root in @("C:\LDPlayer", "D:\LDPlayer",
                    "C:\Program Files\LDPlayer", "C:\Program Files (x86)\LDPlayer")) {
    if (-not (Test-Path $root)) { continue }
    $cands = @()
    foreach ($v in @("LDPlayer14", "LDPlayer9", "LDPlayer4.0", "LDPlayer64")) { $cands += "$root\$v" }
    $cands += $root
    $cands += @(Get-ChildItem $root -Directory -Filter "LDPlayer*" -ErrorAction SilentlyContinue |
                ForEach-Object { $_.FullName })
    foreach ($c in $cands) {
        if ((Test-Path "$c\adb.exe") -and
            ((Test-Path "$c\ldconsole.exe") -or (Test-Path "$c\dnconsole.exe"))) { $ld = $c; break }
    }
    if ($ld) { break }
}
if ($ld) {
    $adb = "$ld\adb.exe"
    $console = if (Test-Path "$ld\ldconsole.exe") { "$ld\ldconsole.exe" } else { "$ld\dnconsole.exe" }
    W "LDPlayer 경로: $ld"
}
else {
    W "LDPlayer 설치 폴더를 찾지 못했습니다 - 인스턴스 기동을 건너뛰고 모니터 앱만 시작합니다"
}

if ($ld) {
    # --- 1) RDP 세션 확인 ---
    # LDPlayer 는 '실제 RDP 연결이 붙어 있는' 세션에서만 게스트를 띄운다. 2026-08-30
    # 재부팅 2회로 실측했다:
    #   세션 없음/Disc                     → VM 만 RUNNING, adb 기기 0
    #   tscon 으로 콘솔에 붙여 Active 로 만듦 → 여전히 adb 기기 0
    #   사람이 RDP 로 접속                  → 인스턴스당 20초에 전부 기동
    # 그래서 판정은 'Active 인가'가 아니라 'rdp-tcp 세션인가'여야 한다. Active 로
    # 판정했더니 tscon 이 만든 console-Active 를 통과시켜, 유일하게 듣는 루프백 RDP
    # 승격을 건너뛰는 역효과가 났다.
    $hasRdp = ((quser 2>$null) -match "rdp-tcp")
    if ($hasRdp) {
        W "RDP 세션 확인 - 기동 진행"
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
            Start-Sleep 10
        }
        $hasRdp = ((quser 2>$null) -match "rdp-tcp")
    }

    # --- 2) 인스턴스 순차 기동 ---
    # 운영 서버 실측(list2): 0=LDPlayer(클라 원본, 제외), 1=LDPlayer-1,
    # 2=정지7-0822, 3=정지9-0822, 4=정지11-0822, 5=정지13-0822.
    # index 1 은 이름만 기본값이지 계정 인스턴스가 맞다(karrot_token.ds 를 갖고 있다).
    $indexes = 1, 2, 3, 4, 5
    if (-not $hasRdp) {
        # 이 상태로 launch 하면 VM 만 뜨고 게스트가 안 올라온다. 인덱스마다 재시도까지
        # 다 돌면 15분을 헛되이 태우고 결과도 같다 → 시도하지 않고 할 일만 남긴다.
        W "!! RDP 세션이 없습니다 - 인스턴스 기동을 건너뜁니다."
        W "!! LDPlayer 는 실제 RDP 연결이 붙은 세션에서만 게스트를 띄웁니다(실측)."
        W "!! 사람이 RDP 로 접속한 뒤 아래를 실행하면 복구됩니다:"
        W "!!   powershell -ExecutionPolicy Bypass -File C:\karrot\ldboot.ps1"
        $indexes = @()
    }
    $bootWait = 180     # 인스턴스당 최대 대기(초)
    $retry = 1          # 실패시 재기동 횟수
    W "순차 기동 시작 (대상 $($indexes.Count)개)"

    foreach ($i in $indexes) {
        W "index $i 확인"
        if (Probe $i) { W "index $i 이미 살아 있음 - 건너뜀"; Start-Sleep 2; continue }
        # 프로브가 응답 없다고 답한 인덱스는 '안 떠 있는' 게 아니라 'VM 은 있는데 게스트가
        # hang 한' 상태일 수 있다. 그 상태에서 launch 는 no-op 이라 3분을 기다렸다 실패한다.
        # 실측(2026-08-30): index 2·3 모두 첫 launch 는 3분 14초 만에 실패, 프로세스를
        # 죽이고 다시 띄우니 20초에 떴다. 그래서 처음부터 지우고 시작한다.
        Reset $i
        $ok = $false
        for ($a = 0; $a -le $retry -and -not $ok; $a++) {
            if ($a -gt 0) {
                W "index $i 기동 실패 - 재기동 $a/$retry"
                Reset $i
            }
            W "launch index $i"
            # 출력을 파이프로 받지 않는다. 창 없는 세션에서 네이티브 명령의 출력 스트림이
            # 막히면 스크립트가 통째로 멈춘다(프로브와 같은 이유).
            Start-Process -FilePath $console -ArgumentList @("launch", "--index", "$i") -WindowStyle Hidden
            $waited = 0
            while ($waited -lt $bootWait) {
                Start-Sleep 5; $waited += 5
                if (Probe $i) { $ok = $true; W "index $i 기동 완료 (${waited}s)"; break }
            }
        }
        if (-not $ok) { W "index $i 기동 실패 - 건너뜀" }
        Start-Sleep 5
    }

    $n = DevCount
    W "최종 adb devices=$n / $($indexes.Count)"
    & $adb devices | Out-File $log -Append -Encoding UTF8
    W "=== ldboot 완료 ==="
}

# --- 3) 인스턴스가 다 올라온 뒤에야 모니터 앱 시작 ---
# 앱의 ensure_ldplayer 가 동시 기동을 하지 않도록 HKCU Run 에서 앱은 빼고 여기서만 띄운다.
W "모니터 앱 시작"
schtasks /run /tn karrotgui | Out-File $log -Append -Encoding UTF8

# GitHub Actions 배포 진입점 — 고정 경로. 내용은 거의 안 바뀌게 최소로 둔다.
#
# authorized_keys 의 command= 가 배포 키를 이 파일에만 묶어 둔다. 그래서 키가
# 새더라도 할 수 있는 일은 "재배포 트리거" 하나뿐이고 셸은 열리지 않는다.
#
# C:\karrot 안에 두지 않는 이유: 재설치가 그 폴더를 통째로 갈아끼운다.
# ldboot.ps1 shim 과 같은 이유다.
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
# update.ps1 의 출력을 그대로 흘려보내므로 콘솔 인코딩을 여기서 UTF-8 로 맞춘다.
# 안 하면 Actions 로그와 배포 로그의 한글이 깨져, 실패했을 때 읽을 수가 없다.
chcp 65001 > $null
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8
$log = "C:\karrot_deploy.log"
function W($m) {
  $line = "$([DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss')) $m"
  Write-Output $line
  Add-Content -Path $log -Value $line -Encoding UTF8
}

W "=== 배포 시작 ==="
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$zip = "$env:TEMP\kdep_$ts.zip"
$ext = "$env:TEMP\kdep_$ts"
$code = 1
try {
  # codeload ZIP 은 요청 시 생성된다 — raw 와 달리 CDN 캐시로 옛 판을 받지 않는다.
  Invoke-WebRequest "https://github.com/cococooklove/karrot-luxury-monitor/archive/refs/heads/master.zip" -OutFile $zip
  Expand-Archive $zip -DestinationPath $ext -Force
  $u = "$ext\karrot-luxury-monitor-master\delivery\integrated\manual_gui\update.ps1"
  if (-not (Test-Path $u)) { throw "ZIP 안에 update.ps1 이 없다: $u" }
  $global:LASTEXITCODE = 0
  & $u 2>&1 | ForEach-Object { W $_ }
  $code = if ($null -ne $LASTEXITCODE) { $LASTEXITCODE } else { 0 }
} catch {
  W ("[실패] " + $_.Exception.Message)
  $code = 1
} finally {
  Remove-Item $ext -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item $zip -Force -ErrorAction SilentlyContinue
}
W "=== 배포 종료 exit=$code ==="
exit $code

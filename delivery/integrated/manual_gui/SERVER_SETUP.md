# 서버 배포 (DatabaseMart Windows + LDPlayer)

클라우드 Windows 서버에 무인 배포. 접속 채널 확보 후 진행.

## 0. 접속 채널 (택1)
- **SSH**: RDP 1회 접속 → `Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0; Start-Service sshd; Set-Service sshd -StartupType Automatic; New-NetFirewallRule -Name sshd -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22` → **프로바이더 방화벽서 22 개방**(DatabaseMart 콘솔).
- **웹 콘솔(KVM)**: DatabaseMart 패널서 서버 콘솔 직접.

## 1. 런타임 설치 (PowerShell)
```powershell
# Python + Git
winget install -e --id Python.Python.3.12 --silent
winget install -e --id Git.Git --silent
# 레포
git clone https://github.com/cococooklove/karrot-luxury-monitor C:\karrot
cd C:\karrot\delivery\integrated\manual_gui
python -m pip install -e .
```

## 2. LDPlayer (토큰 수확용)
- LDPlayer 설치(공식). 인스턴스 N개 = 계정 N개(각기 다른 동네 로그인).
- 각 인스턴스: 당근 디버그앱 설치(run-as 수확) + 계정 로그인 + GPS 동네 설정 + **KR 프록시** 바인딩.
- `ld_autoharvest`가 `C:\LDPlayer\LDPlayer*` 자동탐지 → adb 수확.

## 3. 설정 파일
```
C:\karrot\delivery\integrated\manual_gui\
  accounts.json          ← 수확되면 자동 생성/갱신
  notify.json            ← {"tg_token","tg_chat","sheet_url","sheet_cred"}
  data\config.json       ← 디바이스 헤더(추출물)
  data\alert_settings.json ← {"core_only":true/false,"night":true/false}
  data\core_regions.json ← (선택) 핵심지역 키워드
```

## 4. 무인 실행 (헤드리스)
```powershell
cd C:\karrot\delivery\integrated\manual_gui
python main.py --headless
# 옵션: --interval=120  --once(테스트)  --no-harvest
```
- 등록·폴링·수확·텔레그램·시트 전부 GUI 없이.
- 커버모드/야간감속 = alert_settings.json 따름.

## 5. 자동시작 (install.ps1 이 등록한다 — 손으로 만들지 말 것)

`install.ps1` 6단계가 아래를 멱등하게 등록한다. 추가 작업은 필요 없다.

| 항목 | 값 | 역할 |
|---|---|---|
| HKCU `Run\LDPlayerBoot` | `powershell -File C:\karrot\ldboot.ps1` | 로그온 시 함대 순차 기동 |
| `C:\karrot\ldboot.ps1` | 리포 사본(`delivery\integrated\manual_gui\ldboot.ps1`)을 부르는 shim | 자동실행이 보는 고정 경로 |
| 작업 `karrotgui` | `pythonw main.py --watchdog` (작업 폴더 = 앱 폴더), **트리거 없음** | `ldboot.ps1` 이 마지막에 `schtasks /run /tn karrotgui` 로 호출. `--watchdog` 이 크래시 시 앱을 되살린다 |

왜 이 모양인가:

- **shim 이 필요한 이유** — 자동실행 진입점은 `C:\karrot\ldboot.ps1` 로 고정인데 재설치는
  `C:\karrot` 을 통째로 갈아끼운다. 실제 파일을 거기 두면 재설치 한 번에 사라지고,
  부팅해도 함대도 앱도 안 뜬다(운영 서버에서 실제로 이렇게 깨져 있었다).
- **SYSTEM 으로 돌리면 안 되는 이유** — LDPlayer 는 실제 RDP 연결이 붙은 사용자 세션에서만
  게스트를 띄운다(아래 제약 참고). `ldboot.ps1` 의 승격 시도도 로그온 사용자 권한이 필요하다.
- **`karrotgui` 에 트리거를 두지 않는 이유** — 앱의 `ensure_ldplayer` 와 `ldboot.ps1` 이
  동시에 인스턴스를 띄우면 게스트 커널이 hang 한다. 반드시 함대가 다 올라온 뒤에 호출한다.

수동 조작:

```powershell
schtasks /run /tn karrotgui                       # 앱만 다시 띄우기
powershell -ExecutionPolicy Bypass -File C:\karrot\ldboot.ps1   # 함대까지 처음부터
```

> 겹치는 옛 작업(`karrotgui2`, `karrotgui3`, `ldlaunch0~5`, `ldboot1`, `ldq1`, `rdpsess` 등)이
> 남아 있으면 `install.ps1` 이 노란 경고로 알려준다. `ldlaunch*` 가 동시에 돌면 LDPlayer 가
> hang 하고 `karrotgui2/3` 는 앱을 중복 실행하므로, 확인 후 `schtasks /delete /tn <이름> /f`.

### 재부팅하면 사람이 RDP 로 한 번 붙어야 한다 (제약)

**LDPlayer 는 실제 RDP 연결이 붙어 있는 세션에서만 게스트를 띄운다.** 2026-08-30 재부팅
2회로 실측했다:

| 세션 상태 | 인스턴스 기동 |
|---|---|
| 없음 / `Disc` | ❌ VM 만 RUNNING, `adb devices` 0 |
| `tscon` 으로 콘솔에 붙여 `Active` | ❌ 동일 |
| 사람이 RDP 접속 (`rdp-tcp#0` `Active`) | ✅ 인스턴스당 20초 |

`ldboot.ps1` 은 루프백 RDP 로 세션을 승격시켜 이걸 무인화하려 하지만, 이 서버에서는
3회 시도 모두 실패했다. 그래서 **무인 재부팅 복구는 되지 않는다.**

RDP 세션을 못 얻으면 기동을 시도하지 않고(어차피 실패하고 15분을 태운다) 로그에 할 일만
남긴 뒤 모니터 앱만 띄운다. `C:\karrot\ldboot.log` 에 이렇게 찍힌다:

```
!! RDP 세션이 없습니다 - 인스턴스 기동을 건너뜁니다.
!! 사람이 RDP 로 접속한 뒤 아래를 실행하면 복구됩니다:
!!   powershell -ExecutionPolicy Bypass -File C:\karrot\ldboot.ps1
```

복구 절차: RDP 접속 → 위 명령 실행 → 5~10분 → **연결 끊기로 나온다(로그오프 금지)**.
한 번 뜬 인스턴스는 연결을 끊어도 계속 돈다. 활성 세션은 **기동할 때만** 필요하다.

## 5-1. 방화벽 (반드시 적용)

2026-08-30 점검에서 **에뮬레이터 ADB 포트가 인터넷에 열려 있었다.** 누구든
`adb connect` 로 붙어 `karrot_token.ds`(계정 세션)를 그대로 가져갈 수 있는
상태였다. SMB(445) 로는 무차별 로그인 시도가 24시간에 2,000건 들어오고 있었다
(NOUSER 1636, ADMINISTRATOR 76 — 전형적인 봇 사전공격).

서버를 새로 세우면 아래를 다시 넣는다. 로컬(127.0.0.1) 통신은 방화벽을 타지
않으므로 토큰 수확에는 영향이 없다.

```powershell
New-NetFirewallRule -DisplayName karrot-block-smb   -Direction Inbound -Action Block -Protocol TCP -LocalPort 135,139,445
New-NetFirewallRule -DisplayName karrot-block-adb   -Direction Inbound -Action Block -Protocol TCP -LocalPort 2222,5554-5600
New-NetFirewallRule -DisplayName karrot-block-winrm -Direction Inbound -Action Block -Protocol TCP -LocalPort 5985,47001
```

SSH(22)·RDP(1098)는 접속에 필요하므로 열어 둔다. 적용 뒤 **바깥에서** 확인한다:

```bash
nc -z -G 4 <서버> 445    # 막혀야 정상
nc -z -G 4 <서버> 5559   # 막혀야 정상
nc -z -G 4 <서버> 1098   # 열려야 정상
```

자동로그온 비밀번호는 레지스트리에 평문으로 있다. RDP 비밀번호를 바꿀 때는
`Winlogon\DefaultPassword` 도 **같은 값으로** 함께 바꾼다. 하나만 바꾸면 재부팅
뒤 자동로그온이 깨져 세션이 안 생기고, 그러면 함대도 앱도 뜨지 않는다.

## 5-2. 인스턴스 하나만 끝내 안 뜰 때

`adb devices` 에 특정 인덱스만 계속 안 나오면 `.ldbk` 재복원으로 가기 전에
**설정 파일 두 개를 먼저 의심한다.** 2026-08-30 에 index 1 이 이 두 가지로
연달아 죽었고, 디스크(`data.vmdk`)는 멀쩡했다.

**(1) `vms\config\leidian<N>.config` 가 잘렸는가**

정상은 4KB 안팎인데 1KB로 잘려 있고 `realWidth`/`realHeigh` 가 `0` 이면 이것이다.
LDPlayer 는 종료할 때 이 파일을 다시 쓰는데 그 도중에 강제 종료되면 잘린다
(ldboot 의 Reset 이 범인이었다 — 지금은 30초까지 정상 종료를 기다린다).

같은 폴더의 `.resbak`(온전한 백업)에서 구조를 가져오되, **지문 필드는 현재
파일 값을 유지**한다. 백업을 통째로 되돌리면 기기 정보가 지금 로그인된 세션과
어긋나 밴 신호가 된다. 유지할 키:
`phoneIMEI` `phoneIMSI` `phoneSimSerial` `phoneAndroidId` `phoneModel`
`phoneManufacturer` `macAddress`

**(2) `vms\leidian<N>\leidian.vbox` 가 엉뚱한 사양으로 굳었는가**

정상 인스턴스와 `CPU count`·`RAMSize` 를 비교한다. index 1 은 6CPU/6144MB 였고
나머지는 2CPU/1024MB 였다. 이 파일은 `.config` 를 고쳐도 자동으로 다시 안 쓰인다.
옆으로 치우면 다음 기동 때 `.config` 기준으로 재생성된다:

```powershell
Move-Item D:\LDPlayer\LDPlayer9\vms\leidian1\leidian.vbox `
          D:\LDPlayer\LDPlayer9\vms\leidian1\leidian.vbox.stale -Force
```

치운 뒤에는 앱의 `ensure_ldplayer`(20분 주기)가 알아서 되살린다. 실제로 index 1
은 이 한 번으로 복구됐고 `karrot_token.ds` 도 그대로 살아 있었다.

## 5-3. RDP 가 `프로토콜 오류(코드: 0x112f)` 로 3초 만에 끊길 때

메모리 부족처럼 보이지만 아니다. 2026-08-31 에 실측했다. 서버는 32GB 중
21.5GB 가 남아 있었고 함대(11 프로세스)도 앱도 정상이었다.

`Microsoft-Windows-RemoteDesktopServices-RdpCoreTS/Operational` 을 보면 인증은
통과하고 세션까지 배정된 뒤에 끊긴다:

```
3:26:43  AuthenticateClientToSession / 세션 1 배정
3:26:44  RemoteFX guest mode, AVC available: 1, Initial profile: 8
3:26:46  DisconnectNotify → The disconnect reason is 4399   ← 4399 = 0x112F
```

원인은 **RDP 하드웨어 AVC(H.264) 인코딩**이다. 이 서버에는 NVIDIA GPU 가 있고
정책이 하드웨어 인코딩을 강제하고 있었는데(`AVCHardwareEncodePreferred=1`,
`AVC444ModePreferred=1`), 같은 GPU 를 LDPlayer 인스턴스들이 OpenGL 로 점유한다.
재접속 순간 RDP 가 하드웨어 인코더를 잡지 못하면 프로토콜 오류로 끊는다.

소프트웨어 인코딩으로 내리면 경합이 사라진다(화질 약간 하락, CPU 소폭 증가):

```powershell
$p='HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services'
Set-ItemProperty $p AVCHardwareEncodePreferred 0 -Type DWord
Set-ItemProperty $p AVC444ModePreferred        0 -Type DWord
Restart-Service TermService -Force
```

`Restart-Service TermService` 는 **로그오프가 아니다.** 세션 1 은 살아 있고 함대도
앱도 죽지 않는다(실측: 재시작 후 LD 11 프로세스·pythonw 2 그대로). 되돌리려면 두
값을 `1` 로 다시 넣는다.

진단할 때 헷갈리는 것들:

- **`3389` 가 막혀 있는 것은 정상이다.** 이 서버의 RDP 는 `1098` 이다(5-1 참고).
  기본 포트로 붙으면 접속 자체가 안 되고, 그건 0x112f 가 아니다.
- **로그의 로그인 실패는 대부분 봇이다.** 같은 시각 `112.170.79.190` 이 5분마다
  없는 계정명(BEST/MICHAEL/GEMINI/...)으로, `82.145.229.50` 이 ADMINISTRATOR
  비밀번호로 두드리고 있었다. 4625 의 `SubStatus` 로 가른다 —
  `0xc0000064` = 없는 계정명, `0xc000006a` = 비밀번호 틀림.
- **내 접속인지 가르는 법**: 이벤트 104 `Client timezone is [9] hour from UTC` 가
  한국 클라이언트다. 그리고 `disconnect reason 4399` 가 찍힌 연결이 0x112f 를 본
  바로 그 연결이다.

알려진 공격 IP 는 이름 붙은 규칙 하나로 막아 둔다. 형 IP 만 화이트리스트로 조이면
유동 IP 일 때 본인이 잠기므로, KVM 콘솔 접근을 확인하기 전에는 이 방향으로 간다:

```powershell
New-NetFirewallRule -DisplayName karrot-block-bruteforce -Direction Inbound `
  -Action Block -RemoteAddress 112.170.79.190,82.145.229.50 -Profile Any
```

## 5-4. 코드 갱신 (update.ps1)

서버에는 git 이 없다 — ZIP 설치라 `git pull` 이 없고, 로컬에서 푸시해도 서버는
그대로다. `update.ps1` 이 앱 정지 → 최신 ZIP → `install.ps1` → 앱 재기동을 한다.
LDPlayer 함대는 건드리지 않으므로 순차 기동을 다시 기다릴 필요가 없다.

```powershell
# 최신인지만 확인 (아무것도 안 바꾼다)
iwr https://raw.githubusercontent.com/cococooklove/karrot-luxury-monitor/master/delivery/integrated/manual_gui/update.ps1 -OutFile $env:TEMP\upd.ps1
& $env:TEMP\upd.ps1 -Check

# 갱신
& $env:TEMP\upd.ps1
```

- 설정·자격증명 보존은 `install.ps1` 의 `$keep` 이 담당한다(2단계 백업/복원).
- 배포 각인은 `data\deployed.json` — `install.ps1` 이 매 설치마다 커밋 SHA 를 적는다.
  `-Check` 는 이 파일과 GitHub `master` SHA 를 비교한다. 각인이 없으면 이 스크립트
  이전에 설치된 판이라 비교가 안 되고, 한 번 갱신하면 이후로는 비교된다.
- `update.ps1` 은 ZIP 안의 `install.ps1` 을 부른다. `raw.githubusercontent` 는 CDN
  캐시가 있어 푸시 직후 옛 스크립트를 내주지만 codeload ZIP 은 요청 시 생성된다.
  (위 `iwr` 로 받는 `update.ps1` 자체는 캐시를 탈 수 있다 — 몇 분 기다리거나
  `?nocache=1` 을 붙인다.)
- `--watchdog` 이 앱을 되살리므로 정지는 재시도 루프로 한다. 그래도 안 죽으면
  중단하고 살아 있는 PID 를 찍는다 — 폴더가 잠긴 채 반쯤 지워지는 것보다 낫다.

## 6. 테스트 순서
1. `python main.py --headless --once` → 유효계정 수·매칭 확인
2. 키워드 등록(계정당 최대 30개): 코드 `MultiAccountAlerts.register_all(LUXURY_BRANDS)` or GUI 1회
3. 텔레그램 수신 확인
4. 서버 재부팅 1회 → RDP 접속 → `powershell -ExecutionPolicy Bypass -File C:\karrot\ldboot.ps1`
   → `C:\karrot\ldboot.log` 에 `최종 adb devices=6 / 5` 와 `모니터 앱 시작` 확인
   (RDP 없이 부팅만 하면 `!! RDP 세션이 없습니다` 가 찍히고 함대는 안 뜬다 — 위 제약 참고)

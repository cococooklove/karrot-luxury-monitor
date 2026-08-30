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
| 작업 `karrotgui` | `pythonw main.py` (작업 폴더 = 앱 폴더), **트리거 없음** | `ldboot.ps1` 이 마지막에 `schtasks /run /tn karrotgui` 로 호출 |

왜 이 모양인가:

- **shim 이 필요한 이유** — 자동실행 진입점은 `C:\karrot\ldboot.ps1` 로 고정인데 재설치는
  `C:\karrot` 을 통째로 갈아끼운다. 실제 파일을 거기 두면 재설치 한 번에 사라지고,
  부팅해도 함대도 앱도 안 뜬다(운영 서버에서 실제로 이렇게 깨져 있었다).
- **SYSTEM 으로 돌리면 안 되는 이유** — LDPlayer 는 사용자 세션이 있어야 게스트를 띄운다.
  `ldboot.ps1` 이 루프백 RDP 로 세션을 승격시키는 것도 로그온 사용자 권한이 필요하다.
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

## 6. 테스트 순서
1. `python main.py --headless --once` → 유효계정 수·매칭 확인
2. 키워드 등록(계정당 최대 30개): 코드 `MultiAccountAlerts.register_all(LUXURY_BRANDS)` or GUI 1회
3. 텔레그램 수신 확인
4. 서버 재부팅 1회 → `C:\karrot\ldboot.log` 에 `최종 adb devices=5 / 5` 와 `모니터 앱 시작` 확인

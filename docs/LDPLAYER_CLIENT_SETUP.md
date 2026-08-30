# LDPlayer 무인 토큰·모니터 셋업 (클라 Windows, 폰 불필요)

폰 없이 LDPlayer(기본 루팅)만으로 다계정 토큰 자동갱신 + 명품 매물 모니터링.
갱신은 각 인스턴스의 정품 당근앱이 스스로 처리(WAF 통과) → `ld_harvest.py` 가 수확만.

## 원리
- LDPlayer = 루팅된 안드로이드. `su` 로 앱 데이터 직접 접근 → 재패키징·이식 불필요.
- `.ldbk` = LDPlayer 백업 → LD에 **네이티브 복원**하면 그 계정 그대로 로그인(device_id 일치).
- **인스턴스 1개 = 계정 1개 = 병렬.** 5계정 = LD 5인스턴스 동시.
- access(30분)만 앱이 갱신. `ld_harvest.py` 가 25분마다 회전토큰 수확 → `accounts.json`.
- 검색(search-bff)은 `accounts.json` access 로 Mac/PC서 헤드리스 호출 — 앱 무관.

## 준비물 (클라 Windows)
- LDPlayer9 설치
- Python 3.9+ (`py --version`)
- 리포 복사 (tools/, collector/, data/capture.jsonl 포함)
- `pip install` 필요시 requirements.txt

## 1. .ldbk 복원 (인스턴스별)
LDPlayer 다중관리자에서 인스턴스 N개 생성 → 각각에 `.ldbk` 복원:
- LDPlayer 다중관리자 > 가져오기, 또는 백업/복원 메뉴로 `6-0822.ldbk` … 개별 복원
- 각 인스턴스 부팅 → 당근앱 실행 → **로그인 상태 확인**(홈 뜨면 OK)
- 5개 .ldbk = 인스턴스 5개 (계정 6,7,9,11,13 그룹)

## 2. adb 포트 확인
> LDPlayer 설치 경로는 서버마다 다르다(예: 현행 운영 서버는 `D:\LDPlayer\LDPlayer9`).
> 아래 명령의 경로는 실제 설치 위치로 바꿔 쓸 것. 코드(`ld_autoharvest`)는
> C:\LDPlayer, D:\LDPlayer, C:\Program Files(x86)\LDPlayer 등을 자동탐색한다.

LDPlayer adb.exe 경로: `C:\LDPlayer\LDPlayer9\adb.exe`
```
"C:\LDPlayer\LDPlayer9\adb.exe" devices
```
인스턴스별 주소 나옴: `127.0.0.1:5555`, `127.0.0.1:5557`, `127.0.0.1:5559` … (보통 +2씩).
안 뜨면 각 인스턴스에서 `adb connect 127.0.0.1:<포트>` (LDPlayer 설정 > 네트워크/디버그).

## 3. su 접근 확인 (인스턴스당)
```
"C:\LDPlayer\LDPlayer9\adb.exe" -s 127.0.0.1:5555 exec-out su -c "ls /data/data/com.towneers.www/files/datastore/"
```
`karrot_token.ds` 보이면 OK. `su: not found` 면 LD 설정 > **ROOT 권한 ON**.

## 4. 토큰 수확 시작 (다계정 병렬)
```
py tools\ld_harvest.py ^
   --adb "C:\LDPlayer\LDPlayer9\adb.exe" ^
   --serials 127.0.0.1:5555 127.0.0.1:5557 127.0.0.1:5559 127.0.0.1:5561 127.0.0.1:5563 ^
   --interval 1500
```
- 매 25분: 각 인스턴스 앱 nudge(갱신유발) → karrot_token.ds 수확 → `accounts.json` 병합.
- 인스턴스별 `code · access Nm 남음` 출력. `--once` 로 1회 테스트.
- `--auto` 로 `adb devices` 자동수집(포트 나열 대신).

## 5. 모니터 실행 (검색 자동화)
`accounts.json` 채워지면 헤드리스 검색:
```
py tools\unattended.py ^
   --adb "C:\LDPlayer\LDPlayer9\adb.exe" ^
   --serial 127.0.0.1:5555 ^
   --path /api/v5/integrate/search ^
   --regions <동네id> [<동네id> …] ^
   --interval 300
```
- `monitor.py` 가 `accounts.json` 의 최신 access 로 검색 → 새 매물 diff → 알림.
- `data/capture.jsonl` 에 `/api/v5/integrate/search` 템플릿 있어야 함(리포에 포함).
- 검색 키워드/필터는 `--path` 파라미터/캡처 템플릿에서 지정(명품 브랜드 등).

> unattended.py 자체 harvest_loop 도 있음(단일 인스턴스). **다계정은 ld_harvest.py 로 수확**,
> unattended.py 는 `--no-monitor` 없이 monitor 만 쓰거나, harvest 충돌 피하려면
> `--harvest-interval` 크게(예 999999) 두고 ld_harvest 에 수확 일임.

## 6. 정상운영
- LD 인스턴스 N개 상시 켜둠 → 앱들이 각자 갱신.
- `ld_harvest.py` 상시 → accounts.json 신선 유지.
- `unattended.py`(monitor) 상시 → 매물 감지.
- 밴분산: `accounts.json` 각 계정에 `proxy` 지정(인스턴스별 고정 프록시), 일일상한.

## 폰 경로와 차이 (참고)
Mac+실폰서 이미 **방법 검증 완료**(2026-08-27): 재패키징 debuggable + .ldbk 앱데이터 이식(tsk) →
로그인복원 → 앱 자동갱신(WAF통과) → 수확. LD는 루팅+네이티브복원이라 그 삽질 없이 동일 결과.
관련 툴: `repackage_karrot.sh` `extract_appdata_tsk.sh` `push_appdata.sh` `harvest_tokens.sh`(폰용).

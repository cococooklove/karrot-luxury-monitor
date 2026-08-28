# 클라 배포 패키지 — 당근 명품 모니터 (exe)

클라는 **더블클릭 → 자동 시작**만. 아래 설정은 **네(운영자)가 배포 전에** 채운다.

## 패키지 구성 (클라에게 주는 것)
```
KarrotMonitor.exe        ← GitHub Actions 아티팩트
settings.txt             ← 프록시/속도 (네가 채움)
notify.json              ← 텔레그램 알림 (네가 채움)
conditions.xlsx          ← 검색 조건(명품 키워드/지역/가격) (네가 채움, 선택)
```
+ 클라 PC에 **LDPlayer + .ldbk 복원**(계정 로그인 상태). exe 가 LDPlayer 감지→토큰 자동수확.

## 네가 배포 전 채울 값

### 1. settings.txt (프록시 + 속도)
```
1000          ← 1줄: 요청 최소간격(ms)
16            ← 2줄: 동시 요청수
http://user:pass@host1:port    ← 3줄~: 프록시 (밴분산, 한 줄에 하나)
http://user:pass@host2:port
```
(프록시 없으면 3줄부터 비움. 계정별 프록시는 앱 '계정+프록시 추가'서 accounts.json 에도 가능)

### 2. notify.json (텔레그램)
```json
{"tg_token": "<봇토큰>", "tg_chat": "<채팅ID>", "sheet_url": "", "sheet_cred": ""}
```
봇토큰 = @BotFather, 채팅ID = 봇에게 메시지 후 getUpdates. (구글시트 쓰면 sheet_url/cred)

### 3. 검색 조건 (명품 키워드/지역/가격)
GUI '자동' 탭서 직접 입력하거나 conditions.xlsx 로 다중조건:
- 키워드(예: 샤넬, 루이비통), 추가/제외어, 최소~최대 가격, 끌올 n일
- 지역: 전국(동단위) 또는 선택 동네
- 명품 브랜드 사전은 `daangn_ext`/`parse_luxury` 에 내장 — 키워드만 지정하면 필터됨

## 클라 사용 (제로 설정 — 프로그램만 실행)
1. `KarrotMonitor.exe` 더블클릭
2. '자동' 탭 → '자동 모니터 시작'
   - **LDPlayer 자동 부팅** (ldconsole 로 인스턴스 기동 — 클라가 LDPlayer 안 켜도 됨)
   - '토큰 갱신' 기본 체크됨 → LDPlayer서 access 자동수확(WAF 우회)
   - 신규 명품 매물 → 결과 테이블 + 텔레그램 알림
3. 끝. 계속 켜두면 무인.

> 운영자 1회 사전준비(클라 PC): LDPlayer 설치 + .ldbk 로 인스턴스 복원(계정 로그인).
> 이후 클라는 exe 만 실행 — LDPlayer 를 직접 열 필요 없음(exe 가 부팅).

## 키워드 알림 탭 (무인 운영 핵심)
토큰만으로 명품 신규매물 실시간 수신 — 앱/LDPlayer 상시 켜둘 필요 없음.

- **실시간 헬스줄**: 토큰(유효N·임박만료) / 자동수확(다음) / 자동폴링(주기·마지막·신규) / 텔레그램·시트 — 한 눈에.
- **커버 모드**: `전국 풀커버`(모든 계정) ↔ `핵심지역 집중`(명품 밀집동네 계정만, 20~30계정으로 거래량 대부분). 등록·폴링·집계 전부 반영.
- **자동 폴링 + 실행 시 자동 시작**: 앱 켜면 무인 감시. `야간 감속`(새벽 주기 자동 완화, 밴회피).
- **매칭 테이블**: 썸네일(매물 사진) · 더블클릭 매물열기 · 계정 컬럼. 재시작해도 중복알림 안 감(seen 영속).
- **계정 현황 패널**: 계정별 동네·토큰만료·핵심여부·폴링실패·점검필요. `핵심지역 편집`·`상태 초기화`.
- **알림**: 텔레그램(실시간) + 구글시트(검색가능 히스토리) 병행. `텔레그램 테스트` 버튼으로 사전 검증.
- **토큰 자동수확**: 20분 주기 백그라운드. 만료임박만 nudge(효율). 루팅=su / 디버그앱=run-as. 100계정 병렬.

## 24시간 무인 지속 (껐다켜도 유지)
**영속(파일 저장 — 재시작해도 유지):** 키워드(당근 서버), 토큰(accounts.json), 자동시작/커버모드/야간/부팅 설정, 본매물 중복방지(match_seen), 계정상태, 핵심지역.

**재부팅해도 감시 지속하려면 체크 2개:**
1. `실행 시 자동 폴링` — 앱 켜지면 8초 후 자동 감시 재개
2. `PC 부팅 시 자동실행` — Windows 시작 시 앱 자동실행(레지스트리 Run)
→ 둘 다 켜면 **재부팅 = 자동으로 감시 복귀**. seen 영속이라 중복 알림 없음.

**앱을 닫으면 감시는 멈춤**(프로세스라 당연). 위 2개로 부팅 자동복귀. 최고 견고성은 작업 스케줄러 "실패 시 재시작"(선택, 크래시 복구).

## 동작 원리 (요약)
- 토큰: LDPlayer 정품앱이 스스로 갱신 → exe 가 su 로 karrot_token.ds 수확 → accounts.json.
  (PC 직접 refresh 는 WAF 403 이라 온디바이스 수확이 유일. `ld_autoharvest.py`)
- 검색: search-bff(피닝/WAF 없음) 를 수확한 access 로 호출 → parse_luxury 명품 필터.
- 밴회피: 프록시 로테이션, 레인 병렬, AIMD 스로틀, daily_cap/warmup, 차단분류 (기존 daangn_ext 스택).
- 알림: 신규/가격변동 → 텔레그램 + (선택)구글시트. sqlite 중복제거.

## 빌드 (네가, GitHub Actions)
Actions 탭 > build-exe > Run workflow → 완료 후 Artifacts 에서 KarrotMonitor 다운로드.
로컬 Windows 빌드: `manual_gui/` 에서
`pip install -e . pyinstaller && pyinstaller --onefile --windowed --name KarrotMonitor --icon assets/icon.ico --add-data "assets:assets" --collect-all curl_cffi --collect-all PyQt6 --collect-submodules daangn --collect-submodules daangn_ext --hidden-import ld_autoharvest main.py`

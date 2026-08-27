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

## 클라 사용 (제로 설정)
1. LDPlayer 켜기 (.ldbk 복원된 계정들, 로그인 상태)
2. `KarrotMonitor.exe` 더블클릭
3. '자동' 탭 → '자동 모니터 시작'
   - '토큰 갱신' 기본 체크됨 → LDPlayer서 access 자동수확(WAF 우회)
   - 신규 명품 매물 → 결과 테이블 + 텔레그램 알림
4. 끝. 계속 켜두면 무인.

## 동작 원리 (요약)
- 토큰: LDPlayer 정품앱이 스스로 갱신 → exe 가 su 로 karrot_token.ds 수확 → accounts.json.
  (PC 직접 refresh 는 WAF 403 이라 온디바이스 수확이 유일. `ld_autoharvest.py`)
- 검색: search-bff(피닝/WAF 없음) 를 수확한 access 로 호출 → parse_luxury 명품 필터.
- 밴회피: 프록시 로테이션, 레인 병렬, AIMD 스로틀, daily_cap/warmup, 차단분류 (기존 daangn_ext 스택).
- 알림: 신규/가격변동 → 텔레그램 + (선택)구글시트. sqlite 중복제거.

## 빌드 (네가, GitHub Actions)
Actions 탭 > build-exe > Run workflow → 완료 후 Artifacts 에서 KarrotMonitor 다운로드.
로컬 Windows 빌드: `manual_gui/` 에서
`pip install -e . pyinstaller && pyinstaller --onefile --windowed --name KarrotMonitor --collect-all curl_cffi --collect-all PyQt6 --collect-submodules daangn --collect-submodules daangn_ext --hidden-import ld_autoharvest main.py`

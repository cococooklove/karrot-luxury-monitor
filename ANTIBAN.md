# 밴 회피 런북 — 클라 방식(LD 백업복원 + 토큰) 유지하며 정지 방지

증상: `.ldbk` 복원 → 토큰 적용 → 갱신 자동화 → 당근 실행 시 계정 **정지(밴)**.
원인은 403 서명거부가 아니라 **당근 anti-abuse의 자동화/기기 탐지**.
목표: 방식 그대로 두고 밴 벡터만 제거.

## 실측 증거 (정지22-0822.ldbk `leidian.config`)

정지 계정 지문 실측 → 밴은 필연이었음:

| 필드 | 실측값 | 판정 |
|---|---|---|
| `rootMode` | **true** | 루팅 탐지 → 즉시 고위험. **최상위 정지신호** |
| `phoneIMSI` | 460000... (MCC 460=**중국**) | 한국앱+중국SIM 지리모순 |
| `phoneSimSerial` | 898600... (중국이통) | 동일 |
| `phoneModel` | PGT-AN10 (Honor 프리미엄) | 스펙과 모순 ↓ |
| `memorySize` / `resolution` / dpi | **1024MB / 327×576 / 144** | 그 모델이 감자스펙 = **에뮬 확정 시그니처** |
| `networkDNS` static | 8.8.8.8 / false | **프록시 없음** = 전 인스턴스 동일 IP |

→ **주범 = 에뮬탐지(모델↔스펙 모순) + 루팅 + 중국SIM.** IMEI만 랜덤화로는 못 고침.
`randomize_fingerprint.py` 가 스펙일치·KR SIM·유효IMEI 까지 세팅하도록 강화됨.
루팅OFF·프록시는 수동(스크립트 밖).

## 밴 벡터 → 대응 (전부 해야 함, 하나 빠지면 밴)

| # | 벡터 | 대응 | 도구 |
|---|---|---|---|
| 1 | **백업복원=지문복제** (클론끼리 android_id/IMEI/모델 동일 → 연좌밴) | 복원 직후 인스턴스별 지문 재랜덤화 | `tools/randomize_fingerprint.py` |
| 2 | LDPlayer 에뮬 탐지 | ldconsole로 IMEI/모델 실기기값 위조 + (가능시 실기기 혼용) | 위 스크립트 `--ld-index` |
| 3 | 앱밖 HTTP 토큰 refresh (서명 누락) | refresh 금지. 앱 자체갱신 토큰을 매 사이클 **읽기만** | `tools/read_app_token.py` |
| 4 | 데이터센터/공유 IP + 기계적 주기 | 워커별 주거·모바일 프록시(1워커=1IP) + 랜덤 지연 + 워밍업 | `collector/pool.py` (proxy) |

## 복원 워크플로우 (클라 절차 + 밴회피 삽입)

```
클라 기존:  멀티매니저 → 인스턴스 추가 → 종료 → 점3개 → 백업/복원 → 복원 → 파일 불러오기 (코드 z)
                                              │
                          ┌───────────────────┘ ← 여기서 당근 앱 실행 전 아래 삽입
```

복원 후, **당근 앱 최초 실행/로그인 전에** 인스턴스마다:

```bash
# 1) 고유 지문 부여 (원인 #1,#2). seed 는 계정명 등 인스턴스별 고유값
python tools/randomize_fingerprint.py --serial emulator-5554 --ld-index 0 --seed acc1
# 2) 인스턴스 재부팅 1회 (지문 반영)
# 3) 프록시 설정 (LD 설정 or 프록시앱) — 워커별 다른 주거 IP
# 4) 당근 앱 실행 → 로그인 → 백그라운드로 앱이 토큰 자체 갱신하게 둠
```

> ⚠️ **같은 .ldbk 를 여러 인스턴스에 복원해 그대로 쓰면 100% 연좌밴.**
> 복원은 되지만 지문 재랜덤화(1단계)는 인스턴스마다 반드시.

## 토큰 운용 (원인 #3)

HTTP refresh 자동화를 **읽기 자동화로 교체**:

```bash
# 저장 키 1회 탐색
python tools/read_app_token.py --serial emulator-5554 --dump
# 확정된 키로 매 사이클 최신 토큰 획득 → pool 헤더 갱신
python tools/read_app_token.py --serial emulator-5554 --key <auth_key>
```

앱만 켜두면 토큰은 앱이 알아서 갱신. 우리는 항상 유효한 값을 읽어 씀 → 서명/device 일관성 유지.

## 계정 구성 (`data/accounts.json`) — 1계정 : 1인스턴스 : 1IP : 1지문

```json
[
  {"name":"acc1","serial":"emulator-5554","ld_index":0,
   "proxy":"http://user:pass@resi1:port","daily_cap":250,"min_gap":3.0},
  {"name":"acc2","serial":"emulator-5556","ld_index":1,
   "proxy":"http://user:pass@resi2:port","daily_cap":250,"min_gap":3.0}
]
```

`pool.py` 가: 계정별 일상한, 요청간 쿨다운, 403/429 시 지수격리+타워커 라우팅 강제.

## 케이던스 (원인 #4)

- **워밍업**: 신규/복원 계정은 첫 1~2일 하루 수십건만. 바로 대량 = 밴.
- **일 상한**: 계정당 200~300건. `daily_cap` 로 강제.
- **지연**: 요청간 `min_gap`(3s)+지터. `pool.py` 기본 적용.
- **증분 우선**: 1회 풀수집 후 25분 폴링(`monitor.py`) → 저volume = 저밴.

## 확정 필요 (실기기 1대에서, 당근에 안 넣고)

```bash
# 클론끼리 이 값이 같으면 원인 #1 확정
adb -s <serial> shell settings get secure android_id
adb -s <serial> shell getprop | grep -Ei "serialno|model|fingerprint"
```

같으면 지문 재랜덤화가 최우선. 다르면 원인 #3/#4로 무게 이동.

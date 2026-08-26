# 토큰 갱신 캡처 — 무인 자동 모니터링의 마지막 관문

## 왜 이게 필요한가

앱 API 검색은 **토큰만 유효하면 기기 없이 무제한** 호출된다 (`search-bff` 피닝 없음, 서명 없음).
문제는 access 토큰 수명이 **30분**이라는 것. 무인 운영하려면 만료 전에 자동 갱신해야 한다.

- access 토큰(30분) — 검색에 쓰는 것. 짧게 죽는다.
- **refresh 토큰(수일~수주)** — access 를 재발급받는 것. 이걸로 자동 갱신한다.

**refresh → access 교환 요청**을 딱 한 번 캡처하면, 그 형식을 `token_manager.py` 에 넣고
refresh 토큰 N개를 `accounts.json` 에 등록 → 이후 완전 무인.

## 왜 일반 캡처로는 안 되나

교환 요청이 일어나는 `api.kr.karrotmarket.com` 만 **인증서 피닝**이 걸려 있다.
(2026-08-27 실측: 이 호스트만 TLS handshake 거부, `search-bff`·`webapp` 은 정상 통과.)
→ Frida 로 이 호스트의 피닝만 우회하면 캡처된다.

## 이번엔 쉽다 — 서명 우회 불필요

앱 요청에 **서명/HMAC 헤더가 없음**을 이미 확인했다(검색 요청 헤더 분석).
따라서 `capture/frida/sign_hook.js` 는 **안 쓴다.** `ssl_unpin.js`(피닝 우회)만 있으면 된다.

## 준비물

- **안드로이드 기기 또는 에뮬레이터** (iOS 는 탈옥 필요 → 안드로이드 권장)
  - 실기기: USB 디버깅 ON, 루팅
  - 에뮬레이터: LDPlayer(Windows) / Android Studio AVD(Mac). 당근 무결성 검사 때문에
    **Magisk + PlayIntegrityFix** 필요할 수 있음(로그인 실패하면 이것)
- PC: `mitmproxy`, `frida-tools`, `adb`
- 당근 계정 로그인된 앱 (패키지 `kr.co.towneers.www`)

```bash
pip install frida-tools
# 기기에 frida-server 설치 (아키텍처 맞는 것)
#   https://github.com/frida/frida/releases  →  frida-server-*-android-arm64
adb push frida-server /data/local/tmp/ && adb shell "chmod 755 /data/local/tmp/frida-server"
adb shell "su -c /data/local/tmp/frida-server &"
```

## 절차

### 1. mitmproxy + 기기 프록시
`SETUP_LDPLAYER.md` 3단계까지 (프록시 + 루트 인증서 시스템 설치).
```bash
mitmdump -s capture/karrot_dump.py --listen-port 8080
```

### 2. 피닝 우회 상태로 앱 실행
```bash
frida -U -f kr.co.towneers.www -l capture/frida/ssl_unpin.js
```
콘솔에 `[unpin] active` 뜨면 성공. `api.kr.karrotmarket.com` TLS 실패가 사라진다.
> 만약 여전히 실패하면 커스텀 피닝 → 콘솔 로그 보고 `ssl_unpin.js` 에 대상 클래스 추가.

### 3. 토큰 갱신 유발
액세스 토큰이 살아있으면 갱신이 안 일어난다. **강제로 만료 상황**을 만든다:
- 앱을 완전 종료 후 **30분 이상** 지난 뒤 재실행, 또는
- 기기 시간을 40분 앞으로 → 앱 재실행 → 원복

앱이 자동으로 `api.kr.karrotmarket.com` 에 갱신 요청을 보낸다.

### 4. 교환 요청 확인
```bash
python tools/find_refresh.py     # (아래 신규 스크립트) capture.jsonl 에서 교환 요청 추출
```
`grant_type=refresh_token` 또는 refresh 토큰이 body/헤더에 실린 POST 를 찾는다.

### 5. token_manager 에 반영
찾은 요청의 URL·body·응답키를 `collector/token_manager.py` 의
`REFRESH_URL` 과 `_default_refresh()` 에 채운다. (자리표시자 이미 있음.)

## 캡처 후 = 기기 영구 불필요

1. refresh 토큰 N개 확보 → `data/accounts.json`
2. `TokenManager` 가 access 만료 임박 시 자동 재발급
3. 자동 모니터가 각 계정 토큰으로 검색 → 완전 무인

> refresh 토큰도 언젠가 만료된다(수주 추정). 그때만 재로그인. access 30분과는 차원이 다르다.

## 리스크

- 토큰 = 계정. 제재는 IP 가 아니라 **계정**에 걸린다 → 다계정 + 계정별 프록시 고정(`accounts.json` 에 이미 구조 있음), 일일 상한(`daily_cap`), 워밍업(`warmup_days`).
- 앱 업데이트로 피닝/인증 방식이 바뀌면 재캡처. 단 검색 API 가 바뀌는 건 아니므로 빈도는 낮다.

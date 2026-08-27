# LD플레이어 캡처 환경 세팅 (정확한 단계)

목표: 당근 앱 실제 트래픽을 mitmproxy 로 잡아 `data/capture.jsonl` 생성.
당근 패키지명: `com.towneers.www`

## 1. mitmproxy 실행 (PC)
```bash
pip install -r requirements.txt
mitmdump -s capture/karrot_dump.py --listen-port 8080
```
PC 로컬 IP 확인: `ipconfig` (Windows) / `ifconfig` (mac). 예 `192.168.0.10`.

## 2. LD플레이어 프록시 설정
LD플레이어는 안드로이드 = Wi-Fi 프록시로 지정.
- LD 설정 > 네트워크, 또는 안드로이드 설정 > Wi-Fi > 연결된 AP 길게 > 수정 > 고급 > 프록시 수동
- 호스트 `192.168.0.10`, 포트 `8080`

## 3. mitm 루트 인증서 설치 (핵심 — 시스템 저장소)
Android 7+ 는 사용자 인증서로는 앱 트래픽 못 잡음 → **시스템 저장소**에 넣어야 함.
LD플레이어는 root 기본 제공(설정에서 ON).

방법 A (adb push, 권장):
```bash
# mitm 인증서를 안드로이드 형식으로 변환
openssl x509 -inform PEM -subject_hash_old -in ~/.mitmproxy/mitmproxy-ca-cert.pem | head -1
# 위 출력 해시값(예: c8750f0d) 로 파일명 생성
hashval=$(openssl x509 -inform PEM -subject_hash_old -in ~/.mitmproxy/mitmproxy-ca-cert.pem | head -1)
cp ~/.mitmproxy/mitmproxy-ca-cert.pem ${hashval}.0

adb connect 127.0.0.1:5555      # LD플레이어 adb 포트 (LD 멀티면 5556,5557...)
adb root && adb remount
adb push ${hashval}.0 /system/etc/security/cacerts/
adb shell chmod 644 /system/etc/security/cacerts/${hashval}.0
adb reboot
```
방법 B: 브라우저로 `http://mitm.it` 접속 → Android 인증서 받기 → 설정에서 CA 설치
(사용자 저장소만 되면 A 로 시스템 승격 필요).

## 4. 검증
LD 브라우저로 아무 https 접속 → mitmdump 콘솔에 흐름 뜨면 OK.

## 5. cert pinning 우회 (당근이 핀닝하면 3단계 후에도 앱 트래픽 안 잡힘)
frida-server 를 에뮬에 올려야 함:
```bash
# 아키텍처 확인 (LD는 보통 x86_64 또는 arm)
adb shell getprop ro.product.cpu.abi
# frida-server 다운로드(버전=PC frida 버전 일치) → push
adb push frida-server /data/local/tmp/
adb shell "chmod 755 /data/local/tmp/frida-server"
adb shell "/data/local/tmp/frida-server &"
```
PC 에서:
```bash
frida-ps -U | grep -i daangn        # 앱 뜨는지 확인
frida -U -f com.towneers.www -l capture/frida/ssl_unpin.js
```
`[unpin] active` 뜬 상태로 앱 사용 → 트래픽 잡힘.

## 6. 캡처
앱에서 **중고거래 매물 목록 조회 (같은 지역 2~3회)** → `data/capture.jsonl` 축적.
```bash
python tools/analyze_capture.py     # 차단 원인 자동 리포트
```

## 무결성 이슈면 (에뮬 로그인 자체 실패)
- Magisk + PlayIntegrityFix 모듈, 또는 실기기 사용.
- LD플레이어 무결성 통과 어려우면 실기기 + USB adb 가 가장 확실.

## 트러블
| 증상 | 원인 | 해결 |
|---|---|---|
| 흐름 안 잡힘 | 프록시 미적용 | Wi-Fi 프록시 재확인 |
| https 만 안 잡힘 | 인증서 사용자저장소만 | 3단계 방법 A |
| 앱만 안 잡힘 | cert pinning | 5단계 frida unpin |
| 로그인 실패 | 무결성 차단 | 실기기/PlayIntegrityFix |

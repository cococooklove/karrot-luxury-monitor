"""
인스턴스별 기기 지문 재랜덤화 — 밴 원인 #1(클론 연좌밴) 차단.

.ldbk 백업을 여러 인스턴스에 복원하면 android_id·시리얼·모델이 전부 동일 →
당근이 '한 기기 = N계정' 으로 연좌 밴. 복원 직후 이 스크립트로 인스턴스마다
고유 지문을 심는다. 반드시 당근 앱 첫 실행/로그인 전에 실행.

두 계층:
  [adb]        android_id, 일부 build.prop (셸 권한 범위)
  [ldconsole]  IMEI/IMSI/모델/제조사/번호/MAC/SIM (LDPlayer 정식 API, Windows)
               → LD가 실제로 하위 레이어까지 위조해줘 에뮬탐지 회피에 필수.

용법:
  python tools/randomize_fingerprint.py --serial emulator-5554 --ld-index 0
  # ldconsole 경로 자동탐색 실패 시:  --ldconsole "C:\\LDPlayer\\LDPlayer9\\ldconsole.exe"

주의: 실행 후 인스턴스 재부팅 1회 권장(지문 반영). 프록시는 별도 설정.
"""
import argparse
import hashlib
import os
import shutil
import subprocess

# 실기기 프로필 — 모델과 스펙(해상도/dpi/RAM)이 **일치**해야 함.
# 정지 원인 = 모델은 프리미엄인데 1GB/327x576/144dpi = 불가능조합 → 에뮬탐지.
# w,h,dpi,ram(MB),cpu 를 실기기 실제값과 맞춰 모순 제거.
MODELS = [
    ("samsung", "SM-G991N", "Galaxy S21",        1080, 2400, 421, 6144, 4),
    ("samsung", "SM-A525N", "Galaxy A52",        1080, 2400, 405, 6144, 4),
    ("samsung", "SM-A536N", "Galaxy A53",        1080, 2400, 405, 6144, 4),
    ("samsung", "SM-N981N", "Galaxy Note20",     1080, 2400, 393, 8192, 4),
    ("Xiaomi",  "M2101K6G",  "Redmi Note 10 Pro", 1080, 2400, 395, 6144, 4),
    ("LGE",     "LM-V500N", "V50 ThinQ",         1080, 2340, 403, 6144, 4),
]


def _seeded(seed_str):
    """시리얼 기반 결정적 난수 — 같은 인스턴스는 항상 같은 지문(재실행 안정)."""
    h = hashlib.sha256(seed_str.encode()).hexdigest()
    return h


def _luhn(imei14):
    """IMEI 15번째 체크디짓 계산 — 유효 IMEI 라야 탐지 회피."""
    s = 0
    for i, ch in enumerate(imei14):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        s += d
    return str((10 - s % 10) % 10)


def gen_fingerprint(seed):
    h = _seeded(seed)
    idx = int(h[:2], 16) % len(MODELS)
    manu, model, name, w, ht, dpi, ram, cpu = MODELS[idx]
    android_id = h[2:18]                        # 16 hex
    digits = "".join(c for c in h if c.isdigit())
    # IMEI: 한국 유통 TAC(35xxxx) + 랜덤 + Luhn 체크디짓 = 유효 IMEI
    tac = "35" + (digits[:6] + "000000")[:6]
    body = (digits[6:13] + "0000000")[:7]
    imei14 = (tac + body)[:14]
    imei = imei14 + _luhn(imei14)
    # IMSI: KR MCC/MNC. 45005=SKT. (중국 460 이 정지 주범이었음)
    imsi = "45005" + (digits[13:23] + "0000000000")[:10]
    # ICCID: 8982(KR) prefix
    sim_serial = "8982" + (digits[5:20] + "0" * 16)[:16]
    mac = ":".join(h[18 + i * 2:20 + i * 2] for i in range(6))
    phone = "010" + (digits[5:13] + "00000000")[:8]
    return {
        "manufacturer": manu, "model": model, "name": name,
        "android_id": android_id, "imei": imei, "imsi": imsi,
        "sim_serial": sim_serial, "mac": mac, "phone": phone,
        "width": w, "height": ht, "dpi": dpi, "ram": ram, "cpu": cpu,
    }


def _adb(serial, *args):
    cmd = ["adb", "-s", serial, *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def apply_adb(serial, fp):
    # android_id (Android 8+는 앱별 해시라 앱데이터 초기화 전 실행 필요)
    _adb(serial, "shell", "settings", "put", "secure", "android_id", fp["android_id"])
    print(f"  [adb] android_id ← {fp['android_id']}")


def _find_ldconsole(explicit):
    if explicit and os.path.exists(explicit):
        return explicit
    for p in (
        r"C:\LDPlayer\LDPlayer9\ldconsole.exe",
        r"C:\LDPlayer\LDPlayer64\ldconsole.exe",
        r"C:\Program Files\LDPlayer\LDPlayer9\ldconsole.exe",
    ):
        if os.path.exists(p):
            return p
    return shutil.which("ldconsole")


def apply_ldconsole(ld, index, fp):
    """ldconsole modify — LD 하위레이어까지 위조. Windows 전용.
    지문값 + **스펙 일치**(해상도/dpi/RAM/CPU) 로 에뮬 모순 제거."""
    args = [
        "modify", "--index", str(index),
        "--imei", fp["imei"], "--imsi", fp["imsi"],
        "--simserial", fp["sim_serial"],
        "--androidid", fp["android_id"],
        "--manufacturer", fp["manufacturer"], "--model", fp["model"],
        "--mac", fp["mac"].replace(":", ""),
        "--pnumber", fp["phone"],
        # 모델과 일치하는 실기기 스펙 (327x576/144dpi/1GB 감자스펙 = 정지주범)
        "--resolution", f"{fp['width']},{fp['height']},{fp['dpi']}",
        "--cpu", str(fp["cpu"]),
        "--memory", str(fp["ram"]),
    ]
    r = subprocess.run([ld, *args], capture_output=True, text=True, timeout=30)
    if r.returncode == 0:
        print(f"  [ldconsole] 적용: {fp['manufacturer']} {fp['model']} "
              f"{fp['width']}x{fp['height']}@{fp['dpi']} {fp['ram']}MB/{fp['cpu']}core")
    else:
        print(f"  [ldconsole] 실패: {r.stderr.strip() or r.stdout.strip()}")
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", required=True, help="adb 시리얼 (예 emulator-5554)")
    ap.add_argument("--ld-index", type=int, default=None, help="LDPlayer 인스턴스 인덱스")
    ap.add_argument("--ldconsole", default=None, help="ldconsole.exe 경로")
    ap.add_argument("--seed", default=None, help="지문 시드(기본=serial). 계정명 등 고유값 권장")
    ap.add_argument("--print-only", action="store_true", help="적용 안 하고 지문만 출력")
    args = ap.parse_args()

    seed = args.seed or args.serial
    fp = gen_fingerprint(seed)
    print(f"[fp] seed={seed}")
    for k, v in fp.items():
        print(f"     {k}: {v}")
    if args.print_only:
        return

    ld = _find_ldconsole(args.ldconsole)
    if args.ld_index is not None and ld:
        apply_ldconsole(ld, args.ld_index, fp)   # LD 재부팅 후 반영
    else:
        print("  [ldconsole] 스킵 (Windows/경로/index 없음) — IMEI/모델 위조 누락 주의")
    apply_adb(args.serial, fp)
    print("→ 인스턴스 재부팅 1회 후 당근 앱 최초 실행. 지문 고유성 확보 완료.")
    print("\n⚠️ 스크립트로 못 고치는 정지주범 2개 — 수동 필수:")
    print("  1) rootMode=true → LD설정에서 **루팅 끄기**. towneers 무결성체크가 루팅 탐지 → 정지.")
    print("     (토큰추출은 루팅필요 → 추출만 루팅ON에서 하고, 운영 인스턴스는 루팅OFF 권장)")
    print("  2) DNS 8.8.8.8/프록시없음 → 인스턴스별 **주거·모바일 프록시** 설정. 전 인스턴스 같은IP=연좌.")


if __name__ == "__main__":
    main()

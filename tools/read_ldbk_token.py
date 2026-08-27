"""
.ldbk 안 당근 앱 인증데이터 추출 — 토큰 구조·refresh·엔드포인트 파악용.

.ldbk(7z) 안 디스크이미지(vmdk) 내부 /data/data/com.towneers.www/shared_prefs 등에
access/refresh 토큰·인증 URL 이 평문 저장됨. 디스크를 추출해 바이트 스캔으로 뽑는다.
(계정은 정지됐어도 토큰 '형식/키이름/엔드포인트'는 살아있는 계정과 동일 → 설계에 그대로 사용)

사전:  .venv/bin/python -m pip install py7zr  (이미 설치됨)
용법:  .venv/bin/python tools/read_ldbk_token.py "/Users/younglee/Downloads/정지22-0822.ldbk"

주의: 디스크 이미지가 수 GB일 수 있음 → /tmp 공간·시간 필요. 스캔은 읽기전용.
"""
import os
import re
import subprocess
import sys

try:
    import py7zr
except ImportError:
    sys.exit("py7zr 없음 →  .venv/bin/python -m pip install py7zr")

OUTDIR = "/tmp/ldbk_disk"
DISK_EXT = re.compile(r"\.(vmdk|img|qcow2?|raw|vdi|hds)$", re.I)

# 뽑을 인증 흔적 — 키이름/토큰형/엔드포인트
PATTERNS = [
    # JWT
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}",
    # 토큰/세션 키 이름 (shared_prefs xml)
    r'name="[^"]*(?:access|refresh|auth|token|bearer|session|credential|oauth)[^"]*"',
    # 인증/토큰 엔드포인트 URL
    r'https?://[A-Za-z0-9._-]*(?:towneers|karrotmarket|daangn)[A-Za-z0-9._/-]*'
    r'(?:auth|oauth|token|login|session|refresh|verify|sms|otp)[A-Za-z0-9._/?=&-]*',
    # 그냥 당근 API 호스트 (엔드포인트 목록화)
    r'https?://[A-Za-z0-9._-]*(?:api|auth|gateway|prod)[A-Za-z0-9._-]*'
    r'(?:towneers|karrotmarket|daangn)[A-Za-z0-9._-]*',
]


def list_entries(path):
    with py7zr.SevenZipFile(path, "r") as z:
        info = z.list()
    rows = [(i.filename, i.uncompressed) for i in info]
    print(f"[archive] {len(rows)} 엔트리:")
    for name, size in rows:
        print(f"   {size/1e6:9.1f} MB  {name}")
    return rows


def extract_disks(path, rows):
    disks = [n for n, _ in rows if DISK_EXT.search(n)]
    if not disks:
        # 확장자 없으면 최대 파일을 디스크로 간주
        disks = [max(rows, key=lambda r: r[1])[0]]
        print(f"[disk] 확장자 매칭 없음 → 최대파일 사용: {disks[0]}")
    os.makedirs(OUTDIR, exist_ok=True)
    print(f"[disk] 추출 대상: {disks} → {OUTDIR} (용량·시간 소요)")
    with py7zr.SevenZipFile(path, "r") as z:
        z.extract(path=OUTDIR, targets=disks)
    return [os.path.join(OUTDIR, d) for d in disks]


def scan(disk):
    print(f"\n===== 스캔 {disk} ({os.path.getsize(disk)/1e9:.2f} GB) =====")
    for pat in PATTERNS:
        try:
            # strings 로 ASCII 뽑고 grep — 대용량 스트리밍
            p1 = subprocess.Popen(["strings", "-n", "8", disk], stdout=subprocess.PIPE)
            p2 = subprocess.Popen(["grep", "-aoE", pat], stdin=p1.stdout,
                                  stdout=subprocess.PIPE)
            p1.stdout.close()
            out = p2.communicate(timeout=900)[0].decode("utf-8", "ignore")
        except Exception as e:
            print(f"  스캔 오류: {e}")
            continue
        hits = sorted(set(l for l in out.splitlines() if l.strip()))
        if hits:
            print(f"\n--- 패턴: {pat[:50]}... ({len(hits)} 유니크) ---")
            for h in hits[:40]:
                print(f"   {h[:160]}")


def main():
    if len(sys.argv) < 2:
        sys.exit("사용: read_ldbk_token.py <path.ldbk>")
    path = sys.argv[1]
    rows = list_entries(path)
    disks = extract_disks(path, rows)
    for d in disks:
        scan(d)
    print("\n→ name=\"...token\" 키이름 = shared_prefs 저장키. eyJ.. = 실제 토큰(형식확인용).")
    print("→ auth/oauth/token URL = refresh·로그인 엔드포인트 후보.")


if __name__ == "__main__":
    main()

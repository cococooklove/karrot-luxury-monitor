"""
LD 백업(.ldbk = 7z)에서 인스턴스 기기지문 추출 — 밴 원인 #1/#2 진단.

.ldbk 안의 LDPlayer config(leidianN.config/*.vbox 등)에 IMEI·모델·제조사·번호·
android 관련 값이 평문으로 들어있다. 1.9GB 디스크 통째 안 풀고 작은 config/텍스트
파일만 선별 추출해 지문 키를 덤프한다.

사전:  python3 -m pip install py7zr
용법:  python3 tools/read_ldbk_fingerprint.py "/Users/younglee/Downloads/정지22-0822.ldbk"
"""
import re
import sys

try:
    import py7zr
except ImportError:
    sys.exit("py7zr 없음 →  python3 -m pip install py7zr")

# 지문 관련 키/값 패턴
KEY = re.compile(r"(imei|imsi|phonenumber|pnumber|manufacturer|model|"
                 r"androidid|android_id|serial|mac|deviceid|udid|"
                 r"playername|resolution|cpu)", re.I)
# 작은 텍스트/설정 파일만 (디스크 이미지 vmdk 제외)
TEXT_EXT = re.compile(r"\.(config|vbox|json|xml|ini|txt|prop|cfg)$", re.I)
MAX = 2 * 1024 * 1024   # 2MB 이하만 읽기


def main():
    if len(sys.argv) < 2:
        sys.exit("사용: read_ldbk_fingerprint.py <path.ldbk>")
    path = sys.argv[1]

    with py7zr.SevenZipFile(path, "r") as z:
        names = z.getnames()
        print(f"[archive] 총 {len(names)}개 엔트리")
        # 후보: 텍스트 확장자 or 이름에 config/leidian 포함
        cand = [n for n in names
                if TEXT_EXT.search(n) or re.search(r"config|leidian|vbox|prop", n, re.I)]
        print(f"[archive] config/텍스트 후보 {len(cand)}개:")
        for n in cand:
            print("   ", n)
        if not cand:
            print("→ config 텍스트 없음. 지문은 디스크 이미지 내부일 수 있음(vmdk 마운트 필요).")
            print("  전체 엔트리 상위 30:")
            for n in names[:30]:
                print("   ", n)
            return

        # 후보 파일 추출 (py7zr 1.x: extract(path, targets))
        import os
        outdir = "/tmp/ldbk_cfg"
        os.makedirs(outdir, exist_ok=True)
        z.reset()
        z.extract(path=outdir, targets=cand)

    print("\n===== 지문 스캔 =====")
    for name in cand:
        fpath = os.path.join(outdir, name)
        try:
            raw = open(fpath, "rb").read()
        except Exception:
            continue
        if len(raw) > MAX:
            continue
        text = raw.decode("utf-8", "ignore")
        # config 원본도 통째로 출력 (작음)
        print(f"\n----- {name} (raw) -----\n{text[:4000]}")
        hits = []
        # JSON/ini 스타일 key:value 라인 스캔
        for m in re.finditer(r'["\[]?([A-Za-z0-9_.]+)["\]]?\s*[:=]\s*"?([^",\n\r}]{1,60})', text):
            k, v = m.group(1), m.group(2).strip()
            if KEY.search(k) and v:
                hits.append((k, v))
        if hits:
            print(f"\n[{name}]")
            seen = set()
            for k, v in hits:
                if (k, v) in seen:
                    continue
                seen.add((k, v))
                print(f"   {k} = {v}")
    print("\n→ imei/model/manufacturer/android_id 가 LDPlayer 기본값이면 에뮬탐지(#2).")
    print("→ 다른 인스턴스 .ldbk 와 같은 값이면 클론 연좌밴(#1) 확정.")


if __name__ == "__main__":
    main()

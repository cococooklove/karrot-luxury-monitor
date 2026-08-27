"""
앱 저장소에서 현재 유효 토큰 읽기 — 밴 원인 #3(앱밖 HTTP refresh) 차단.

토큰을 HTTP refresh 로 직접 재발급하면 앱의 동적서명·device 헤더가 빠져
당근이 위험플래그 → 정지. 대신 앱이 자체 갱신한 토큰을 매 사이클 그대로
읽어 쓴다. 앱은 켜두기만 하면 백그라운드로 알아서 refresh 한다.

두 경로:
  [run-as]  비루팅: adb shell run-as <pkg> 로 shared_prefs xml 읽기 (디버그빌드/일부만 가능)
  [su]      루팅/LD: adb shell su -c cat 로 직접 읽기 (LD는 보통 루팅됨 → 이쪽)

토큰 저장 키를 모를 때: --dump 로 shared_prefs 전체를 훑어 토큰형 값 자동탐지.

용법:
  python tools/read_app_token.py --serial emulator-5554 --dump          # 키 탐색
  python tools/read_app_token.py --serial emulator-5554 --key auth_token # 특정 키 → stdout
  # pool 연동: 워커가 요청 전 이걸 호출해 최신 토큰으로 헤더 갱신
"""
import argparse
import re
import subprocess

PKG = "com.towneers.www"
PREFS_DIR = "/data/data/{pkg}/shared_prefs"
# 토큰형 값: 긴 JWT(eyJ...) 또는 고엔트로피 32+ 문자열
TOKENISH = re.compile(r'(eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}'
                      r'|[A-Za-z0-9_\-]{32,})')
KEYHINT = re.compile(r'(token|auth|access|bearer|jwt|credential|session)', re.I)


def _adb(serial, *args):
    return subprocess.run(["adb", "-s", serial, *args],
                          capture_output=True, text=True, timeout=30)


def _shell(serial, cmd):
    """su 우선, 실패 시 run-as 폴백."""
    r = _adb(serial, "shell", f"su -c '{cmd}'")
    if r.returncode == 0 and r.stdout and "not found" not in r.stdout.lower():
        return r.stdout
    # run-as 폴백 (cmd 안의 절대경로를 pkg 상대로 못 바꾸므로 run-as는 별도 처리 필요)
    return r.stdout or r.stderr


def list_prefs(serial):
    out = _shell(serial, f"ls {PREFS_DIR.format(pkg=PKG)}")
    return [f.strip() for f in out.split() if f.strip().endswith(".xml")]


def read_prefs(serial, fname):
    path = f"{PREFS_DIR.format(pkg=PKG)}/{fname}"
    return _shell(serial, f"cat {path}")


def dump(serial):
    """모든 shared_prefs 훑어 토큰형 (key,value) 후보 출력."""
    files = list_prefs(serial)
    if not files:
        print("prefs 없음 — 루팅/경로 확인. (LD는 보통 su 됨)")
        return
    hits = []
    for f in files:
        xml = read_prefs(serial, f)
        for m in re.finditer(r'name="([^"]+)">([^<]+)<', xml):
            key, val = m.group(1), m.group(2)
            if (KEYHINT.search(key) or TOKENISH.fullmatch(val)) and len(val) >= 20:
                hits.append((f, key, val))
    if not hits:
        print("토큰형 값 못 찾음 — 앱 로그인 상태 확인, 또는 DB(databases/) 저장일 수 있음.")
    for f, key, val in hits:
        print(f"[{f}] {key} = {val[:50]}{'...' if len(val) > 50 else ''}")


def read_token(serial, key, fname=None):
    """특정 키의 값 반환. fname 미지정 시 전체에서 첫 매치."""
    files = [fname] if fname else list_prefs(serial)
    for f in files:
        xml = read_prefs(serial, f)
        m = re.search(rf'name="{re.escape(key)}">([^<]+)<', xml)
        if m:
            return m.group(1)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", required=True)
    ap.add_argument("--dump", action="store_true", help="토큰 키 자동탐지")
    ap.add_argument("--key", help="읽을 prefs 키")
    ap.add_argument("--file", help="특정 xml 파일명(선택)")
    args = ap.parse_args()

    if args.dump:
        dump(args.serial)
    elif args.key:
        tok = read_token(args.serial, args.key, args.file)
        print(tok if tok else "(없음)")
    else:
        print("--dump 또는 --key 지정")


if __name__ == "__main__":
    main()

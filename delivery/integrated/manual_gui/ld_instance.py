"""계정 추가 — `.ldbk` 백업을 새 LDPlayer 인스턴스로 복원한다.

계정을 늘리는 방법은 이것뿐이다. 프로그램의 'refresh 토큰 추가'는 당근 WAF 이전에
만든 경로라 지금은 동작하지 않는다 — 토큰은 에뮬레이터 안의 당근 앱에서만 나온다.
그래서 '계정을 추가한다 = 그 계정으로 로그인된 인스턴스를 만든다' 이다.

손으로 ldconsole 을 두드리면 밟는 함정이 많고 실제로 다 밟았다. 그 처리를 여기
한 곳에 모은다 — GUI 버튼도 명령줄도 같은 함수를 쓴다. 절차가 두 벌이 되면
한쪽만 고쳐지고, 그 한쪽이 계정을 통째로 못 쓰게 만든다.

  · 복원이 `leidian<N>.config` 를 초기화한다. 5개를 한꺼번에 복원했다가 전부
    851바이트로 줄어 해상도·ADB·루트 설정이 날아간 적이 있다.
  · 그 config 를 JSON 으로 읽었다 다시 쓰면(ConvertFrom/ConvertTo, json.load/dump)
    LDPlayer 가 파일을 기본값으로 리셋한다. **텍스트 치환으로만** 고쳐야 한다.
  · ADB 가 꺼진 백업이 있다(adbDebug=0). VM 은 뜨는데 adb 에 안 잡혀 토큰 수확이
    영영 안 된다 — 겉보기에 멀쩡해서 원인을 찾기 어렵다.
  · `data/fleet.json` 에 인덱스를 안 넣으면 새 인스턴스가 감시 대상에서 빠진다.

명령줄:
    python ld_instance.py D:\\ldbk\\inst6.ldbk 정지6
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time

from ld_autoharvest import find_ldconsole, ld_rows

FLEET_REL = os.path.join("data", "fleet.json")
# 복원이 끝난 config 가 이보다 작으면 초기화된 것으로 본다. 정상은 수 KB 이고
# 초기화된 것은 851바이트였다(실측).
CONFIG_MIN_BYTES = 1200
RESTORE_TIMEOUT = 1800          # .ldbk 는 GB 단위라 몇 분 걸린다


class AddError(RuntimeError):
    """계정 추가 실패. 메시지는 사람이 읽고 다음 행동을 정할 수 있게 쓴다."""


def _run(args, timeout=120):
    p = subprocess.run(args, capture_output=True, timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = (p.stdout or b"").decode("utf-8", "ignore")
    err = (p.stderr or b"").decode("utf-8", "ignore")
    return p.returncode, out, err


def _indexes(console):
    return {str(r.get("index")) for r in (ld_rows(console) or []) if r.get("index") is not None}


def _vms_dir(console):
    return os.path.join(os.path.dirname(console), "vms")


def backup_configs(console, log):
    """모든 leidian*.config 를 임시폴더에 떠 둔다. 복원이 남의 것까지 건드린 전례가 있다."""
    import tempfile
    vms = _vms_dir(console)
    dst = os.path.join(tempfile.gettempdir(),
                       "ld_config_" + time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(dst, exist_ok=True)
    n = 0
    try:
        for name in os.listdir(vms):
            if name.startswith("leidian") and name.endswith(".config"):
                shutil.copy2(os.path.join(vms, name), dst)
                n += 1
    except Exception as e:
        log(f"[계정추가] config 백업 실패(계속): {str(e)[:80]}")
        return None
    log(f"[계정추가] config {n}개 백업: {dst}")
    return dst


def ensure_adb_debug(console, index, log):
    """복원된 인스턴스의 ADB 를 켠다. 반환: (고쳤나, 경고문자열|None).

    **JSON 왕복 금지.** 파일을 파싱해 다시 쓰면 LDPlayer 가 설정을 기본값으로
    리셋한다(실측). 필요한 한 글자만 바꾼다.
    """
    path = os.path.join(_vms_dir(console), f"leidian{index}.config")
    if not os.path.exists(path):
        return False, (f"{path} 이 아직 없습니다. 인스턴스를 한 번 켰다 끄면"
                       " 만들어집니다.")
    try:
        raw = open(path, encoding="utf-8").read()
    except Exception as e:
        return False, f"config 를 못 읽었습니다: {str(e)[:80]}"
    # 경고는 **모아서** 돌려준다. 하나로 덮어쓰면 뒤엣것이 앞엣것을 지우고,
    # 지워지는 쪽이 하필 'adb 가 꺼져 토큰이 영영 안 잡힌다'는 경고다.
    warns = []
    if '"basicSettings.adbDebug"' not in raw:
        warns.append("config 에 adbDebug 항목이 없습니다 — 인스턴스 설정 → 기타 →"
                     " ADB '로컬 연결 열기' 를 직접 켜야 토큰이 수확됩니다.")
        fixed = raw
    else:
        fixed = re.sub(r'("basicSettings\.adbDebug"\s*:\s*)0', r"\g<1>1", raw)
    changed = fixed != raw
    if changed:
        shutil.copy2(path, path + ".bak-" + time.strftime("%Y%m%d_%H%M%S"))
        with open(path, "w", encoding="utf-8") as f:
            f.write(fixed)
        log("[계정추가] adbDebug 0 → 1 (0이면 adb 에 안 잡혀 토큰 수확이 안 됩니다)")
    try:
        if os.path.getsize(path) < CONFIG_MIN_BYTES:
            warns.append(f"config 가 {os.path.getsize(path)}바이트로 작습니다 —"
                         " 복원이 설정을 초기화했을 수 있습니다. 백업에서 되돌리세요.")
    except OSError:
        pass
    return changed, (" / ".join(warns) if warns else None)


def add_to_fleet(app_dir, index, log):
    """감시 대상 목록에 넣는다. 안 넣으면 새 인스턴스가 조용히 제외된다.

    이건 우리 파일이라 JSON 으로 써도 된다 — LDPlayer config 와 다르다."""
    path = os.path.join(app_dir, FLEET_REL)
    if not os.path.exists(path):
        log(f"[계정추가] {FLEET_REL} 이 없어 만들지 않았습니다"
            " (없으면 전체 인스턴스가 대상입니다)")
        return None
    try:
        cur = json.load(open(path, encoding="utf-8"))
        vals = cur.get("indexes") if isinstance(cur, dict) else cur
        vals = [int(v) for v in (vals or [])]
    except Exception as e:
        log(f"[계정추가] {FLEET_REL} 을 못 읽어 그대로 둡니다: {str(e)[:80]}")
        return None
    idx = int(index)
    if idx in vals:
        return vals
    vals = sorted(vals + [idx])
    shutil.copy2(path, path + ".bak-" + time.strftime("%Y%m%d_%H%M%S"))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"indexes": vals}, f, ensure_ascii=False)
    os.replace(tmp, path)
    log(f"[계정추가] 감시 대상에 {idx} 추가 → {vals}")
    return vals


def add_from_ldbk(ldbk, name, app_dir=".", console=None, log=None,
                  should_stop=None):
    """`.ldbk` 를 새 인스턴스로 복원한다. 반환 {index, warnings, config_backup}.

    실패는 AddError 로 던진다 — 조용히 반쯤 만들어진 인스턴스를 남기지 않는다.
    """
    log = log or (lambda m: None)
    stop = should_stop or (lambda: False)
    if not ldbk or not os.path.exists(ldbk):
        raise AddError(f".ldbk 파일이 없습니다: {ldbk}")
    name = str(name or "").strip()
    if not name:
        raise AddError("인스턴스 이름을 정하세요(계정을 알아볼 이름).")
    console = console or find_ldconsole()
    if not console or not os.path.exists(console):
        raise AddError("ldconsole.exe 를 못 찾았습니다. LDPlayer 설치를 확인하세요.")

    warnings = []
    cfg_backup = backup_configs(console, log)

    before = _indexes(console)
    log(f"[계정추가] 현재 인스턴스 {len(before)}개 · 새로 만드는 중: {name}")
    rc, out, err = _run([console, "add", "--name", name])
    if rc != 0:
        raise AddError(f"인스턴스 생성 실패: {(err or out or '')[:120]}")
    time.sleep(2)

    after = _indexes(console)
    new = sorted(after - before, key=lambda v: int(v))
    if len(new) != 1:
        raise AddError(
            f"새 인스턴스를 특정하지 못했습니다(전 {len(before)}개 → 후 {len(after)}개)."
            " 같은 이름이 이미 있는지 확인하세요.")
    index = new[0]
    log(f"[계정추가] 새 인덱스: {index}")

    if stop():
        raise AddError("사용자가 중단했습니다(인스턴스는 만들어졌습니다: "
                       f"index {index}).")

    log(f"[계정추가] 복원 중 — 파일이 커서 몇 분 걸립니다: {os.path.basename(ldbk)}")
    rc, out, err = _run([console, "restore", "--index", str(index), "--file", ldbk],
                        timeout=RESTORE_TIMEOUT)
    if rc != 0:
        raise AddError(f"복원 실패(exit {rc}): {(err or out or '')[:120]}")
    time.sleep(2)

    _changed, warn = ensure_adb_debug(console, index, log)
    if warn:
        warnings.append(warn)
        log("[계정추가] 경고: " + warn)
    if cfg_backup:
        log(f"[계정추가] 설정이 이상하면 되돌릴 곳: {cfg_backup}")

    add_to_fleet(app_dir, index, log)
    log("[계정추가] 완료 — 이제 RDP 로 접속한 상태에서 그 인스턴스를 켜세요."
        " LDPlayer 는 실제 RDP 세션이 붙어 있어야 게스트를 띄웁니다.")
    return {"index": index, "warnings": warnings, "config_backup": cfg_backup}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    try:
        r = add_from_ldbk(sys.argv[1], sys.argv[2],
                          app_dir=os.path.dirname(os.path.abspath(__file__)),
                          log=lambda m: print(m, flush=True))
    except AddError as e:
        print(f"[계정추가][실패] {e}", flush=True)
        raise SystemExit(1)
    print(f"[계정추가] index {r['index']}", flush=True)

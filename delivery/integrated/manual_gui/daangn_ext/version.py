"""실행 중인 판이 무엇인지 — 창 우측 상단에 적는다.

설계 이유:
  - 서버는 git 이 없다. 배포가 남기는 data/deployed.json(sha·설치시각)이 유일한
    자기 판 기록이다. 개발 PC 에는 그 파일이 없으니 git 에 묻고, 둘 다 없으면
    '판 미상' 으로 적되 앱은 멀쩡히 뜬다.
  - '최신' 판정은 하지 않는다. 판과 설치 시각만 적고, 최신인지는 보는 사람이
    커밋 기록과 대조한다 — 틀린 '최신' 표시가 없는 표시보다 나쁘다.
  - 여기는 Qt 를 모른다. 순수 함수라 테스트가 창 없이 돈다.
"""
import json
import os
import subprocess
from datetime import datetime, timezone

STAMP_FILE = os.path.join("data", "deployed.json")


def local_version(app_dir=".") -> dict:
    """{'short','sha','installed','source'} — source 는 deploy | git | ''."""
    p = os.path.join(app_dir, STAMP_FILE)
    try:
        with open(p, encoding="utf-8-sig") as f:
            st = json.load(f)
        sha = str(st.get("sha") or "")
        short = str(st.get("short") or sha[:7])
        if short and short != "unknown":
            return {"short": short, "sha": sha, "installed": _local_stamp(st.get("installed")),
                    "source": "deploy"}
    except (OSError, ValueError):
        pass
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=app_dir, capture_output=True,
                             text=True, timeout=5)
        sha = out.stdout.strip()
        if out.returncode == 0 and len(sha) >= 7:
            return {"short": sha[:7], "sha": sha, "installed": "", "source": "git"}
    except (OSError, subprocess.SubprocessError):
        pass
    return {"short": "", "sha": "", "installed": "", "source": ""}


def _local_stamp(iso) -> str:
    """'2026-09-02T23:39:47Z'(UTC) → '09/03 08:39'(현지). 못 읽으면 ''."""
    if not iso:
        return ""
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone().strftime("%m/%d %H:%M")
    except ValueError:
        return ""


def version_label(local: dict) -> str:
    """'v 056224c · 설치 09/02 18:56' / 'v abc1234 · 개발 판' / '판 미상'."""
    short = local.get("short") or ""
    if not short:
        return "판 미상"
    head = f"v {short}"
    if local.get("installed"):
        head += f" · 설치 {local['installed']}"
    elif local.get("source") == "git":
        head += " · 개발 판"
    return head

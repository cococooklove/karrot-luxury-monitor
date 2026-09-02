"""실행 중인 판이 무엇이고 최신인지 — 창 우측 상단에 적는다.

설계 이유:
  - 서버는 git 이 없다. 배포가 남기는 data/deployed.json(sha·설치시각)이 유일한
    자기 판 기록이다. 개발 PC 에는 그 파일이 없으니 git 에 묻고, 둘 다 없으면
    '판 미상' 으로 적되 앱은 멀쩡히 뜬다.
  - '최신인지' 는 GitHub 의 master 끝 커밋과 비교한다. 네트워크는 실패할 수 있으니
    확인 못 하면 확인 못 했다고 적는다 — 최신이라고 우기지 않는다.
  - 여기는 Qt 를 모른다. 순수 함수라 테스트가 창 없이 돈다.
"""
import json
import os
import subprocess
from datetime import datetime, timezone

REPO = "cococooklove/karrot-luxury-monitor"
LATEST_URL = f"https://api.github.com/repos/{REPO}/commits/master"
STAMP_FILE = os.path.join("data", "deployed.json")
NET_TIMEOUT = 8


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


def fetch_latest_sha(timeout=NET_TIMEOUT) -> str:
    """GitHub master 끝 커밋 sha. 실패하면 ''(예외를 밖으로 내지 않는다)."""
    try:
        from urllib.request import Request, urlopen
        req = Request(LATEST_URL, headers={"Accept": "application/vnd.github+json",
                                           "User-Agent": "karrot-monitor"})
        with urlopen(req, timeout=timeout) as r:
            return str(json.load(r).get("sha") or "")
    except Exception:
        return ""


def version_label(local: dict, latest_sha, checked=False) -> tuple:
    """(표시 문구, 상태) — 상태는 latest | outdated | unknown | none.

    checked=False 면 아직 확인 전(기동 직후) — '확인 중'. 확인 뒤 sha 가 비면
    '확인 못 함'. 판 자체가 없으면(none) 최신 여부는 묻지 않는다."""
    short = local.get("short") or ""
    if not short:
        return "판 미상", "none"
    head = f"v {short}"
    if local.get("installed"):
        head += f" · 설치 {local['installed']}"
    elif local.get("source") == "git":
        head += " · 개발 판"
    if not checked:
        return head + " · 최신 확인 중…", "unknown"
    latest = (latest_sha or "").strip()
    if not latest:
        return head + " · 최신 확인 못 함", "unknown"
    if latest.startswith(short) or (local.get("sha") and latest == local["sha"]):
        return head + " · ✓ 최신", "latest"
    return head + f" · ⚠ 새 판 {latest[:7]} 있음", "outdated"

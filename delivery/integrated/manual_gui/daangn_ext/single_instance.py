"""같은 프로그램이 두 번 뜨는 것을 막는다.

왜 필요한가. 각 MainWindow 는 KeywordRouter 를 하나씩 만들어 같은
`data/keyword_routes.json` 을 쓴다. 같은 창이 둘 뜨면 서로의 배정을 덮는다.
실서버 2026-09-02 에 아이콘 실행과 자동시작 작업(karrotgui)이 겹쳐 GUI 가 둘
떴고, 방금 넣은 엑셀 조건이 사라졌다 — 클라에게는 "엑셀이 반영 안 된다"로
보였다.

**모드별로** 잠근다. 클라는 `--manual`(수동검색)과 `--watch`(매물감시)를 두
프로그램으로 쓰는 것이 정상 사용법이라, 통째로 막으면 그 사용법이 깨진다.
같은 모드가 둘인 경우만 사고다.

락 방식은 accounts.json 과 같다 — 파일 존재 여부가 아니라 **OS 파일락**이다.
프로세스가 죽으면 커널이 즉시 놓으므로, 앱이 크래시해도 영영 못 켜는 스테일
상태가 생기지 않는다. 락 수단이 없는 플랫폼에서는 막지 않는다(못 켜는 것보다
겹치는 편이 낫다 — 겹쳐도 라우터 병합이 데이터는 지킨다).
"""
from __future__ import annotations

import os

# 잡은 락은 **프로세스가 사는 동안** 들고 있어야 유지된다. 지역변수로 두면
# GC 가 fd 를 닫으면서 락이 풀린다.
_held: list[int] = []


def lock_file(name: str, dirpath: str = "./data") -> str:
    return os.path.join(dirpath, f"app.{name}.lock")


def acquire(name: str, dirpath: str = "./data") -> bool:
    """이 이름의 인스턴스를 독점한다. 잡았으면 True, 남이 쥐고 있으면 False."""
    try:
        from ld_autoharvest import _try_lock
    except Exception:
        return True                      # 락 수단이 없으면 막지 않는다
    try:
        os.makedirs(dirpath, exist_ok=True)
        fd = os.open(lock_file(name, dirpath), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return True                      # 락 파일을 못 만들어도 실행은 시킨다
    if not _try_lock(fd):
        try:
            os.close(fd)
        except OSError:
            pass
        return False
    _held.append(fd)
    return True


def release_all() -> None:
    """테스트용. 실제 앱은 종료가 곧 해제다."""
    while _held:
        fd = _held.pop()
        try:
            from ld_autoharvest import _unlock
            _unlock(fd)
        except Exception:
            pass
        try:
            os.close(fd)
        except OSError:
            pass

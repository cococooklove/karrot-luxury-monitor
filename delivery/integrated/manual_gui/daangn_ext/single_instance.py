"""같은 일을 하는 프로그램이 두 번 뜨는 것을 막고, 두 번째 실행은 먼저 뜬
창을 앞으로 불러낸다.

왜 필요한가. 각 MainWindow 는 KeywordRouter 를 하나씩 만들어 같은
`data/keyword_routes.json` 을 쓰고, 백그라운드 모드는 수확·폴링까지 돌린다.
같은 일을 하는 창이 둘 뜨면 서로의 배정을 덮는다. 실서버 2026-09-02 에
`--watch`(아이콘)와 `--watchdog`→`--child`(자동시작 작업)가 겹쳐 GUI 가 둘
떴고, 방금 넣은 엑셀 조건이 사라졌다 — 클라에게는 "엑셀이 반영 안 된다"로
보였다.

**무엇을 기준으로 잠그나.** UI 모드가 아니라 `MODES[...]["background"]` 다.

    manual  background=False  수동검색만 — 수확·폴링·라우터 변경 없음
    watch   background=True   매물감시
    all     background=True   자동시작 작업이 띄우는 3탭

모드로 잠그면 `watch` 와 `all` 이 서로 다른 이름이라 둘 다 통과한다 — 실제로
충돌한 조합이 정확히 그것이었다. 그래서 백그라운드를 도는 쪽은 이름 하나를
공유해 한 번에 하나만 뜬다. 수동검색은 별도 이름이라 **매물감시와 동시에 뜬다**
— 클라가 두 프로그램으로 쓰는 정상 사용법이다.

**두 번째 실행은 실패가 아니다.** 클라는 바탕화면 아이콘으로 프로그램을 켠다.
자동시작이 이미 띄워둔 상태에서 아이콘을 누르면 "이미 실행 중" 경고 후 종료는
클라 눈에 '아이콘을 눌렀는데 안 켜진다'이다. 그래서 먼저 뜬 창에 신호를 보내
그 창을 앞으로 올리고 조용히 빠진다.

락은 OS 파일락이라 프로세스가 죽으면 커널이 즉시 놓는다 — 앱이 크래시해도
영영 못 켜는 스테일 상태가 없다. 락 수단이 없는 플랫폼에서는 막지 않는다
(못 켜는 것보다 겹치는 편이 낫다 — 겹쳐도 KeywordRouter._save 의 병합이
데이터는 지킨다).
"""
from __future__ import annotations

import os

# 잡은 락은 **프로세스가 사는 동안** 들고 있어야 유지된다. 지역변수로 두면
# GC 가 fd 를 닫으면서 락이 풀린다.
_held: list[int] = []
_servers: list = []


def key_for(mode: str, modes: dict) -> str:
    """이 모드가 잠가야 할 이름. 백그라운드를 도는 모드끼리는 한 이름을 쓴다."""
    cfg = (modes or {}).get(mode) or {}
    return "background" if cfg.get("background", True) else f"ui-{mode}"


def lock_file(name: str, dirpath: str = "./data") -> str:
    return os.path.join(dirpath, f"app.{name}.lock")


def acquire(name: str, dirpath: str = "./data") -> bool:
    """이 이름을 독점한다. 잡았으면 True, 남이 쥐고 있으면 False."""
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


# ── 먼저 뜬 창 불러내기 ──
# 파일락과 별개의 통로다. 락은 '누가 주인인가'만 정하고, 창을 올리는 건
# 주인에게 말을 걸어야 한다.

def _sock_name(name: str) -> str:
    return f"karrot-monitor-{name}"


def serve(name: str, on_summon) -> bool:
    """주인이 부른다. 다른 실행이 신호를 보내면 on_summon() 이 불린다.

    이미 락을 쥔 뒤에 부르므로 남아 있는 소켓 이름은 죽은 프로세스의 잔재다 —
    removeServer 로 치우고 연다(POSIX 에서 크래시 후 이름이 남는다)."""
    try:
        from PyQt6.QtNetwork import QLocalServer
    except Exception:
        return False
    try:
        QLocalServer.removeServer(_sock_name(name))
        srv = QLocalServer()
        if not srv.listen(_sock_name(name)):
            return False

        def _accept():
            conn = srv.nextPendingConnection()
            if conn is not None:
                conn.disconnected.connect(conn.deleteLater)
            try:
                on_summon()
            except Exception:
                pass
        srv.newConnection.connect(_accept)
        _servers.append(srv)             # GC 되면 리스닝이 끊긴다
        return True
    except Exception:
        return False


def summon(name: str, timeout_ms: int = 1500) -> bool:
    """먼저 뜬 창을 앞으로 불러낸다. 전달됐으면 True."""
    try:
        from PyQt6.QtNetwork import QLocalSocket
    except Exception:
        return False
    try:
        sock = QLocalSocket()
        sock.connectToServer(_sock_name(name))
        if not sock.waitForConnected(timeout_ms):
            return False
        sock.write(b"summon")
        sock.flush()
        sock.waitForBytesWritten(timeout_ms)
        sock.disconnectFromServer()
        return True
    except Exception:
        return False


def release_all() -> None:
    """테스트용. 실제 앱은 종료가 곧 해제다."""
    while _servers:
        srv = _servers.pop()
        try:
            srv.close()
        except Exception:
            pass
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

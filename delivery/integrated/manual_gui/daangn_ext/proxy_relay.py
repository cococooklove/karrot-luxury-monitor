"""인증 없는 로컬 프록시 → 인증 붙는 상용 프록시 릴레이.

왜 필요한가 (2026-09-01 실측):
LDPlayer 게스트의 당근 앱은 안드로이드 전역 프록시를 실제로 탄다. 서버에서
로깅 프록시를 띄우고 `settings put global http_proxy 호스트:포트` 를 걸었더니
api.kr.karrotmarket.com(토큰 갱신), event.kr.karrotmarket.com,
img.kr.gcp-karroter.net 이 전부 그 프록시를 통과했다.

문제는 인증이다. 상용 KR 프록시는 대부분 `http://아이디:비번@호스트:포트` 인데
안드로이드 전역 프록시 설정에는 자격증명 필드가 없다 — `host:port` 뿐이다.
그래서 호스트(윈도우 서버)에서 **인증 없는 로컬 리스너**를 열고, 업스트림으로
넘길 때 `Proxy-Authorization: Basic ...` 을 붙이는 중계가 있어야 한다.

    relay = ProxyRelay({"452902": "http://id:pw@1.2.3.4:8000"}, bind="172.16.1.2")
    relay.start()
    relay.endpoint("452902")     # -> "172.16.1.2:51234"  (게스트에 넣을 값)
    ...
    relay.stop()

설계 결정:
  * **같은 업스트림 URL 은 리스너 하나를 공유한다.** 계정 수만큼 포트를 여는 건
    낭비고, 프록시 업체가 세는 건 동시연결이지 리스너 수가 아니다.
  * **포트는 OS 가 고른다(0번 바인드).** 고정 포트는 재기동·다중 인스턴스에서
    충돌한다. 실제 포트를 읽어 endpoint() 가 돌려준다.
  * **한 연결이 터져도 릴레이는 안 죽는다.** 예외는 삼키되 log= 콜백으로 사유를
    남긴다 — 조용히 끊으면 "프록시가 안 된다"만 남고 원인을 못 찾는다.
  * **잘못된 업스트림 URL 은 그 키만 죽는다.** 생성 시 예외를 올리지 않고
    사유를 로그로 남긴 뒤 그 키의 endpoint() 를 None 으로 둔다. 계정 하나의
    오타가 나머지 계정 감시까지 멈추면 안 된다.
"""
from __future__ import annotations

import base64
import socket
import threading
from urllib.parse import unquote, urlsplit

CONNECT_TIMEOUT = 10.0      # 업스트림 TCP 연결 대기
HEAD_TIMEOUT = 30.0         # 요청/응답 헤더 한 덩이를 기다리는 시간
BUF = 65536                 # 터널 펌프 청크
MAX_HEAD = 65536            # 헤더가 이보다 크면 정상 요청이 아니다


def _parse_upstream(url: str) -> tuple[str, int, str | None]:
    """`http://id:pw@host:port` → (host, port, Basic 헤더값 or None).

    스킴이 없는 `host:port` 도 받는다(운영자가 손으로 적는 값이라 흔하다).
    자격증명이 없으면 세 번째 값이 None — 인증 헤더를 아예 안 붙인다.
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError("업스트림 URL 이 비었다")
    if "://" not in raw:
        raw = "http://" + raw
    sp = urlsplit(raw)
    if sp.scheme not in ("http", "https"):
        raise ValueError(f"지원하지 않는 스킴: {sp.scheme}")
    host = sp.hostname
    if not host:
        raise ValueError(f"호스트를 못 읽었다: {url}")
    try:
        port = sp.port
    except ValueError:
        raise ValueError(f"포트가 숫자가 아니다: {url}") from None
    if not port:
        raise ValueError(f"포트가 없다(host:port 형식이어야 한다): {url}")
    if not (1 <= port <= 65535):
        raise ValueError(f"포트 범위를 벗어난다: {port}")

    auth = None
    if sp.username:
        # 자격증명에 @ : / 가 들어가면 퍼센트 인코딩돼 온다. 풀어서 인코딩해야
        # 업스트림이 알아본다.
        user = unquote(sp.username)
        pw = unquote(sp.password or "")
        token = base64.b64encode(f"{user}:{pw}".encode()).decode("ascii")
        auth = "Basic " + token
    return host, port, auth


def _read_head(sock: socket.socket) -> tuple[bytes, bytes]:
    """헤더 끝(\\r\\n\\r\\n)까지 읽어 (헤더, 남은바이트) 로 나눈다.

    남은 바이트는 이미 도착한 본문/터널 데이터다 — 버리면 첫 요청이 깨진다.
    """
    buf = b""
    while True:
        idx = buf.find(b"\r\n\r\n")
        if idx >= 0:
            return buf[:idx + 4], buf[idx + 4:]
        if len(buf) > MAX_HEAD:
            raise ValueError("헤더가 너무 크다")
        chunk = sock.recv(BUF)
        if not chunk:
            if not buf:
                raise ValueError("연결이 헤더 전에 끊겼다")
            raise ValueError("헤더가 덜 온 채 끊겼다")
        buf += chunk


def _inject_auth(head: bytes, auth: str | None) -> bytes:
    """요청 헤드의 Proxy-Authorization 을 우리 것으로 갈아끼운다.

    클라이언트(게스트)가 보낸 값은 어차피 없거나 틀린 값이므로 지운다.
    auth 가 None 이면 지우기만 하고 새로 붙이지 않는다(요구 5).
    """
    lines = head.split(b"\r\n")
    request_line, rest = lines[0], lines[1:]
    kept = [ln for ln in rest
            if not ln.lower().startswith(b"proxy-authorization:")]
    out = [request_line]
    if auth:
        out.append(b"Proxy-Authorization: " + auth.encode("ascii"))
    out.extend(kept)
    return b"\r\n".join(out)


def _status_code(head: bytes) -> int:
    """응답 헤드의 상태코드. 못 읽으면 0."""
    try:
        parts = head.split(b"\r\n", 1)[0].split(None, 2)
        return int(parts[1])
    except Exception:
        return 0


def _pump(src: socket.socket, dst: socket.socket) -> None:
    """한 방향으로 바이트를 흘린다. 끝나면 쓰기쪽을 닫아 상대에게 EOF 를 준다."""
    try:
        src.settimeout(None)
        while True:
            chunk = src.recv(BUF)
            if not chunk:
                break
            dst.sendall(chunk)
    except Exception:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except Exception:
            pass


class _Listener:
    """업스트림 하나에 대응하는 로컬 리스너."""

    def __init__(self, host: str, port: int, auth: str | None,
                 bind: str, log):
        self.up_host, self.up_port, self.auth = host, port, auth
        self.bind = bind
        self._log = log
        self.srv: socket.socket | None = None
        self.port_local = 0
        self._stop = threading.Event()
        self._conns: set[socket.socket] = set()
        self._lock = threading.Lock()

    # ── 수명 ──
    def start(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.bind, 0))          # 0 = OS 가 빈 포트를 고른다
        srv.listen(64)
        srv.settimeout(0.3)               # stop() 이 즉시 먹히도록
        self.srv = srv
        self.port_local = srv.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        try:
            if self.srv:
                self.srv.close()
        except Exception:
            pass
        with self._lock:
            conns, self._conns = list(self._conns), set()
        for c in conns:
            try:
                c.close()
            except Exception:
                pass

    @property
    def endpoint(self) -> str:
        return f"{self.bind}:{self.port_local}"

    # ── 루프 ──
    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                cli, _addr = self.srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break                      # stop() 이 소켓을 닫았다
            except Exception as e:
                self._log(f"[relay] accept 실패: {e!r}")
                continue
            with self._lock:
                self._conns.add(cli)
            threading.Thread(target=self._serve, args=(cli,),
                             daemon=True).start()

    def _serve(self, cli: socket.socket) -> None:
        up = None
        try:
            cli.settimeout(HEAD_TIMEOUT)
            head, leftover = _read_head(cli)
            method = head.split(b" ", 1)[0].upper()
            up = socket.create_connection(
                (self.up_host, self.up_port), timeout=CONNECT_TIMEOUT)
            up.settimeout(HEAD_TIMEOUT)
            if method == b"CONNECT":
                self._do_connect(cli, up, head, leftover)
            else:
                self._do_plain(cli, up, head, leftover)
        except Exception as e:
            # 요구 9: 한 연결이 터져도 릴레이 전체는 산다. 대신 사유는 남긴다.
            self._log(f"[relay] {self.up_host}:{self.up_port} 연결 처리 실패: {e!r}")
        finally:
            with self._lock:
                self._conns.discard(cli)
            for s in (cli, up):
                try:
                    if s:
                        s.close()
                except Exception:
                    pass

    def _do_connect(self, cli, up, head: bytes, leftover: bytes) -> None:
        """CONNECT host:443 을 인증 붙여 업스트림에 다시 던진다."""
        up.sendall(_inject_auth(head, self.auth))
        up_head, up_left = _read_head(up)
        code = _status_code(up_head)
        if code != 200:
            # 요구 3: 조용히 끊지 않는다. 407/403 을 그대로 내려보내야
            # 운영자가 "자격증명이 틀렸구나"를 안다.
            status = up_head.split(b"\r\n", 1)[0][:120].decode(
                "latin-1", "replace")
            self._log(f"[relay] {self.up_host}:{self.up_port} 가 터널을 거부: "
                      f"{status}")
            try:
                cli.sendall(up_head)
            except Exception:
                pass
            return
        cli.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        if leftover:
            up.sendall(leftover)           # 클라가 미리 보낸 TLS ClientHello
        if up_left:
            cli.sendall(up_left)           # 업스트림이 헤더에 붙여 보낸 첫 바이트
        self._tunnel(cli, up)

    def _do_plain(self, cli, up, head: bytes, leftover: bytes) -> None:
        """절대 URL 평문 요청을 인증만 붙여 그대로 넘긴다."""
        up.sendall(_inject_auth(head, self.auth))
        if leftover:
            up.sendall(leftover)
        self._tunnel(cli, up)

    def _tunnel(self, cli, up) -> None:
        t = threading.Thread(target=_pump, args=(cli, up), daemon=True)
        t.start()
        _pump(up, cli)                     # 업스트림→클라는 이 스레드가 맡는다
        t.join(timeout=5.0)


class ProxyRelay:
    """{키: 업스트림URL} 을 받아 키마다 인증 없는 로컬 엔드포인트를 준다.

    bind 기본값이 **127.0.0.1** 인 이유: 이 릴레이는 인증이 없다. 공개 IP 를
    가진 서버(예: 108.181.252.171)에서 0.0.0.0 으로 열면 인터넷 아무나
    우리 유료 프록시 자격증명으로 트래픽을 흘릴 수 있는 오픈 프록시가 된다.
    LDPlayer 게스트에서 붙여야 할 때만 호스트-온리 네트워크 주소(예: LDPlayer
    NAT 게이트웨이 172.16.1.2)를 명시적으로 넘길 것. 0.0.0.0 은 마지막 수단.
    """

    def __init__(self, upstreams: dict[str, str] | None = None,
                 bind: str = "127.0.0.1", log=None):
        self.bind = bind or "127.0.0.1"
        self._log = log if callable(log) else (lambda m: None)
        self._listeners: list[_Listener] = []
        self._by_key: dict[str, _Listener] = {}
        self._errors: dict[str, str] = {}
        self._started = False
        self._lock = threading.Lock()
        for key, url in (upstreams or {}).items():
            self.add(key, url)

    # ── 구성 ──
    def add(self, key: str, url: str) -> bool:
        """키 하나를 등록한다. URL 이 잘못됐으면 False + 로그(예외 없음).

        같은 업스트림이 이미 있으면 그 리스너를 재사용한다(요구 1).
        """
        try:
            host, port, auth = _parse_upstream(url)
        except Exception as e:
            self._errors[key] = str(e)
            self._log(f"[relay] {key}: 업스트림 URL 을 못 읽었다 — {e}")
            return False
        ident = (host, port, auth)
        with self._lock:
            for ls in self._listeners:
                if (ls.up_host, ls.up_port, ls.auth) == ident:
                    self._by_key[key] = ls
                    return True
            ls = _Listener(host, port, auth, self.bind, self._log)
            if self._started:
                ls.start()
            self._listeners.append(ls)
            self._by_key[key] = ls
        return True

    # ── 수명 ──
    def start(self) -> "ProxyRelay":
        with self._lock:
            if self._started:
                return self
            self._started = True
            listeners = list(self._listeners)
        for ls in listeners:
            try:
                ls.start()
            except Exception as e:
                self._log(f"[relay] {ls.up_host}:{ls.up_port} 리스너 기동 실패: {e!r}")
        return self

    def stop(self) -> None:
        with self._lock:
            self._started = False
            listeners = list(self._listeners)
        for ls in listeners:
            try:
                ls.stop()
            except Exception:
                pass

    def __enter__(self):
        return self.start()

    def __exit__(self, *_exc):
        self.stop()
        return False

    # ── 조회 ──
    def endpoint(self, key: str) -> str | None:
        """게스트에 넣을 `host:port`. 미등록/잘못된 URL/미기동이면 None."""
        ls = self._by_key.get(key)
        if ls is None or not ls.port_local:
            return None
        return ls.endpoint

    def endpoints(self) -> dict[str, str]:
        return {k: e for k in self._by_key if (e := self.endpoint(k))}

    def listener_count(self) -> int:
        """열린(또는 열릴) 리스너 수. 계정 수가 아니라 업스트림 수여야 한다."""
        return len(self._listeners)

    def errors(self) -> dict[str, str]:
        """URL 을 못 읽어 릴레이가 안 붙은 키 → 사유."""
        return dict(self._errors)

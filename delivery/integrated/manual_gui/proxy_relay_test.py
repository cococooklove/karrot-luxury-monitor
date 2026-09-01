"""인증 릴레이 — 게스트가 못 넣는 자격증명을 호스트가 대신 붙이는가.

안드로이드 전역 프록시에는 아이디/비번 칸이 없다(`host:port` 뿐). 상용 KR
프록시는 대부분 인증을 요구한다. 그래서 호스트에서 인증 없는 리스너를 열고
업스트림으로 넘길 때 `Proxy-Authorization` 을 붙이는 릴레이가 필요하다.

여기서 mock 으로 때우면 의미가 없다 — 정말 확인해야 할 건 "그 헤더가 실제로
업스트림 소켓에 도착하는가"이므로, **진짜 소켓(전부 127.0.0.1)** 으로 가짜
업스트림 프록시를 띄워 받은 바이트를 검사한다. 라이브 네트워크는 안 탄다.

실행: python proxy_relay_test.py
"""
import base64
import os
import socket
import sys
import threading
import time

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

from daangn_ext import proxy_relay as PR
from daangn_ext.proxy_relay import ProxyRelay

R = []


def ck(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  {extra}")


# ────────────────────────────── 가짜 업스트림 ──────────────────────────────
class FakeUpstream:
    """127.0.0.1 에 뜨는 가짜 인증 프록시.

    CONNECT 를 받으면 200 을 주고 **에코 서버**가 된다(= 목적지 흉내).
    status=407 로 만들면 인증 거부를 흉내낸다. 받은 요청 헤드는 전부 보관해
    테스트가 Proxy-Authorization 을 직접 들여다볼 수 있게 한다.
    """

    def __init__(self, status=200):
        self.status = status
        self.heads = []
        self._stop = threading.Event()
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(16)
        self.srv.settimeout(0.2)
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self._loop, daemon=True).start()

    @property
    def url_auth(self):
        return f"http://tester:s3cr3t@127.0.0.1:{self.port}"

    @property
    def url_plain(self):
        return f"http://127.0.0.1:{self.port}"

    def _loop(self):
        while not self._stop.is_set():
            try:
                c, _ = self.srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(c,), daemon=True).start()

    def _handle(self, c):
        try:
            c.settimeout(5.0)
            head, left = read_head(c)
            self.heads.append(head)
            if head.split(b" ", 1)[0].upper() == b"CONNECT":
                if self.status != 200:
                    c.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\n"
                              b"Proxy-Authenticate: Basic realm=\"up\"\r\n\r\n")
                    return
                c.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                if left:
                    c.sendall(left)             # 미리 온 바이트도 에코
                while True:
                    b = c.recv(4096)
                    if not b:
                        break
                    c.sendall(b)                # 에코
            else:
                body = b"ok"
                c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n"
                          b"Connection: close\r\n\r\n" + body)
        except Exception:
            pass
        finally:
            try:
                c.close()
            except Exception:
                pass

    def stop(self):
        self._stop.set()
        try:
            self.srv.close()
        except Exception:
            pass

    def auth_header_of(self, i=0):
        """i 번째로 받은 요청의 Proxy-Authorization 값(없으면 None)."""
        for ln in self.heads[i].split(b"\r\n"):
            if ln.lower().startswith(b"proxy-authorization:"):
                return ln.split(b":", 1)[1].strip()
        return None


def read_head(sock):
    """헤더 끝까지만 읽고 남은 바이트를 함께 돌려준다."""
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    i = buf.find(b"\r\n\r\n")
    if i < 0:
        return buf, b""
    return buf[:i + 4], buf[i + 4:]


def dial(endpoint, timeout=5.0):
    host, port = endpoint.rsplit(":", 1)
    s = socket.create_connection((host, int(port)), timeout=timeout)
    s.settimeout(timeout)
    return s


def recv_all(sock, n, timeout=5.0):
    """n 바이트가 모일 때까지(또는 EOF/타임아웃까지) 읽는다."""
    out, dead = b"", time.time() + timeout
    while len(out) < n and time.time() < dead:
        try:
            b = sock.recv(n - len(out))
        except socket.timeout:
            break
        if not b:
            break
        out += b
    return out


LOGS = []
def log(m):
    LOGS.append(m)


open_things = []

# ────────────────────── 1. CONNECT 터널 + 인증 헤더 ──────────────────────
print("=== 1. CONNECT 터널: 인증이 붙고 바이트가 왕복한다 ===")
up = FakeUpstream()
open_things.append(up)
relay = ProxyRelay({"452902": up.url_auth}, log=log)
open_things.append(relay)
relay.start()

ep = relay.endpoint("452902")
ck("endpoint 가 host:port 를 준다", bool(ep) and ep.startswith("127.0.0.1:"), str(ep))
ck("포트를 OS 가 골랐다(0 이 아니다)", int(ep.rsplit(":", 1)[1]) > 0, str(ep))

c = dial(ep)
c.sendall(b"CONNECT api.kr.karrotmarket.com:443 HTTP/1.1\r\n"
          b"Host: api.kr.karrotmarket.com:443\r\n\r\n")
head, left = read_head(c)
ck("클라이언트가 200 Connection Established 를 받는다",
   b"200" in head.split(b"\r\n")[0], head.split(b"\r\n")[0][:60])

c.sendall(b"PING-TOKEN-REFRESH")
echoed = recv_all(c, len(left) + len(b"PING-TOKEN-REFRESH"))
ck("터널로 바이트가 왕복한다", (left + echoed) == b"PING-TOKEN-REFRESH",
   repr(left + echoed))
c.close()

ck("업스트림에 요청이 도착했다", len(up.heads) == 1, f"{len(up.heads)}건")
got = up.auth_header_of(0)
want = b"Basic " + base64.b64encode(b"tester:s3cr3t")
ck("Proxy-Authorization 이 실제로 도착한다", got is not None, repr(got))
ck("base64 가 맞다", got == want, f"got={got!r} want={want!r}")
ck("CONNECT 대상 호스트가 보존된다",
   up.heads[0].split(b"\r\n")[0] == b"CONNECT api.kr.karrotmarket.com:443 HTTP/1.1",
   up.heads[0].split(b"\r\n")[0])

print("\n=== 2. CONNECT 앞질러 온 바이트(TLS ClientHello)도 안 잃는다 ===")
c = dial(ep)
c.sendall(b"CONNECT api.kr.karrotmarket.com:443 HTTP/1.1\r\n"
          b"Host: api.kr.karrotmarket.com:443\r\n\r\n" + b"EARLY")
head, left = read_head(c)
rest = recv_all(c, 5 - len(left))
ck("헤더에 붙여 보낸 바이트가 업스트림까지 간다", (left + rest) == b"EARLY",
   repr(left + rest))
c.close()

# ─────────────────────── 3. 평문 HTTP 절대 URL ───────────────────────
print("\n=== 3. 평문 HTTP: 절대 URL 그대로 + 인증만 추가 ===")
c = dial(ep)
# 게스트가 엉뚱한 인증 헤더를 이미 달고 오는 경우까지 함께 본다.
c.sendall(b"GET http://img.kr.gcp-karroter.net/a.jpg HTTP/1.1\r\n"
          b"Host: img.kr.gcp-karroter.net\r\n"
          b"Proxy-Authorization: Basic Z2FyYmFnZQ==\r\n\r\n")
head, _ = read_head(c)
ck("응답이 클라이언트까지 온다", head.split(b"\r\n")[0].startswith(b"HTTP/1.1 200"),
   head.split(b"\r\n")[0])
c.close()
plain = up.heads[-1]
ck("요청 라인이 절대 URL 그대로 넘어간다",
   plain.split(b"\r\n")[0] == b"GET http://img.kr.gcp-karroter.net/a.jpg HTTP/1.1",
   plain.split(b"\r\n")[0])
ck("우리 자격증명으로 갈아끼운다", up.auth_header_of(-1) == want,
   repr(up.auth_header_of(-1)))
ck("클라가 보낸 가짜 인증 헤더는 안 남는다",
   plain.lower().count(b"proxy-authorization:") == 1,
   str(plain.lower().count(b"proxy-authorization:")))
ck("나머지 헤더는 보존된다", b"Host: img.kr.gcp-karroter.net" in plain)

# ───────────────── 4. 자격증명 없는 업스트림 → 헤더 없음 ─────────────────
print("\n=== 4. 자격증명 없는 업스트림이면 인증 헤더를 안 붙인다 ===")
up2 = FakeUpstream()
open_things.append(up2)
r2 = ProxyRelay({"k": up2.url_plain}, log=log)
open_things.append(r2)
r2.start()
c = dial(r2.endpoint("k"))
c.sendall(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
read_head(c)
c.close()
time.sleep(0.1)
ck("업스트림이 요청을 받았다", len(up2.heads) == 1, f"{len(up2.heads)}건")
ck("Proxy-Authorization 이 아예 없다", up2.auth_header_of(0) is None,
   repr(up2.auth_header_of(0)))

# ───────────────────── 5. 407 은 그대로 전달된다 ─────────────────────
print("\n=== 5. 업스트림이 407 이면 그 상태를 클라이언트가 본다 ===")
up407 = FakeUpstream(status=407)
open_things.append(up407)
r3 = ProxyRelay({"k": up407.url_auth}, log=log)
open_things.append(r3)
r3.start()
c = dial(r3.endpoint("k"))
c.sendall(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
head, _ = read_head(c)
first = head.split(b"\r\n")[0]
ck("407 상태줄이 클라이언트까지 온다", b"407" in first, first)
ck("조용히 끊지 않는다(본문 있음)", len(head) > 0, f"{len(head)}B")
ck("Proxy-Authenticate 도 전달된다", b"Proxy-Authenticate" in head)
c.close()
ck("거부 사유가 로그에 남는다", any("거부" in m for m in LOGS), str(LOGS[-1:]))

# ──────────────────── 6. 같은 업스트림 = 리스너 하나 ────────────────────
print("\n=== 6. 같은 업스트림 두 키 → 리스너/포트 하나 ===")
r4 = ProxyRelay({"452902": up.url_auth,
                 "463777": up.url_auth,
                 "999999": up2.url_plain}, log=log)
open_things.append(r4)
r4.start()
ck("같은 URL 두 키가 같은 포트", r4.endpoint("452902") == r4.endpoint("463777"),
   f'{r4.endpoint("452902")} vs {r4.endpoint("463777")}')
ck("다른 URL 은 다른 포트", r4.endpoint("999999") != r4.endpoint("452902"))
ck("리스너는 계정 수가 아니라 업스트림 수", r4.listener_count() == 2,
   f"{r4.listener_count()}개")
# 스킴을 생략해 적어도 같은 업스트림으로 본다(운영자가 손으로 적는 값이다).
r4.add("bare", up.url_auth.replace("http://", ""))
ck("스킴 유무는 같은 업스트림으로 친다", r4.endpoint("bare") == r4.endpoint("452902"))
ck("리스너가 안 늘어난다", r4.listener_count() == 2, f"{r4.listener_count()}개")

# ─────────────────────── 7. stop() 이후 포트가 닫힌다 ───────────────────────
print("\n=== 7. stop() 뒤 포트가 닫힌다 ===")
ep4 = r4.endpoint("452902")
r4.stop()
time.sleep(0.5)
closed = False
try:
    s = dial(ep4, timeout=1.0)
    s.close()
except (ConnectionRefusedError, OSError):
    closed = True
ck("연결이 거부된다", closed, ep4)

# ─────────────── 8. 잘못된 URL / 업스트림 실패에도 안 죽는다 ───────────────
print("\n=== 8. 잘못된 설정·업스트림 장애에도 릴레이가 산다 ===")
bad = ProxyRelay({
    "빈값": "",
    "포트없음": "http://1.2.3.4",
    "포트문자": "http://1.2.3.4:abcd",
    "포트범위": "http://1.2.3.4:99999",
    "스킴이상": "socks5://1.2.3.4:1080",
    "정상": up.url_auth,
}, log=log)
open_things.append(bad)
bad.start()
for k in ("빈값", "포트없음", "포트문자", "포트범위", "스킴이상"):
    ck(f"{k} 은 endpoint 가 None", bad.endpoint(k) is None, str(bad.endpoint(k)))
ck("사유가 errors() 에 남는다", len(bad.errors()) == 5, str(list(bad.errors())))
ck("사유가 로그에도 남는다", any("못 읽었다" in m for m in LOGS))
ck("정상 키는 멀쩡히 뜬다", bool(bad.endpoint("정상")), str(bad.endpoint("정상")))
ck("없는 키는 None", bad.endpoint("없는계정") is None)

# 업스트림이 죽어 있는 경우: 연결은 끊기지만 릴레이는 다음 요청을 계속 받는다.
dead = socket.socket()
dead.bind(("127.0.0.1", 0))
dead_port = dead.getsockname()[1]
dead.close()                                   # 아무도 안 듣는 포트
r5 = ProxyRelay({"죽은놈": f"http://u:p@127.0.0.1:{dead_port}"}, log=log)
open_things.append(r5)
r5.start()
ep5 = r5.endpoint("죽은놈")
c = dial(ep5)
c.sendall(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
ck("업스트림 실패는 연결 종료로 나타난다", recv_all(c, 1, timeout=3.0) == b"")
c.close()
ck("실패 사유가 로그에 남는다", any("연결 처리 실패" in m for m in LOGS),
   str(LOGS[-1:]))
# 같은 릴레이가 그 뒤에도 살아 있는가 (요구 9의 핵심)
c = dial(ep5, timeout=2.0)
c.sendall(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
ck("리스너는 그 뒤에도 accept 한다", recv_all(c, 1, timeout=3.0) == b"")
c.close()
c = dial(bad.endpoint("정상"))
c.sendall(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
h, _ = read_head(c)
ck("다른 릴레이도 정상 동작", b"200" in h.split(b"\r\n")[0], h.split(b"\r\n")[0])
c.close()

# 헤더가 아닌 쓰레기를 밀어넣어도 프로세스가 산다
c = dial(bad.endpoint("정상"))
c.sendall(b"\x00\x01GARBAGE\r\n")
c.close()
time.sleep(0.2)
c = dial(bad.endpoint("정상"))
c.sendall(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
h, _ = read_head(c)
ck("쓰레기 입력 뒤에도 정상 처리", b"200" in h.split(b"\r\n")[0],
   h.split(b"\r\n")[0])
c.close()

# ───────────────── 9. 기본 바인드는 127.0.0.1 (오픈프록시 방지) ─────────────────
print("\n=== 9. 기본 바인드는 루프백이다 ===")
r6 = ProxyRelay({"k": up.url_auth}, log=log)
open_things.append(r6)
r6.start()
ck("기본 bind 가 127.0.0.1", r6.endpoint("k").startswith("127.0.0.1:"),
   r6.endpoint("k"))
src = open("daangn_ext/proxy_relay.py", encoding="utf-8").read()
ck("기본값 이유가 독스트링에 적혀 있다",
   "127.0.0.1" in src and "오픈 프록시" in src)
# 게스트에서 붙이려면 호스트-온리 주소로 바꿔 열 수 있어야 한다. 127.0.0.2 는
# OS/설정에 따라 없을 수 있으므로(맥 기본이 그렇다) 그 경우엔 "죽지 않고
# 사유를 남기는가"를 대신 본다 — 바인드 실패로 감시가 통째로 멈추면 안 된다.
n_logs = len(LOGS)
r7 = ProxyRelay({"k": up.url_auth}, bind="127.0.0.2", log=log)
open_things.append(r7)
r7.start()
if r7.endpoint("k"):
    ck("bind 를 인자로 바꿀 수 있다",
       r7.endpoint("k").startswith("127.0.0.2:"), str(r7.endpoint("k")))
else:
    ck("바인드 못 하면 죽지 않고 사유를 남긴다",
       any("리스너 기동 실패" in m for m in LOGS[n_logs:]),
       f"(127.0.0.2 없는 환경) {LOGS[n_logs:]}")
# 어떤 경우든 기본 릴레이는 계속 살아 있어야 한다.
c = dial(r6.endpoint("k"))
c.sendall(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
h, _ = read_head(c)
ck("다른 bind 실패가 기존 릴레이를 안 건드린다", b"200" in h.split(b"\r\n")[0],
   h.split(b"\r\n")[0])
c.close()

# ───────────────── 10. 퍼센트 인코딩된 자격증명 ─────────────────
print("\n=== 10. 특수문자 자격증명도 제대로 인코딩된다 ===")
up3 = FakeUpstream()
open_things.append(up3)
r8 = ProxyRelay({"k": f"http://u%40s:p%3Aw@127.0.0.1:{up3.port}"}, log=log)
open_things.append(r8)
r8.start()
c = dial(r8.endpoint("k"))
c.sendall(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
read_head(c)
c.close()
time.sleep(0.1)
ck("퍼센트 인코딩을 풀어서 base64 한다",
   up3.auth_header_of(0) == b"Basic " + base64.b64encode(b"u@s:p:w"),
   repr(up3.auth_header_of(0)))

# ───────────────── 11. 스레드는 데몬 (프로세스가 안 물린다) ─────────────────
print("\n=== 11. 스레드는 전부 데몬 ===")
alive = [t for t in threading.enumerate() if not t.daemon and t is not threading.main_thread()]
ck("논데몬 스레드를 안 남긴다", not alive, str(alive))

for t in open_things:
    try:
        t.stop()
    except Exception:
        pass

print("\n=== 12. keep-alive 로 인증이 새지 않는다 ===")
# 인증은 첫 요청 헤더에만 붙는다. 같은 연결로 두 번째 요청이 오면 인증 없이
# 나가 업스트림이 407 로 막는다 — 첫 요청만 되고 나머지는 조용히 실패한다.
# 그래서 연결 재사용 자체를 막는다.
_fc = PR._force_close
h = (b"GET http://x/ HTTP/1.1\r\nHost: x\r\n"
     b"Connection: keep-alive\r\nProxy-Connection: keep-alive\r\n\r\n")
out = _fc(h)
ck("keep-alive 를 지운다", b"keep-alive" not in out.lower(), str(out[:80]))
ck("close 로 바꾼다", b"Connection: close" in out and b"Proxy-Connection: close" in out)
ck("요청라인은 보존", out.startswith(b"GET http://x/ HTTP/1.1"))
ck("다른 헤더는 보존", b"Host: x" in out)
ck("대소문자 섞여도 지운다",
   b"keep-alive" not in _fc(b"GET / HTTP/1.1\r\nCONNECTION: Keep-Alive\r\n\r\n").lower())
ck("망가진 입력에도 안 죽는다", isinstance(_fc(b"\xff\xfe"), bytes))

print("\n=== 13. 리스너를 못 열어도 그 키만 죽는다 ===")
# 계정 하나 때문에 나머지 계정의 프록시 반영이 통째로 멈추면 안 된다.
r13 = ProxyRelay(bind="127.0.0.1", log=lambda m: None).start()
try:
    class _Boom:
        def __init__(self, *a, **k):
            self.up_host, self.up_port, self.auth = "boom", 1, None

        def start(self):
            raise OSError("바인드 불가")

    _orig_ls = PR._Listener
    PR._Listener = _Boom
    ok13 = r13.add("bad", "http://u:p@1.2.3.4:8000")
    PR._Listener = _orig_ls
    ck("예외 대신 False", ok13 is False)
    ck("사유를 남긴다", "bad" in (r13.errors() or {}), str(r13.errors()))
    ck("정상 키는 계속 된다", r13.add("good", "http://u:p@5.6.7.8:9000") is True)
    ck("정상 키 엔드포인트가 있다", bool(r13.endpoint("good")))
finally:
    r13.stop()

bad_names = [n for n, ok in R if not ok]
print(f"\n{len(R) - len(bad_names)}/{len(R)} PASS")
if bad_names:
    print("실패:", bad_names)
sys.exit(1 if bad_names else 0)

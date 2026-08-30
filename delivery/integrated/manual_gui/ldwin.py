"""LDPlayer 인스턴스 창을 GUI 안으로 끌어와 탭으로 보여주기 위한 Win32 헬퍼.

LDPlayer 는 인스턴스마다 별도 프로세스(dnplayer.exe)의 top-level 창을 띄우고,
탭 UI 를 제공하지 않는다. 그래서 창 스타일을 WS_CHILD 로 바꾸고 SetParent 로
우리 QWidget 밑에 붙여(reparent) 탭처럼 보이게 한다.

주의:
- 붙인 창은 부모(우리 앱)가 죽으면 같이 파괴된다. 반드시 종료 전에 release_all()
  로 원래 top-level 로 되돌려야 dnplayer 프로세스가 살아남는다.
- AttachThreadInput 은 쓰지 않는다. LDPlayer 부팅 hang 이 알려진 증상이라
  입력 큐를 붙이면 GUI 까지 같이 얼어붙는다. 대신 클릭 시 SetFocus 만 준다.
- Windows 전용. 다른 OS 에서는 IS_WINDOWS=False 이고 모든 함수가 무해한
  기본값을 돌려준다(개발 머신에서 import 만 해도 죽지 않게).
- **QApplication 을 만든 뒤에 쓸 것.** Qt 는 시작할 때 프로세스 DPI 인식을
  PER_MONITOR_AWARE_V2 로 바꾸고, 그 전후로 GetWindowRect 좌표계가 달라진다
  (200% 스케일 서버에서 정확히 2배 차이나는 걸 확인했다). Qt 전에 좌표를
  기억해 두면 복원 때 창이 절반 크기로 튀어나온다. main.py 는 QApplication →
  MainWindow → _build_emul_tab 순서라 안전하다.
"""

import os
import subprocess
import sys

IS_WINDOWS = sys.platform.startswith("win")


def _log(msg):
    """콘솔 인코딩(cp949/cp1252)이 한글을 못 받아도 죽지 않게."""
    try:
        print(msg)
    except Exception:
        pass

# ── ldconsole ────────────────────────────────────────────────────────────────

_CONSOLE_NAMES = ["ldconsole.exe", "dnconsole.exe"]


def find_console(adb_bin=None):
    """ldconsole.exe 경로. ld_autoharvest 의 탐색 로직을 그대로 재사용한다."""
    try:
        import ld_autoharvest
        return ld_autoharvest.find_ldconsole(adb_bin)
    except Exception:
        pass
    for base in (r"C:\LDPlayer\LDPlayer9", r"C:\LDPlayer\LDPlayer4",
                 r"C:\Program Files\LDPlayer\LDPlayer9"):
        for n in _CONSOLE_NAMES:
            p = os.path.join(base, n)
            if os.path.exists(p):
                return p
    return None


def parse_list2(text):
    """`ldconsole list2` 출력 파싱.

    포맷: index,name,top_hwnd,bind_hwnd,android_started,pid,vbox_pid
    핸들/pid 가 0 이거나 필드가 모자란 줄도 깨지지 않게 방어적으로 읽는다.
    """
    rows = []
    for line in (text or "").splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) < 2 or not f[0].lstrip("-").isdigit():
            continue

        def num(i):
            try:
                return int(f[i])
            except (IndexError, ValueError):
                return 0

        rows.append({
            "index": int(f[0]),
            "name": f[1],
            "top_hwnd": num(2),
            "bind_hwnd": num(3),
            "running": num(4) not in (0, -1),
            "pid": num(5),
        })
    return rows


def resolve_instances(rows, windows):
    """list2 행과 실제 창 목록을 대조해 인스턴스별 진짜 창 핸들을 정한다.

    list2 의 필드 순서(index,name,top_hwnd,bind_hwnd,...)는 LDPlayer 버전마다
    다를 수 있다. 그래서 핸들을 곧이곧대로 믿지 않고, 실제 dnplayer 창 목록과
    제목/PID 로 교차 검증한다. 어긋나면 제목 → PID 순으로 다시 찾는다.
    창을 못 찾은 인스턴스는 running=False (보여줄 화면이 없다).
    """
    by_hwnd, by_title, by_pid = {}, {}, {}
    for w in windows:
        by_hwnd[w["hwnd"]] = w
        by_title.setdefault(w["title"], w)
        by_pid.setdefault(w["pid"], w)

    out = []
    for r in rows:
        cand = by_hwnd.get(r["top_hwnd"])
        win = None
        if cand is not None and (cand["title"] == r["name"]
                                 or (r["pid"] and cand["pid"] == r["pid"])):
            win = cand                       # list2 핸들이 교차검증을 통과
        if win is None:
            win = by_title.get(r["name"])    # 제목 = 인스턴스 이름
        if win is None and r["pid"]:
            win = by_pid.get(r["pid"])
        if win is None:
            win = cand                       # 마지막 수단: 그래도 후보가 있으면 쓴다
        row = dict(r)
        row["top_hwnd"] = win["hwnd"] if win else 0
        row["running"] = bool(win)
        row["title"] = win["title"] if win else r["name"]
        if win:
            row["pid"] = win["pid"] or r["pid"]
        out.append(row)
    return out


def list_instances(console):
    """인스턴스 목록 — 실제 창 핸들까지 확정해서 돌려준다. 실패 시 빈 리스트."""
    if not console:
        return []
    try:
        p = subprocess.run([console, "list2"], capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        rows = parse_list2(p.stdout.decode("utf-8", "ignore"))
    except Exception:
        return []
    if not rows:
        return []
    return resolve_instances(rows, player_windows())


# ── Win32 ────────────────────────────────────────────────────────────────────

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_BORDER = 0x00800000
WS_DLGFRAME = 0x00400000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000
WS_EX_APPWINDOW = 0x00040000

SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040

SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWNA = 8

WS_EX_TOOLWINDOW = 0x00000080
SWP_NOSIZE = 0x0001
STOW_POS = -32000        # 창을 치워둘 좌표(가상 화면 밖)
STOW_DETECT = -20000     # 이보다 왼쪽이면 우리가 치운 창으로 본다

_DECORATIONS = (WS_POPUP | WS_CAPTION | WS_BORDER | WS_DLGFRAME | WS_THICKFRAME
                | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _u32 = ctypes.WinDLL("user32", use_last_error=True)

    # 64bit 는 *Ptr, 32bit 는 LongW 만 있다.
    _get_long = getattr(_u32, "GetWindowLongPtrW", None) or _u32.GetWindowLongW
    _set_long = getattr(_u32, "SetWindowLongPtrW", None) or _u32.SetWindowLongW
    _get_long.argtypes = [wintypes.HWND, ctypes.c_int]
    _get_long.restype = ctypes.c_ssize_t
    _set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _set_long.restype = ctypes.c_ssize_t

    _u32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    _u32.SetParent.restype = wintypes.HWND
    _u32.IsWindow.argtypes = [wintypes.HWND]
    _u32.IsWindow.restype = wintypes.BOOL
    _u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _u32.GetWindowRect.restype = wintypes.BOOL
    _u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_uint]
    _u32.SetWindowPos.restype = wintypes.BOOL
    _u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _u32.ShowWindow.restype = wintypes.BOOL
    _u32.SetFocus.argtypes = [wintypes.HWND]
    _u32.SetFocus.restype = wintypes.HWND
    _u32.IsWindowVisible.argtypes = [wintypes.HWND]
    _u32.IsWindowVisible.restype = wintypes.BOOL
    _u32.GetDC.argtypes = [wintypes.HWND]
    _u32.GetDC.restype = wintypes.HDC
    _u32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _u32.ReleaseDC.restype = ctypes.c_int
    _u32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    _u32.PrintWindow.restype = wintypes.BOOL
    _u32.GetParent.argtypes = [wintypes.HWND]
    _u32.GetParent.restype = wintypes.HWND
    _u32.GetDesktopWindow.argtypes = []
    _u32.GetDesktopWindow.restype = wintypes.HWND
    _u32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    _u32.GetWindow.restype = wintypes.HWND
    _u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                              ctypes.POINTER(wintypes.DWORD)]
    _u32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _u32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _u32.GetWindowTextLengthW.restype = ctypes.c_int
    _u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _u32.GetWindowTextW.restype = ctypes.c_int
    _u32.GetWindowDC.argtypes = [wintypes.HWND]
    _u32.GetWindowDC.restype = wintypes.HDC

    _ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _u32.EnumWindows.argtypes = [_ENUMPROC, wintypes.LPARAM]
    _u32.EnumWindows.restype = wintypes.BOOL

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
    _k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]

    _gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    _gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _gdi.CreateCompatibleDC.restype = wintypes.HDC
    _gdi.DeleteDC.argtypes = [wintypes.HDC]
    _gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    _gdi.SelectObject.restype = wintypes.HGDIOBJ
    _gdi.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                      ctypes.POINTER(ctypes.c_void_p),
                                      wintypes.HANDLE, wintypes.DWORD]
    _gdi.CreateDIBSection.restype = wintypes.HBITMAP
    _gdi.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                            ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int,
                            wintypes.DWORD]
    _gdi.BitBlt.restype = wintypes.BOOL

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                    ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


PLAYER_EXES = ("dnplayer.exe", "ldplayer.exe")
GW_OWNER = 4
MIN_PLAYER_EDGE = 120        # 이보다 작은 창은 에뮬레이터 본체가 아니다


def _process_name(pid, cache):
    if pid in cache:
        return cache[pid]
    name = ""
    h = _k32.OpenProcess(0x1000, False, pid)     # QUERY_LIMITED_INFORMATION
    if h:
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buf))
            if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                name = os.path.basename(buf.value).lower()
        finally:
            _k32.CloseHandle(h)
    cache[pid] = name
    return name


def player_windows():
    """지금 살아 있는 LDPlayer 인스턴스 창 전부 — [{hwnd, pid, title}]."""
    return top_windows(exes=PLAYER_EXES)


def top_windows(pid=None, exes=None, min_edge=MIN_PLAYER_EDGE):
    """조건에 맞는 top-level 창 목록 — [{hwnd, pid, title}].

    숨겨졌거나 화면 밖으로 치워진 창도 포함한다(크래시 잔재 복구에 필요).
    소유자 있는 창(대화상자)·작은 창은 걸러 본체만 남긴다.
    exes 를 주면 그 실행파일의 창만, pid 를 주면 그 프로세스의 창만 남긴다.
    """
    if not IS_WINDOWS:
        return []
    found, cache = [], {}

    @_ENUMPROC
    def _cb(hwnd, _lparam):
        try:
            if _u32.GetWindow(hwnd, GW_OWNER):
                return True
            rect = wintypes.RECT()
            if not _u32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
            if (rect.right - rect.left < min_edge
                    or rect.bottom - rect.top < min_edge):
                return True
            wpid = wintypes.DWORD(0)
            _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if pid is not None and wpid.value != pid:
                return True
            if exes is not None and _process_name(wpid.value, cache) not in exes:
                return True
            n = _u32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 2)
            _u32.GetWindowTextW(hwnd, buf, n + 2)
            found.append({"hwnd": int(hwnd), "pid": wpid.value,
                          "title": buf.value.strip()})
        except Exception:
            pass
        return True

    _u32.EnumWindows(_cb, 0)
    return found


def is_window(hwnd):
    if not IS_WINDOWS or not hwnd:
        return False
    return bool(_u32.IsWindow(wintypes.HWND(hwnd)))


def desktop_hwnd():
    return int(_u32.GetDesktopWindow() or 0) if IS_WINDOWS else 0


def _is_top_level(h):
    """부모에서 떨어져 나왔는지 판정.

    SetParent(hwnd, NULL) 뒤에도 WS_CHILD 가 아직 남아 있으면 GetParent 는
    NULL 이 아니라 **바탕화면 핸들**을 돌려준다. 0 인지만 보면 성공을 실패로
    오판한다(실제 서버에서 이 오판이 관측됐다). 바탕화면도 '부모 없음'으로 친다.
    """
    p = int(_u32.GetParent(h) or 0)
    return p == 0 or p == int(_u32.GetDesktopWindow() or 0)


def window_state(hwnd):
    """진단용 창 상태 덤프 — 어디서 어긋났는지 보려면 이걸 찍는다."""
    if not IS_WINDOWS or not is_window(hwnd):
        return {"alive": False}
    h = wintypes.HWND(hwnd)
    rect = wintypes.RECT()
    _u32.GetWindowRect(h, ctypes.byref(rect))
    return {"alive": True,
            "rect": (rect.left, rect.top, rect.right - rect.left,
                     rect.bottom - rect.top),
            "style": hex(_get_long(h, GWL_STYLE) & 0xFFFFFFFF),
            "exstyle": hex(_get_long(h, GWL_EXSTYLE) & 0xFFFFFFFF),
            "visible": bool(_u32.IsWindowVisible(h)),
            "parent": int(_u32.GetParent(h) or 0)}


def is_visible(hwnd):
    if not IS_WINDOWS or not hwnd:
        return False
    return bool(_u32.IsWindowVisible(wintypes.HWND(hwnd)))


PW_RENDERFULLCONTENT = 0x2
BI_RGB = 0
DIB_RGB_COLORS = 0
SRCCOPY = 0x00CC0020
MAX_CAPTURE_EDGE = 4096


def _has_content(raw, w, h):
    """전부 검정(캡처 실패)인지 성긴 샘플링으로 판정 — 전 픽셀 훑으면 비싸다."""
    step = max(4, (w * h) // 2000) * 4
    return any(raw[i:i + 3] != b"\x00\x00\x00"
               for i in range(0, len(raw) - 4, step))


def capture(hwnd):
    """창 픽셀 → (width, height, BGRA bytes). 실패면 None."""
    shot = capture_ex(hwnd)
    return shot[:3] if shot else None


def capture_ex(hwnd):
    """capture() + 어떤 방식으로 떴는지 → (w, h, bytes, method). 실패면 None.

    주의: PrintWindow 는 대상 프로세스에 동기 메시지를 보낸다. LDPlayer 가 hang
    하면 이 호출도 같이 멈추므로 반드시 워커 스레드에서만 부를 것.
    화면이 전부 검정이면(가속 렌더 캡처 실패) None 을 돌려 호출측이 대체
    표시로 넘어가게 한다.
    """
    if not IS_WINDOWS or not is_window(hwnd):
        return None
    h = wintypes.HWND(hwnd)
    rect = wintypes.RECT()
    if not _u32.GetWindowRect(h, ctypes.byref(rect)):
        return None
    w = rect.right - rect.left
    ht = rect.bottom - rect.top
    if w <= 0 or ht <= 0 or w > MAX_CAPTURE_EDGE or ht > MAX_CAPTURE_EDGE:
        return None

    screen_dc = _u32.GetDC(wintypes.HWND(0))
    mem_dc = _gdi.CreateCompatibleDC(screen_dc)
    bmp = old = None
    try:
        bi = _BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bi.biWidth = w
        bi.biHeight = -ht                 # top-down (음수) — 뒤집기 불필요
        bi.biPlanes = 1
        bi.biBitCount = 32
        bi.biCompression = BI_RGB
        bits = ctypes.c_void_p()
        bmp = _gdi.CreateDIBSection(mem_dc, ctypes.byref(bi), DIB_RGB_COLORS,
                                    ctypes.byref(bits), None, 0)
        if not bmp or not bits:
            return None
        old = _gdi.SelectObject(mem_dc, bmp)
        # 가속 렌더 창은 방식에 따라 빈 화면이 나온다. 세 가지를 순서대로 시도해
        # 처음으로 실제 그림이 나오는 것을 쓴다.
        raw = method = None
        for attempt in ("printwindow-full", "printwindow", "bitblt"):
            if attempt == "printwindow-full":
                ok = _u32.PrintWindow(h, mem_dc, PW_RENDERFULLCONTENT)
            elif attempt == "printwindow":
                ok = _u32.PrintWindow(h, mem_dc, 0)
            else:
                src = _u32.GetWindowDC(h)
                if not src:
                    continue
                try:
                    ok = _gdi.BitBlt(mem_dc, 0, 0, w, ht, src, 0, 0, SRCCOPY)
                finally:
                    _u32.ReleaseDC(h, src)
            if not ok:
                continue
            got = ctypes.string_at(bits, w * ht * 4)
            if _has_content(got, w, ht):
                raw, method = got, attempt
                break
        if raw is None:
            return None
    finally:
        if old:
            _gdi.SelectObject(mem_dc, old)
        if bmp:
            _gdi.DeleteObject(bmp)
        _gdi.DeleteDC(mem_dc)
        _u32.ReleaseDC(wintypes.HWND(0), screen_dc)

    return w, ht, raw, method


class Embedder:
    """붙인 창의 원래 상태를 기억했다가 그대로 되돌려주는 관리자."""

    def __init__(self):
        self._saved = {}        # 부착한 창: hwnd -> (style, exstyle)
        self._stowed = {}       # 화면 밖으로 치운 창: hwnd -> exstyle
        self._home = {}         # 창의 진짜 원위치: hwnd -> (x, y, w, h)

    def _remember_home(self, hwnd):
        """창을 처음 건드릴 때의 화면상 위치·크기를 한 번만 기록한다.

        이미 치워둔(-32000) 상태에서 부착하면 그 좌표가 '원위치'로 굳어
        복원 때 화면 밖으로 돌아가 버린다. 그래서 최초 1회만 기록하고,
        그 시점에 이미 화면 밖이면 안전한 기본 위치를 쓴다.
        """
        if hwnd in self._home:
            return self._home[hwnd]
        rect = wintypes.RECT()
        _u32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
        w = max(1, rect.right - rect.left)
        h = max(1, rect.bottom - rect.top)
        if rect.left <= STOW_DETECT or rect.top <= STOW_DETECT:
            home = (80, 80, w, h)
        else:
            home = (rect.left, rect.top, w, h)
        self._home[hwnd] = home
        return home

    # -- 붙이기/떼기 --------------------------------------------------------
    def embed(self, hwnd, host_hwnd, width, height):
        """hwnd 를 host_hwnd 의 자식으로 만든다. 성공 시 True."""
        if not IS_WINDOWS or not is_window(hwnd) or not host_hwnd:
            return False
        if hwnd in self._saved:
            self.fit(hwnd, width, height)
            return True

        h = wintypes.HWND(hwnd)
        self._remember_home(hwnd)
        stow_ex = self._stowed.pop(hwnd, None)   # 치워둔 창이면 부착과 함께 되살아난다
        style = _get_long(h, GWL_STYLE)
        # 치워둘 때 바꾼 exstyle 이 아니라 그 이전 값을 원본으로 삼는다
        exstyle = stow_ex if stow_ex is not None else _get_long(h, GWL_EXSTYLE)
        self._saved[hwnd] = (style, exstyle)

        _set_long(h, GWL_STYLE, (style & ~_DECORATIONS) | WS_CHILD)
        _set_long(h, GWL_EXSTYLE, exstyle & ~WS_EX_APPWINDOW)
        # SetParent 는 성공/실패가 아니라 '이전 부모'를 돌려준다. top-level 창은
        # 이전 부모가 NULL 이므로 성공해도 0 이 나온다. 반환값으로 판정하면 안 되고
        # 실제로 부모가 바뀌었는지를 봐야 한다.
        _u32.SetParent(h, wintypes.HWND(host_hwnd))
        if int(_u32.GetParent(h) or 0) != int(host_hwnd):
            # 실패하면 원상복구하고 포기(반쯤 망가진 창을 남기지 않는다)
            _u32.SetParent(h, wintypes.HWND(0))
            _set_long(h, GWL_STYLE, style)
            _set_long(h, GWL_EXSTYLE, exstyle)
            x, y, ww, hh = self._home.get(hwnd, (80, 80, 900, 1600))
            _u32.SetWindowPos(h, wintypes.HWND(0), x, y, ww, hh,
                              SWP_FRAMECHANGED | SWP_NOZORDER | SWP_NOACTIVATE)
            _u32.ShowWindow(h, SW_SHOWNORMAL)
            self._saved.pop(hwnd, None)
            return False
        self.fit(hwnd, width, height)
        return True

    def release(self, hwnd):
        """원래 top-level 창으로 되돌린다. 창이 이미 죽었으면 기록만 지운다."""
        saved = self._saved.pop(hwnd, None)
        if saved is None or not IS_WINDOWS:
            return False
        if not is_window(hwnd):
            return False
        style, exstyle = saved
        x, y, w, h_ = self._home.get(hwnd, (80, 80, 900, 1600))
        hw = wintypes.HWND(hwnd)
        _u32.SetParent(hw, wintypes.HWND(0))
        if not _is_top_level(hw):
            # 떼내기 실패 — 스타일까지 바꾸면 자식인 채 장식만 붙은 괴상한 창이
            # 된다. 기록을 되돌려 놓고(종료 때 한 번 더 시도) 그대로 둔다.
            self._saved[hwnd] = saved
            _log(f"[ldwin] SetParent 해제 실패 hwnd={hwnd} "
                 f"err={ctypes.get_last_error()}")
            return False
        _set_long(hw, GWL_STYLE, style)
        _set_long(hw, GWL_EXSTYLE, exstyle)
        _u32.SetWindowPos(hw, wintypes.HWND(0), x, y, w, h_,
                          SWP_FRAMECHANGED | SWP_NOZORDER | SWP_NOACTIVATE)
        _u32.ShowWindow(hw, SW_SHOWNORMAL)
        return True

    def release_all(self):
        for hwnd in list(self._saved):
            try:
                self.release(hwnd)
            except Exception:
                self._saved.pop(hwnd, None)

    # -- 레이아웃 -----------------------------------------------------------
    def fit(self, hwnd, width, height):
        """호스트 위젯 크기에 맞춰 자식 창을 채운다."""
        if not IS_WINDOWS or hwnd not in self._saved or not is_window(hwnd):
            return
        _u32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(0), 0, 0,
                          max(1, int(width)), max(1, int(height)),
                          SWP_FRAMECHANGED | SWP_SHOWWINDOW | SWP_NOZORDER
                          | SWP_NOACTIVATE)

    def focus(self, hwnd):
        """키보드 입력이 에뮬레이터로 가도록 포커스만 넘긴다."""
        if IS_WINDOWS and is_window(hwnd):
            _u32.SetFocus(wintypes.HWND(hwnd))

    def attached(self):
        return list(self._saved)

    # -- 창 치우기(stow) ----------------------------------------------------
    # SW_HIDE 대신 화면 밖으로 옮긴다. 숨긴 창은 PrintWindow 가 빈 화면을 돌려줘
    # 썸네일이 죽지만, 보이되 화면 밖에 있는 창은 정상적으로 캡처된다.
    def stow(self, hwnd):
        """인스턴스 창을 화면 밖 + 작업표시줄 밖으로 치운다(프로세스는 그대로)."""
        if not IS_WINDOWS or not is_window(hwnd) or hwnd in self._saved:
            return False
        if hwnd in self._stowed:
            return True
        h = wintypes.HWND(hwnd)
        self._remember_home(hwnd)
        exstyle = _get_long(h, GWL_EXSTYLE)
        self._stowed[hwnd] = exstyle

        # 작업표시줄 항목 제거는 창을 잠깐 숨겼다 다시 띄워야 반영된다.
        _u32.ShowWindow(h, SW_HIDE)
        _set_long(h, GWL_EXSTYLE,
                  (exstyle | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
        _u32.SetWindowPos(h, wintypes.HWND(0), STOW_POS, STOW_POS, 0, 0,
                          SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
                          | SWP_FRAMECHANGED)
        _u32.ShowWindow(h, SW_SHOWNA)
        return True

    def unstow(self, hwnd):
        """치워둔 창을 원래 자리·작업표시줄로 되돌린다."""
        saved = self._stowed.pop(hwnd, None)
        if saved is None or not IS_WINDOWS or not is_window(hwnd):
            return False
        exstyle = saved
        x, y = self._home.get(hwnd, (80, 80, 0, 0))[:2]
        h = wintypes.HWND(hwnd)
        _u32.ShowWindow(h, SW_HIDE)
        _set_long(h, GWL_EXSTYLE, exstyle)
        _u32.SetWindowPos(h, wintypes.HWND(0), x, y, 0, 0,
                          SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
                          | SWP_FRAMECHANGED)
        _u32.ShowWindow(h, SW_SHOWNORMAL)
        return True

    def unstow_all(self):
        for hwnd in list(self._stowed):
            try:
                self.unstow(hwnd)
            except Exception:
                self._stowed.pop(hwnd, None)

    def stowed(self):
        return list(self._stowed)

    def prune(self):
        """죽은 창의 기록을 버린다(장시간 구동 시 dict 무한 증가 방지)."""
        for d in (self._saved, self._stowed, self._home):
            for hwnd in [h for h in d if not is_window(h)]:
                d.pop(hwnd, None)


def is_stowed(hwnd):
    """화면 밖으로 치워진 창인가. 좌표만 보면 되므로 기록 없이도 판정된다."""
    if not IS_WINDOWS or not is_window(hwnd):
        return False
    rect = wintypes.RECT()
    if not _u32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return False
    return rect.left <= STOW_DETECT


def rescue(hwnd):
    """치워진 채 남은 창을 화면으로 되살린다.

    앱이 크래시로 죽으면 stow 기록이 사라지고 창만 화면 밖에 남는다. LDPlayer 가
    스스로 창을 -32000 좌표로 보내는 일은 없으므로, 시작할 때 그런 창을 발견하면
    우리가 남긴 잔재로 보고 복구한다. 숨김(SW_HIDE) 상태로 남은 창도 같이 되살린다.
    """
    if not IS_WINDOWS or not is_window(hwnd):
        return False
    h = wintypes.HWND(hwnd)
    if not is_stowed(hwnd) and is_visible(hwnd):
        return False
    exstyle = _get_long(h, GWL_EXSTYLE)
    _u32.ShowWindow(h, SW_HIDE)
    _set_long(h, GWL_EXSTYLE, (exstyle | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW)
    _u32.SetWindowPos(h, wintypes.HWND(0), 80, 80, 0, 0,
                      SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
    _u32.ShowWindow(h, SW_SHOWNORMAL)
    return True

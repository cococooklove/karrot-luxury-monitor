"""Win32 를 흉내 낸 가짜 백엔드로 ldwin 의 창 상태머신을 검증한다.

실제 Windows 없이도 잡을 수 있는 것 — 그리고 반드시 잡아야 하는 것:
  · 부착/치우기 뒤에 창이 원래 스타일·위치·표시상태로 정확히 돌아오는가
  · 중간에 실패했을 때 반쯤 망가진 상태로 남지 않는가
  · 크래시 잔재(화면 밖·숨김)를 다음 실행에서 되살리는가
LDPlayer 가 실제로 그려지는지·키입력이 먹는지는 여기서 알 수 없다(ldwin_probe.py).

가짜 API 는 실제 Win32 의 반환값 규약을 따른다. 특히 SetParent 는 성공/실패가
아니라 '이전 부모'를 돌려주므로, top-level 창을 자식으로 만들면 성공해도 0 이
나온다 — 반환값으로 성패를 판정하면 여기서 걸린다.
"""

import ldwin

GWL_STYLE, GWL_EXSTYLE = -16, -20
SWP_NOSIZE, SWP_NOMOVE, SWP_SHOWWINDOW = 0x1, 0x2, 0x40


class FakeWin32:
    """창 몇 개짜리 가짜 윈도우 매니저."""

    def __init__(self):
        self.windows = {}
        self.fail_setparent_to = None      # 이 부모로의 SetParent 는 실패시킨다

    def add(self, hwnd, x=300, y=200, w=360, h=640,
            style=0x14CF0000, exstyle=ldwin.WS_EX_APPWINDOW):
        self.windows[hwnd] = {"x": x, "y": y, "w": w, "h": h, "style": style,
                              "exstyle": exstyle, "visible": True, "parent": 0}
        return hwnd

    def snapshot(self, hwnd):
        return dict(self.windows[hwnd])

    # -- user32 --
    def IsWindow(self, h):
        return 1 if h in self.windows else 0

    def IsWindowVisible(self, h):
        w = self.windows.get(h)
        return 1 if w and w["visible"] else 0

    def GetWindowRect(self, h, rect):
        w = self.windows.get(h)
        if not w:
            return 0
        rect.left, rect.top = w["x"], w["y"]
        rect.right, rect.bottom = w["x"] + w["w"], w["y"] + w["h"]
        return 1

    def GetParent(self, h):
        w = self.windows.get(h)
        return w["parent"] if w else 0

    def SetParent(self, h, parent):
        w = self.windows.get(h)
        if not w:
            return 0
        prev = w["parent"]
        if self.fail_setparent_to is not None and parent == self.fail_setparent_to:
            return 0                       # 실패: 부모를 바꾸지 않고 NULL 반환
        w["parent"] = parent
        return prev                        # 성공: 이전 부모(top-level 이면 0)

    def SetWindowPos(self, h, _after, x, y, cx, cy, flags):
        w = self.windows.get(h)
        if not w:
            return 0
        if not flags & SWP_NOMOVE:
            w["x"], w["y"] = x, y
        if not flags & SWP_NOSIZE:
            w["w"], w["h"] = cx, cy
        if flags & SWP_SHOWWINDOW:
            w["visible"] = True
        return 1

    def ShowWindow(self, h, cmd):
        w = self.windows.get(h)
        if not w:
            return 0
        w["visible"] = cmd != ldwin.SW_HIDE
        return 1

    def SetFocus(self, h):
        return h


class FakeCtypes:
    @staticmethod
    def get_last_error():
        return 0

    @staticmethod
    def byref(x):
        return x


class FakeRect:
    left = top = right = bottom = 0


class FakeWintypes:
    RECT = FakeRect

    @staticmethod
    def HWND(v):
        return v


def install(fake):
    """ldwin 을 가짜 백엔드로 갈아끼운다."""
    ldwin.IS_WINDOWS = True
    ldwin._u32 = fake
    ldwin.ctypes = FakeCtypes
    ldwin.wintypes = FakeWintypes
    ldwin._get_long = lambda h, which: fake.windows[h][
        "style" if which == GWL_STYLE else "exstyle"]

    def _set(h, which, val):
        fake.windows[h]["style" if which == GWL_STYLE else "exstyle"] = val
    ldwin._set_long = _set


def setup():
    fake = FakeWin32()
    install(fake)
    return fake, ldwin.Embedder()


# ── 부착 왕복 ────────────────────────────────────────────────────────────────

def test_embed_then_release_restores_everything():
    fake, emb = setup()
    fake.add(1); fake.add(999)                       # 999 = 호스트 위젯
    before = fake.snapshot(1)

    assert emb.embed(1, 999, 400, 700) is True       # SetParent 가 0(=이전부모)을
    assert fake.windows[1]["parent"] == 999          # 돌려줘도 성공으로 봐야 한다
    assert fake.windows[1]["style"] & ldwin.WS_CHILD
    assert not fake.windows[1]["style"] & ldwin.WS_CAPTION
    assert (fake.windows[1]["w"], fake.windows[1]["h"]) == (400, 700)

    assert emb.release(1) is True
    after = fake.snapshot(1)
    assert after == before, (before, after)
    assert emb.attached() == []


def test_embed_failure_leaves_window_untouched():
    fake, emb = setup()
    fake.add(1); fake.add(999)
    fake.fail_setparent_to = 999
    before = fake.snapshot(1)

    assert emb.embed(1, 999, 400, 700) is False
    assert fake.snapshot(1) == before, fake.snapshot(1)
    assert emb.attached() == []


def test_release_failure_keeps_record_for_retry():
    fake, emb = setup()
    fake.add(1); fake.add(999)
    emb.embed(1, 999, 400, 700)

    fake.fail_setparent_to = 0                       # 떼내기가 실패하는 상황
    assert emb.release(1) is False
    assert 1 in emb.attached(), "재시도할 수 있게 기록이 남아야 한다"
    assert fake.windows[1]["parent"] == 999          # 어정쩡하게 안 건드림

    fake.fail_setparent_to = -1                      # 종료 시 재시도 → 복구
    emb.release_all()
    assert fake.windows[1]["parent"] == 0
    assert emb.attached() == []


# ── 창 치우기 왕복 ───────────────────────────────────────────────────────────

def test_stow_then_unstow_restores_position_and_taskbar():
    fake, emb = setup()
    fake.add(1)
    before = fake.snapshot(1)

    assert emb.stow(1) is True
    assert fake.windows[1]["x"] == ldwin.STOW_POS
    assert fake.windows[1]["exstyle"] & ldwin.WS_EX_TOOLWINDOW   # 작업표시줄에서 제거
    assert not fake.windows[1]["exstyle"] & ldwin.WS_EX_APPWINDOW
    assert fake.windows[1]["visible"], "보이되 화면 밖 — 그래야 썸네일이 잡힌다"
    assert ldwin.is_stowed(1)

    assert emb.unstow(1) is True
    assert fake.snapshot(1) == before, fake.snapshot(1)


def test_stowed_window_attached_then_released_comes_back_on_screen():
    """회귀: 치워둔 창을 부착하면 -32000 이 '원위치'로 굳어 복원 때 화면 밖으로
    사라지던 버그. 원위치는 최초 1회만 기록해야 한다."""
    fake, emb = setup()
    fake.add(1, x=300, y=200); fake.add(999)
    home = (fake.windows[1]["x"], fake.windows[1]["y"])

    emb.stow(1)
    assert emb.embed(1, 999, 400, 700) is True
    assert emb.release(1) is True

    assert (fake.windows[1]["x"], fake.windows[1]["y"]) == home
    assert not ldwin.is_stowed(1)
    assert fake.windows[1]["visible"]
    assert fake.windows[1]["exstyle"] & ldwin.WS_EX_APPWINDOW, "작업표시줄 복귀"


def test_shutdown_restores_mixed_state():
    """종료 경로 — 부착 2개 + 치움 2개가 섞여 있어도 전부 원상복구."""
    fake, emb = setup()
    fake.add(999)
    originals = {}
    for h in (1, 2, 3, 4):
        fake.add(h, x=100 + h * 10, y=50 + h)
        originals[h] = fake.snapshot(h)
    emb.stow(3); emb.stow(4)
    emb.embed(1, 999, 400, 700); emb.embed(2, 999, 400, 700)

    emb.release_all(); emb.unstow_all()

    for h in (1, 2, 3, 4):
        assert fake.snapshot(h) == originals[h], (h, fake.snapshot(h))


# ── 크래시 잔재 복구 ─────────────────────────────────────────────────────────

def test_rescue_offscreen_leftover():
    fake, emb = setup()
    fake.add(1)
    emb.stow(1)
    fake2, _ = fake, None                    # 앱이 죽어 기록만 사라진 상황
    emb2 = ldwin.Embedder()                  # 새 세션

    assert ldwin.rescue(1) is True
    assert not ldwin.is_stowed(1)
    assert fake2.windows[1]["visible"]
    assert fake2.windows[1]["exstyle"] & ldwin.WS_EX_APPWINDOW
    assert not fake2.windows[1]["exstyle"] & ldwin.WS_EX_TOOLWINDOW
    assert emb2.attached() == []


def test_rescue_hidden_leftover_and_skips_healthy_window():
    fake, emb = setup()
    fake.add(1); fake.add(2)
    fake.windows[1]["visible"] = False       # SW_HIDE 로 남은 잔재

    assert ldwin.rescue(1) is True
    assert fake.windows[1]["visible"]
    assert ldwin.rescue(2) is False, "멀쩡한 창은 건드리지 않는다"


def test_prune_drops_dead_handles():
    fake, emb = setup()
    fake.add(1); fake.add(2); fake.add(999)
    emb.embed(1, 999, 400, 700)
    emb.stow(2)

    del fake.windows[1]; del fake.windows[2]     # 인스턴스가 꺼진 상황
    emb.prune()
    assert emb.attached() == [] and emb.stowed() == []


def test_fit_only_touches_attached_windows():
    fake, emb = setup()
    fake.add(1); fake.add(999)
    before = fake.snapshot(1)
    emb.fit(1, 800, 800)                     # 부착 안 된 창은 무시
    assert fake.snapshot(1) == before
    emb.embed(1, 999, 400, 700)
    emb.fit(1, 500, 900)
    assert (fake.windows[1]["w"], fake.windows[1]["h"]) == (500, 900)


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    raise SystemExit(1 if fails else 0)

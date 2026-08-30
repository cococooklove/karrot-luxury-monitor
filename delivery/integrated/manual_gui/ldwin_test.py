"""ldwin.parse_list2 검증 — Win32 없이(맥/리눅스 포함) 돌아가는 순수 로직 테스트."""

import ldwin


def test_normal():
    out = ("0,LDPlayer,131354,131356,1,10256,10932\n"
           "1,LDPlayer-1,0,0,0,0,0\n")
    rows = ldwin.parse_list2(out)
    assert len(rows) == 2, rows
    a, b = rows
    assert a == {"index": 0, "name": "LDPlayer", "top_hwnd": 131354,
                 "bind_hwnd": 131356, "running": True, "pid": 10256}, a
    assert b["running"] is False and b["top_hwnd"] == 0, b


def test_garbage_lines_ignored():
    out = ("dnconsole version 9.0\n"
           "\n"
           "not,a,row\n"
           "2,계정C,999,1000,1,777,888\n")
    rows = ldwin.parse_list2(out)
    assert [r["index"] for r in rows] == [2], rows
    assert rows[0]["name"] == "계정C"


def test_short_and_broken_fields():
    # 필드 모자람 / 숫자 아님 → 0 으로 떨어지고 예외 없음
    rows = ldwin.parse_list2("3,이름만있음\n4,X,abc,,1\n")
    assert rows[0]["top_hwnd"] == 0 and rows[0]["running"] is False
    assert rows[1]["top_hwnd"] == 0 and rows[1]["running"] is True


def test_empty():
    assert ldwin.parse_list2("") == []
    assert ldwin.parse_list2(None) == []


# ── resolve_instances: list2 필드 순서를 믿지 않고 실제 창과 대조하는 로직 ──

W1 = {"hwnd": 111, "pid": 900, "title": "LDPlayer"}
W2 = {"hwnd": 222, "pid": 901, "title": "계정2"}


def _row(**kw):
    base = {"index": 0, "name": "LDPlayer", "top_hwnd": 111, "bind_hwnd": 5,
            "running": True, "pid": 900}
    base.update(kw)
    return base


def test_resolve_trusts_matching_handle():
    out = ldwin.resolve_instances([_row()], [W1, W2])
    assert out[0]["top_hwnd"] == 111 and out[0]["running"] is True, out


def test_resolve_recovers_from_wrong_field_order():
    # 필드가 밀려 top_hwnd 자리에 엉뚱한 값(bind hwnd/pid 등)이 들어온 경우
    out = ldwin.resolve_instances([_row(top_hwnd=5, pid=0)], [W1, W2])
    assert out[0]["top_hwnd"] == 111, out          # 제목으로 되찾는다
    out = ldwin.resolve_instances(
        [_row(name="이름다름", top_hwnd=99999, pid=900)], [W1, W2])
    assert out[0]["top_hwnd"] == 111, out          # PID 로 되찾는다


def test_resolve_marks_missing_window_not_running():
    # list2 는 실행 중이라는데 창이 없다 → 보여줄 화면이 없으므로 running=False
    out = ldwin.resolve_instances([_row(name="없는놈", top_hwnd=0, pid=0)], [W2])
    assert out[0]["running"] is False and out[0]["top_hwnd"] == 0, out


def test_resolve_handle_belonging_to_other_instance():
    # 핸들이 남의 인스턴스를 가리키면(교차검증 실패) 제목 우선으로 바로잡는다
    out = ldwin.resolve_instances([_row(name="계정2", top_hwnd=111, pid=901)],
                                  [W1, W2])
    assert out[0]["top_hwnd"] == 222, out


def test_player_windows_empty_off_windows():
    if ldwin.IS_WINDOWS:      # 가짜 백엔드가 끼워진 뒤라면(sim 테스트와 한 프로세스) 건너뜀
        return
    assert ldwin.player_windows() == []
    assert ldwin.list_instances(None) == []


def test_non_windows_is_safe():
    # 개발 머신(맥)에서 import·호출만으로 죽지 않아야 한다
    if ldwin.IS_WINDOWS:
        return
    e = ldwin.Embedder()
    assert e.embed(123, 456, 100, 100) is False
    assert e.release(123) is False
    e.fit(123, 10, 10)
    e.focus(123)
    e.release_all()
    assert e.attached() == []
    assert e.stow(123) is False
    assert e.unstow(123) is False
    e.unstow_all()
    assert e.stowed() == []
    assert ldwin.is_stowed(123) is False
    assert ldwin.rescue(123) is False
    assert ldwin.capture(123) is None


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

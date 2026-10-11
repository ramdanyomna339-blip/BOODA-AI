from types import SimpleNamespace

import pytest

from core.desktop_control import WindowsDesktopBackend


def make_backend(send):
    obj = WindowsDesktopBackend.__new__(WindowsDesktopBackend)
    obj.ui = SimpleNamespace(failSafeCheck=lambda: None)
    obj.target = lambda: {"window": 1}
    obj.review_target = obj.target
    obj.user32 = SimpleNamespace(SendInput=send)
    return obj


def test_arabic_utf16_units_and_key_release_are_preserved(monkeypatch):
    packets, delays = [], []
    def send(count, events, size):
        packets.append([(event.data.ki.scan, event.data.ki.flags) for event in events])
        return count
    monkeypatch.setattr("core.desktop_control.time.sleep", delays.append)
    text = "اختبار بودا: كل خطوة بموافقتي. 🙂"
    make_backend(send)._unicode(text)
    raw = text.encode("utf-16-le")
    units = [int.from_bytes(raw[i:i+2], "little") for i in range(0, len(raw), 2)]
    assert packets == [[(unit, flag)] for unit in units for flag in (4, 6)]
    assert len(delays) == 2 * len(units) and min(delays) >= .05


def test_partial_unicode_send_stops_without_retry(monkeypatch):
    calls = []
    monkeypatch.setattr("core.desktop_control.time.sleep", lambda delay: None)
    def send(*args):
        calls.append(1)
        return 0
    with pytest.raises(RuntimeError, match="incomplete"):
        make_backend(send)._unicode("اختبار")
    assert len(calls) == 1


def test_editor_title_change_during_typing_is_allowed(monkeypatch):
    packets = []
    obj = make_backend(lambda *args: packets.append(1) or 1)
    original = {"window": 1, "pid": 2, "bounds": [0, 0, 100, 100], "title": "Untitled"}
    obj.review_target = lambda: original
    obj.target = lambda: dict(original, title="اختبار")
    monkeypatch.setattr("core.desktop_control.time.sleep", lambda delay: None)
    obj._unicode("اختبار")
    assert len(packets) == 12


@pytest.mark.parametrize("field,value", [("window", 9), ("pid", 9), ("bounds", [1, 1, 101, 101])])
def test_changed_window_process_or_bounds_stop_input(monkeypatch, field, value):
    obj = make_backend(lambda *args: pytest.fail("input sent to changed target"))
    original = {"window": 1, "pid": 2, "bounds": [0, 0, 100, 100]}
    obj.review_target = lambda: original
    obj.target = lambda: dict(original, **{field: value})
    with pytest.raises(RuntimeError, match="Window changed"):
        obj._unicode("اختبار")


def test_interrupted_hold_still_releases_key_and_does_not_continue(monkeypatch):
    flags = []
    def send(count, events, size):
        flags.append(events[0].data.ki.flags)
        return count
    def interrupt(delay):
        raise KeyboardInterrupt()
    monkeypatch.setattr("core.desktop_control.time.sleep", interrupt)
    with pytest.raises(KeyboardInterrupt):
        make_backend(send)._unicode("بودا")
    assert flags == [4, 6]


def test_failed_release_does_not_send_another_character(monkeypatch):
    flags = []
    def send(count, events, size):
        flags.append(events[0].data.ki.flags)
        return 1 if len(flags) == 1 else 0
    monkeypatch.setattr("core.desktop_control.time.sleep", lambda delay: None)
    with pytest.raises(RuntimeError, match="release incomplete"):
        make_backend(send)._unicode("بودا")
    assert flags == [4, 6]

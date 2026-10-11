from pathlib import Path
from types import SimpleNamespace
import pytest
from core.desktop_control import WindowsDesktopBackend


def backend(tmp_path):
    obj = WindowsDesktopBackend.__new__(WindowsDesktopBackend)
    obj.ui = SimpleNamespace(size=lambda: (1920, 1080))
    obj.selected_window = None
    obj.media_root = tmp_path
    return obj


@pytest.mark.parametrize("op,params", [
    ("type", {"text": "do this\n"}), ("type", {"text": "x" * 2001}),
    ("key", {"key": "win+r"}), ("key", {"key": "delete"}),
    ("click", {"x": 0, "y": 20, "button": "left"}),
    ("click", {"x": 2000, "y": 20, "button": "left"}),
    ("move", {"x": True, "y": 20}),
    ("scroll", {"amount": 200, "x": 20, "y": 20}),
    ("open_url", {"url": "file:///C:/something"}),
    ("open_url", {"url": "https://127.0.0.1/"}),
    ("open_url", {"url": "https://localhost/"}),
    ("open_url", {"url": "https://user:pass@example.com"}),
    ("search", {"query": ""}),
    ("observe", {"extra": "data"}),
    ("watch", {"duration": 10000, "interval": 10, "endpoint": "http://127.0.0.1:11434", "model": "local"}),
])
def test_backend_rejects_bad_inputs_without_calling_native_ui(tmp_path, op, params):
    with pytest.raises(ValueError):
        backend(tmp_path).validate(op, params)


def test_scoped_media_does_not_escape(tmp_path):
    obj = backend(tmp_path)
    (tmp_path / "audio.wav").write_bytes(b"example")
    assert obj._media("audio.wav") == tmp_path / "audio.wav"
    for path in ["../elsewhere.wav", "C:/elsewhere.wav", "audio.wav:stream", "missing.wav"]:
        with pytest.raises((ValueError, OSError)):
            obj._media(path)


def test_points_must_stay_in_selected_window(tmp_path):
    obj = backend(tmp_path)
    obj.selected_window = {"window": 10, "bounds": [100, 100, 500, 500]}
    obj.review_target = lambda: obj.selected_window
    with pytest.raises(ValueError):
        obj.validate("move", {"x": 700, "y": 200})
    obj.validate("move", {"x": 200, "y": 200})


def test_missing_process_id_cannot_be_treated_as_a_valid_target(tmp_path):
    obj = backend(tmp_path)
    obj.user32 = SimpleNamespace(GetWindowTextW=lambda hwnd, buffer, size: None,
                                 GetWindowThreadProcessId=lambda hwnd, pointer: 0)
    with pytest.raises(ValueError, match="valid process"):
        obj._window(123)


@pytest.mark.parametrize("mode", [None, False])
def test_read_only_assist_never_starts_text_model(tmp_path, monkeypatch, mode):
    from contextlib import contextmanager
    @contextmanager
    def vision_runtime():
        yield "http://127.0.0.1:8081/v1"
    monkeypatch.setattr("core.vision_runtime.ensure_screen_vision", vision_runtime)
    monkeypatch.setattr("core.screen_observer.LocalScreenVision", lambda **kwargs:
        SimpleNamespace(describe=lambda *args, **kwargs: "4"))
    monkeypatch.setattr("core.local_model.ensure_local_model_server",
        lambda: pytest.fail("Read-only assist started text model"))
    obj = backend(tmp_path)
    obj.ui.screenshot = lambda: "fake frame"
    monkeypatch.setattr("core.screen_evidence.read_text_evidence", lambda image:
        {"ocr_text": "", "ocr_available": False, "requires_review": True})
    params = {"question": "ما الرقم؟"}
    if mode is not None:
        params["propose"] = mode
    result = obj.perform("assist", params)
    assert result["action"] is None and result["executed"] is False
    assert "4" in result["answer"]
    assert result["answer_source"] == "local_vision"


def test_assist_rejects_non_boolean_proposal_mode(tmp_path):
    with pytest.raises(ValueError):
        backend(tmp_path).validate("assist", {"question": "question", "propose": "yes"})


def test_minimized_window_is_rejected_before_approval(tmp_path):
    obj = backend(tmp_path)
    obj.selected_window = {"window": 1, "pid": 10, "title": "Untitled - Notepad",
                           "bounds": [-32000, -32000, -31801, -31966]}
    obj._window = lambda hwnd: dict(obj.selected_window)
    with pytest.raises(ValueError, match="مصغّرة"):
        obj.review_target()

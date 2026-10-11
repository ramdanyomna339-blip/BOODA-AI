import json
from pathlib import Path
import threading
import time
import urllib.request
import urllib.error
import pytest
from core.arabic_console import ArabicConsole, create_server


def wait_prompt(console):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        state = console.state()
        if state["pending"]:
            return state["pending"]
        time.sleep(.005)
    pytest.fail("no prompt")


def test_arabic_display_preserves_logical_text():
    console = ArabicConsole()
    text = "اختبار بودا: كل خطوة بموافقتي.\nreport-123.txt https://example.com"
    console.write(text)
    assert console.state()["text"] == text


def test_input_is_not_reshaped_and_cannot_be_submitted_twice():
    console = ArabicConsole()
    values = []
    worker = threading.Thread(target=lambda: values.append(console.ask("النص: ")))
    worker.start()
    prompt = wait_prompt(console)
    assert not console.submit("old-id", "موافق")
    assert console.submit(prompt["id"], "اختبار بودا 123")
    assert not console.submit(prompt["id"], "موافق")
    worker.join(2)
    assert values == ["اختبار بودا 123"]


def test_secret_input_not_in_output_or_prompt_state():
    console = ArabicConsole()
    values = []
    worker = threading.Thread(target=lambda: values.append(console.ask("مفتاح API: ", secret=True)))
    worker.start()
    prompt = wait_prompt(console)
    assert prompt["secret"]
    console.submit(prompt["id"], "test-private-value")
    worker.join(2)
    assert "test-private-value" not in json.dumps(console.state())
    assert values == ["test-private-value"]


def test_server_refuses_missing_token_or_cross_origin():
    console = ArabicConsole()
    server, token = create_server(console, {"html": "Arabic UI", "css": "", "js": ""})
    listener = threading.Thread(target=server.serve_forever, daemon=True)
    listener.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with pytest.raises(urllib.error.HTTPError): urllib.request.urlopen(base + "/state")
        request = urllib.request.Request(base + "/state", headers={"X-Booda-Token": token})
        with urllib.request.urlopen(request) as response:
            assert json.load(response)["text"] == ""
        request = urllib.request.Request(base + "/answer", data=b'{}', headers={"X-Booda-Token": token, "Origin": "https://evil.test"})
        with pytest.raises(urllib.error.HTTPError): urllib.request.urlopen(request)
    finally:
        server.shutdown()
        server.server_close()


def test_ui_uses_native_direction_and_safe_text_content():
    root = Path(__file__).resolve().parents[1] / "tools/arabic_ui"
    assert 'lang="ar" dir="rtl"' in (root / "app.html").read_text(encoding="utf-8")
    script = (root / "app.js").read_text(encoding="utf-8")
    assert "output.textContent = state.text" in script
    assert "innerHTML" not in script


@pytest.mark.parametrize("answer,expected", [("لا", False), ("موافق", True)])
def test_approval_in_arabic_ui_still_requires_explicit_answer(monkeypatch, answer, expected):
    import builtins
    from types import SimpleNamespace
    from core.desktop_review import confirm_request
    console, values = ArabicConsole(), []
    monkeypatch.setattr(builtins, "input", console.ask)
    task = SimpleNamespace(metadata={"operation": "type", "parameters": {"text": "اختبار بودا"}, "target": None})
    worker = threading.Thread(target=lambda: values.append(confirm_request(task)))
    worker.start()
    prompt = wait_prompt(console)
    assert not values
    console.submit(prompt["id"], answer)
    worker.join(2)
    assert values == [expected]

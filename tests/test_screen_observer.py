import json
import threading
from types import SimpleNamespace

import pytest
from core.screen_observer import LocalScreenVision, ScreenObservationSession


class Vision:
    def __init__(self):
        self.calls = []
    def describe(self, image, *, previous, question=None):
        self.calls.append((image, previous, question))
        return "visible screen"


def test_unchanged_frame_reuses_analysis_but_new_question_and_changes_do_not():
    data = [b"first"]
    image = SimpleNamespace(mode="RGB", size=(2, 2), tobytes=lambda: data[0])
    vision = Vision()
    session = ScreenObservationSession(lambda: image, vision)
    assert session.step()["analysis_reused"] is False
    assert session.step()["analysis_reused"] is True
    assert len(vision.calls) == 1
    session.ask("ما الرقم؟")
    assert session.step()["analysis_reused"] is False
    assert len(vision.calls) == 2
    assert session.step()["analysis_reused"] is False
    assert len(vision.calls) == 3
    data[0] = b"changed"
    assert session.step()["analysis_reused"] is False
    assert len(vision.calls) == 4
    session.set_paused(True)
    session.set_paused(False)
    assert session.step()["analysis_reused"] is False
    assert len(vision.calls) == 5


def test_capture_that_crosses_deadline_does_not_start_analysis():
    clock = [0]
    vision = Vision()
    def capture():
        clock[0] = 10
        return "frame"
    session = ScreenObservationSession(capture, vision, duration=10, clock=lambda: clock[0])
    assert session.step() is None
    assert not vision.calls
    assert session.stopped.is_set() and session.latest is None


def test_analysis_that_crosses_deadline_does_not_start_reasoning():
    clock = [0]
    reasoning = []
    def describe(image, **kwargs):
        clock[0] = 10
        return "expired evidence"
    session = ScreenObservationSession(lambda: "frame", SimpleNamespace(describe=describe),
        duration=10, clock=lambda: clock[0], reason=lambda *args: reasoning.append(args))
    session.ask("ما الظاهر؟", propose=True)
    assert session.step() is None
    assert not reasoning
    assert session.stopped.is_set() and session.latest is None


def test_watch_stops_at_deadline_and_pause_blocks_capture():
    clock = [0]
    captures = []
    vision = Vision()
    def capture():
        captures.append("frame")
        return "frame"
    session = ScreenObservationSession(capture, vision, duration=10, interval=3, clock=lambda: clock[0])
    assert session.step()["sequence"] == 1
    session.paused.set()
    assert session.step() is None
    assert len(captures) == 1
    session.paused.clear()
    assert session.step()["sequence"] == 2
    assert vision.calls[1][1] == "visible screen"
    clock[0] = 10
    assert session.step() is None
    assert session.latest is None and session.stopped.is_set()
    assert len(captures) == 2


def test_inflight_response_cannot_restart_stopped_observer():
    started, release = threading.Event(), threading.Event()
    def describe(image, *, previous):
        started.set()
        assert release.wait(2)
        return "late result"
    session = ScreenObservationSession(lambda: "frame", SimpleNamespace(describe=describe))
    thread = threading.Thread(target=session.step)
    thread.start()
    assert started.wait(2)
    session.stop()
    release.set()
    thread.join(2)
    assert not thread.is_alive()
    assert session.latest is None and session.sequence == 0


def test_pause_resume_discards_inflight_frame_from_before_pause():
    started, release = threading.Event(), threading.Event()
    def describe(image, *, previous):
        started.set()
        assert release.wait(2)
        return "old screen"
    session = ScreenObservationSession(lambda: "frame", SimpleNamespace(describe=describe))
    thread = threading.Thread(target=session.step)
    thread.start()
    assert started.wait(2)
    session.set_paused(True)
    session.set_paused(False)
    release.set()
    thread.join(2)
    assert session.latest is None and session.sequence == 0


@pytest.mark.parametrize("url", ["https://example.com", "http://localhost:11434", "http://127.0.0.1:11434/path", "http://user@127.0.0.1", "http://127.0.0.1?dest=remote"])
def test_screen_images_cannot_be_sent_to_remote_or_ambiguous_endpoints(url):
    with pytest.raises(ValueError):
        LocalScreenVision(endpoint=url)


def test_vision_request_has_no_tools_and_treats_screen_as_untrusted():
    class Image:
        def copy(self): return self
        def thumbnail(self, size): pass
        def convert(self, mode): return self
        def save(self, buffer, **kwargs): buffer.write(b"synthetic JPEG")
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return json.dumps({"message": {"content": "A clear visual screen description"}}).encode()
    requests = []
    def open_request(request, **kwargs):
        requests.append(request)
        return Response()
    client = LocalScreenVision(endpoint="http://127.0.0.1:11434")
    client.opener = SimpleNamespace(open=open_request)
    assert client.describe(Image()) == "A clear visual screen description"
    payload = json.loads(requests[0].data)
    assert "tools" not in payload
    assert "untrusted" in payload["messages"][0]["content"]
    assert payload["messages"][1]["images"]


def test_openai_vision_template_keeps_image_before_question():
    class Image:
        def copy(self): return self
        def thumbnail(self, size): pass
        def convert(self, mode): return self
        def save(self, buffer, **kwargs): buffer.write(b"synthetic")
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return json.dumps({"choices": [{"message": {"content": "A red square is visible."}}]}).encode()
    requests = []
    def open_request(request, **kwargs):
        requests.append(request)
        return Response()
    client = LocalScreenVision()
    client.opener = SimpleNamespace(open=open_request)
    client.describe(Image())
    payload = json.loads(requests[0].data)
    content = payload["messages"][0]["content"]
    assert [part["type"] for part in content] == ["image_url", "text"]
    assert content[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "tools" not in payload


def test_live_question_uses_new_frame_and_never_executes_proposal():
    calls = []
    def reason(question, description):
        calls.append((question, description))
        return {"answer": "اقتراح فقط", "action": {"operation": "search", "parameters": {"query": "shapes"}}, "executed": False}
    vision = Vision()
    session = ScreenObservationSession(lambda: "new frame", vision, reason=reason)
    session.ask("ابحث عن الظاهر", propose=True)
    result = session.step()
    assert calls == [("ابحث عن الظاهر", "visible screen")]
    assert "ابحث عن الظاهر" in vision.calls[0][2]
    assert result["assistant_reply"]["executed"] is False
    assert session.question == ""
    session.step()
    assert len(calls) == 1
    session.set_paused(True)
    with pytest.raises(ValueError):
        session.ask("question")


def test_bad_reasoning_does_not_stop_observation_or_offer_an_action():
    def bad_reason(question, description):
        raise ValueError("invented evidence")
    session = ScreenObservationSession(lambda: "frame", Vision(), reason=bad_reason)
    session.ask("question", propose=True)
    assert session.step()["assistant_reply"]["action"] is None
    assert not session.stopped.is_set()
    assert session.step()["assistant_reply"] is None


def test_read_only_question_uses_vision_without_starting_text_model():
    def forbidden_reason(*args):
        raise AssertionError("Read-only questions must not start another model")
    session = ScreenObservationSession(lambda: "frame", Vision(), reason=forbidden_reason)
    session.ask("ما الظاهر؟")
    reply = session.step()["assistant_reply"]
    assert "visible screen" in reply["answer"]
    assert reply["action"] is None and reply["executed"] is False
    assert reply["answer_source"] == "local_vision"


def test_proposal_requires_explicit_mode_even_for_action_wording():
    session = ScreenObservationSession(lambda: "frame", Vision(),
        reason=lambda *args: pytest.fail("Proposal mode was not selected"))
    session.ask("ابحث وافتح موقعًا")
    assert session.step()["assistant_reply"]["action"] is None


def test_focused_visual_question_can_have_a_short_numeric_answer():
    class Image:
        def copy(self): return self
        def thumbnail(self, size): pass
        def convert(self, mode): return self
        def save(self, buffer, **kwargs): buffer.write(b"synthetic")
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return json.dumps({"choices": [{"message": {"content": "4"}}]}).encode()
    requests = []
    def open_request(request, **kwargs):
        requests.append(request)
        return Response()
    client = LocalScreenVision()
    client.opener = SimpleNamespace(open=open_request)
    assert client.describe(Image(), question="What number is displayed?") == "4"
    payload = json.loads(requests[0].data)
    assert "What number is displayed?" in payload["messages"][0]["content"][1]["text"]
    with pytest.raises(ValueError):
        client.describe(Image())

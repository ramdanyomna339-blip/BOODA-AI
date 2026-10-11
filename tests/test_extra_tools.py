import pytest
from core.browser_tools import ReviewedBrowser, check_public_address
from core.image_text import read_image_text
from core.tool_readiness import inspect_tools


class Item:
    def is_visible(self): return True
    def is_enabled(self): return True
    def get_attribute(self, name): return None
    def count(self): return 1
    def click(self, **kwargs): self.clicked = True
    def fill(self, text): self.text = text


class Page:
    url = "https://example.com/"
    item = Item()
    def get_by_role(self, *args, **kwargs): return self.item


def browser():
    instance = ReviewedBrowser(Page())
    instance._state = lambda: {"url": "https://example.com/", "title": "test", "text": "test",
                              "elements": [{"role": "button", "name": "بحث"}]}
    return instance


def test_browser_action_consumes_snapshot():
    instance = browser()
    token = instance.read()["snapshot"]
    parameters = {"snapshot": token, "role": "button", "name": "بحث"}
    assert instance.act("browser_click", parameters)["verification_required"]
    with pytest.raises(ValueError): instance.act("browser_click", parameters)


def test_changed_page_refuses_input():
    instance = browser()
    token = instance.read()["snapshot"]
    instance._state = lambda: {"text": "changed"}
    with pytest.raises(ValueError, match="تغيرت"):
        instance.act("browser_click", {"snapshot": token, "role": "button", "name": "بحث"})


def test_expired_snapshot_refuses_input(monkeypatch):
    monkeypatch.setattr("core.browser_tools.time.monotonic", lambda: 0)
    instance = browser()
    token = instance.read()["snapshot"]
    monkeypatch.setattr("core.browser_tools.time.monotonic", lambda: 61)
    with pytest.raises(ValueError):
        instance.act("browser_click", {"snapshot": token, "role": "button", "name": "بحث"})


def test_private_address_refused(monkeypatch):
    monkeypatch.setattr("core.browser_tools.socket.getaddrinfo", lambda *a, **k: [(None, None, None, None, ("127.0.0.1", 443))])
    with pytest.raises(ValueError): check_public_address("https://example.com/")


def test_ocr_review_and_size():
    class Image:
        width = height = 100
    result = read_image_text(Image(), engine=lambda image: ("اختبار بودا", 90))
    assert result["requires_review"] and result["text"] == "اختبار بودا"
    Image.width = 300000
    with pytest.raises(ValueError): read_image_text(Image(), engine=lambda image: ("", 0))


def test_readiness_does_not_claim_live_validation(tmp_path):
    result = inspect_tools(tmp_path)
    assert result["live_tested"] is False
    assert not result["tools"][-1]["installed"]

import pytest
from core.video_sources import discover_video_sources
from core.youtube_captions import youtube_video_id, read_youtube_captions, pinned_youtube_session


class Fetcher:
    def fetch(self, url):
        return {"url": url, "media_type": "text/html", "content": '''<video src="/video.mp4">
        <track kind="captions" src="/ar.vtt" srclang="ar" label="عربي">
        <source src="https://cdn.example.com/video.webm"></video>
        <track src="file:///secret"><script>execute()</script>'''}


def test_discovers_only_sources_without_fetching_them():
    result = discover_video_sources("https://example.com/page", fetcher=Fetcher())
    assert len(result["sources"]) == 3 and not result["downloaded"]
    assert result["sources"][1]["language"] == "ar"
    assert result["sources"][0]["url"] == "https://example.com/video.mp4"


def test_image_sources_are_not_reported_as_video():
    from core.video_sources import VideoLinks
    parser = VideoLinks("https://example.com/")
    parser.feed('<picture><source src="/photo.webp"></picture><video><source src="/video.mp4"></video>')
    assert [row["url"] for row in parser.links] == ["https://example.com/video.mp4"]


@pytest.mark.parametrize("url", ["https://youtu.be/abcdefghijk", "https://www.youtube.com/watch?v=abcdefghijk", "https://www.youtube.com/shorts/abcdefghijk"])
def test_youtube_id(url):
    assert youtube_video_id(url) == "abcdefghijk"


@pytest.mark.parametrize("url", ["https://youtube.com.evil.test/watch?v=abcdefghijk", "https://www.youtube.com/watch?v=short", "https://www.youtube.com/watch?v=abcdefghijk&v=other", "http://youtu.be/abcdefghijk", "https://user:pass@youtu.be/abcdefghijk"])
def test_bad_video_url_rejected(url):
    with pytest.raises(ValueError): youtube_video_id(url)


class Transcript:
    language_code, is_generated = "ar", True
    def to_raw_data(self): return [{"start": 0, "duration": 2, "text": "اختبار بودا"}]


class API:
    def fetch(self, video_id, languages):
        assert video_id == "abcdefghijk" and languages == ["ar"]
        return Transcript()


def test_arabic_captions_distinguished_from_audio():
    result = read_youtube_captions("https://youtu.be/abcdefghijk", api=API())
    assert result["text"] == "اختبار بودا" and result["is_generated"]
    assert not result["audio_transcribed"] and not result["account_used"]


def test_blocking_failure_is_not_success():
    class Blocked:
        def fetch(self, *args, **kwargs): raise RuntimeError("blocked")
    with pytest.raises(RuntimeError, match="تعذر"):
        read_youtube_captions("https://youtu.be/abcdefghijk", api=Blocked())


@pytest.mark.parametrize("url,headers", [("https://evil.test/test", {}), ("https://www.youtube.com/", {"Cookie": "CONSENT=YES"}), ("https://www.youtube.com/", {"Authorization": "secret"})])
def test_transport_rejects_unapproved_hosts_or_credentials(url, headers):
    import requests
    with pinned_youtube_session() as session:
        with pytest.raises(ValueError): session.send(requests.Request("GET", url, headers=headers).prepare())


def test_transport_private_dns_refused(monkeypatch):
    import requests
    monkeypatch.setattr("core.youtube_captions.socket.getaddrinfo", lambda *a, **k: [(None, None, None, None, ("127.0.0.1", 443))])
    with pinned_youtube_session() as session:
        with pytest.raises(ValueError): session.send(requests.Request("GET", "https://www.youtube.com/").prepare())


def test_transport_pins_validated_address_and_refuses_redirect(monkeypatch):
    import requests
    called = []
    class Source:
        status = 302
        def getheader(self, *args): return "identity"
    class Connection:
        def __init__(self, host, address): called.append((host, address))
        def request(self, *args, **kwargs): pass
        def getresponse(self): return Source()
        def close(self): called.append("closed")
    monkeypatch.setattr("core.youtube_captions.socket.getaddrinfo", lambda *a, **k: [(None, None, None, None, ("8.8.8.8", 443))])
    monkeypatch.setattr("core.youtube_captions._PinnedHTTPS", Connection)
    with pinned_youtube_session() as session:
        with pytest.raises(ValueError): session.send(requests.Request("GET", "https://www.youtube.com/").prepare())
    assert called == [("www.youtube.com", "8.8.8.8"), "closed"]


@pytest.mark.parametrize("operation", ["discover_video", "youtube_captions"])
def test_video_operations_require_approval(operation):
    from core.desktop_control import BoodaDesktopController, DESKTOP_PERMISSION
    from core.permission_manager import BoodaPermissionManager
    class Backend:
        def validate(self, *args): pass
        def target(self): return None
        def perform(self, *args): pytest.fail("no approval")
    permissions = BoodaPermissionManager()
    permissions.add_permission(DESKTOP_PERMISSION, allowed=True, risk_level="high")
    controller = BoodaDesktopController(Backend())
    task = controller.prepare(operation)
    assert controller.execute(task, permission_manager=permissions) is None

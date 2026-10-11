from email.message import Message

import pytest

from core.research_web import PublicTextFetcher, WebSearch, public_url, source_from_response


@pytest.mark.parametrize("url", ["http://example.com", "https://user:pass@example.com", "https://example.com:444/",
                                    "file:///secret", "https://example.com/\nsecret"])
def test_rejects_unsafe_urls(url):
    with pytest.raises(ValueError):
        public_url(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "192.168.1.1", "::1"])
def test_rejects_private_dns_before_any_connection(monkeypatch, address):
    monkeypatch.setattr("core.research_web.socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (address, 443))])
    monkeypatch.setattr("core.research_web._PinnedHTTPS", lambda *a: pytest.fail("Must not connect"))
    with pytest.raises(ValueError):
        PublicTextFetcher().fetch("https://example.test/")


def test_extraction_removes_scripts_and_keeps_source_metadata():
    source = source_from_response({"url": "https://example.com/article", "media_type": "text/html",
        "content": "<title>Title</title><nav>menu</nav><script>secret()</script><p>Useful evidence.</p>",
        "updated_at": "date"})
    assert source["title"] == "Title" and source["text"] == "Useful evidence."
    assert source["publisher"] == "example.com" and source["updated_at"] == "date"


def test_web_discovery_fetches_real_pages_not_snippets():
    class Fetcher:
        calls = []
        def fetch(self, url):
            self.calls.append(url)
            if "duckduckgo.com" in url:
                return {"content": '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Farticle">Result</a>'}
            return {"url": url, "content": "<title>Source</title><p>Evidence from page.</p>", "media_type": "text/html"}
    fetcher = Fetcher()
    result = WebSearch(fetcher).search("topic", limit=1)
    assert result["sources"][0]["text"] == "Evidence from page."
    assert len(fetcher.calls) == 2


def test_search_fallback_and_partial_failure_are_reported():
    class Fetcher:
        def fetch(self, url):
            if "duckduckgo" in url:
                raise ValueError("challenge")
            if "bing.com" in url:
                return {"content": '<rss><channel><item><link>https://example.com/a</link></item><item><link>https://example.com/b</link></item></channel></rss>'}
            if url.endswith("/b"):
                raise OSError("unavailable")
            return {"url": url, "content": "A source excerpt", "media_type": "text/plain"}
    result = WebSearch(Fetcher()).search("topic", limit=2)
    assert len(result["sources"]) == 1 and len(result["errors"]) == 2


@pytest.mark.parametrize("status,media,body", [(302, "text/html", b""), (200, "application/octet-stream", b"x"),
                                               (200, "text/html", b"x" * 1_000_001)], ids=["redirect", "binary", "oversize"])
def test_http_redirect_binary_and_oversize_fail_closed(monkeypatch, status, media, body):
    class Response:
        headers = Message()
        def getheader(self, name, default=None):
            return media if name == "Content-Type" else default
        def read(self, limit):
            return body[:limit]
    response = Response()
    response.status = status
    class Connection:
        def request(self, *args, **kwargs): pass
        def getresponse(self): return response
        def close(self): pass
    monkeypatch.setattr("core.research_web.socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))])
    monkeypatch.setattr("core.research_web._PinnedHTTPS", lambda *a: Connection())
    with pytest.raises(ValueError):
        PublicTextFetcher().fetch("https://example.test/")


@pytest.mark.parametrize("oversize", [False, True], ids=["valid-gzip", "gzip-expansion-limit"])
def test_gzip_is_decompressed_with_a_strict_output_limit(monkeypatch, oversize):
    import gzip
    body = gzip.compress(b"x" * (1_000_001 if oversize else 100))
    class Response:
        status = 200
        headers = Message()
        def getheader(self, name, default=None):
            return {"Content-Type": "text/plain", "Content-Encoding": "gzip"}.get(name, default)
        def read(self, limit):
            return body
    class Connection:
        def request(self, *args, **kwargs): pass
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr("core.research_web.socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))])
    monkeypatch.setattr("core.research_web._PinnedHTTPS", lambda *a: Connection())
    if oversize:
        with pytest.raises(ValueError):
            PublicTextFetcher().fetch("https://example.test/")
    else:
        assert PublicTextFetcher().fetch("https://example.test/")["content"] == "x" * 100

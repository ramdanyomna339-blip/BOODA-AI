"""Bounded public HTTPS retrieval and best-effort web discovery.

Connections pin a validated public DNS address. Redirects, credentials, private
addresses, nonstandard ports and non-text responses are deliberately rejected.
"""

from html.parser import HTMLParser
import http.client
import ipaddress
import re
import socket
import ssl
import zlib
from xml.etree import ElementTree
from urllib.parse import urlsplit, urlunsplit, urlencode, parse_qs


MAX_BYTES = 1_000_000


def public_url(url):
    if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 33 for c in url):
        raise ValueError("Invalid public URL.")
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.port not in {None, 443}):
        raise ValueError("Use a public HTTPS URL without credentials or custom port.")
    host = parts.hostname.encode("idna").decode("ascii")
    netloc = f"[{host}]" if ":" in host else host
    return urlunsplit(("https", netloc, parts.path or "/", parts.query, ""))


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, timeout=15, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


class PublicTextFetcher:
    def fetch(self, url):
        url = public_url(url)
        parts = urlsplit(url)
        addresses = {item[4][0] for item in socket.getaddrinfo(
            parts.hostname, 443, type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise ValueError("Only publicly routable addresses are allowed.")
        connection = _PinnedHTTPS(parts.hostname, sorted(addresses)[0])
        try:
            target = urlunsplit(("", "", parts.path, parts.query, ""))
            connection.request("GET", target, headers={
                "User-Agent": "BoodaResearch/1.0", "Accept": "text/html,text/plain",
                "Accept-Encoding": "identity",
            })
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError(f"Source returned HTTP {response.status}; redirects are not followed.")
            media = response.getheader("Content-Type", "").split(";", 1)[0].lower()
            if media not in {"text/html", "text/plain", "application/xhtml+xml",
                             "application/rss+xml", "text/xml", "application/xml", "text/vtt", "application/x-subrip"}:
                raise ValueError("Source must be HTML, plain text, or XML.")
            encoding = response.getheader("Content-Encoding", "identity").lower()
            if encoding not in {"identity", "gzip", "deflate"}:
                raise ValueError("Unsupported source compression.")
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("Source exceeds the response size limit.")
            if encoding != "identity":
                try:
                    decoder = zlib.decompressobj(31 if encoding == "gzip" else zlib.MAX_WBITS)
                    raw = decoder.decompress(raw, MAX_BYTES + 1)
                    if len(raw) > MAX_BYTES or not decoder.eof:
                        raise ValueError("Decompressed source exceeds the limit or is incomplete.")
                except zlib.error as error:
                    raise ValueError("Invalid compressed source.") from error
            charset = response.headers.get_content_charset() or "utf-8"
            try:
                content = raw.decode(charset, errors="replace")
            except LookupError:
                raise ValueError("Unsupported source encoding.") from None
            return {"url": url, "content": content, "media_type": media,
                    "updated_at": response.getheader("Last-Modified")}
        finally:
            connection.close()


class _Article(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = []
        self.title_depth = 0
        self.title = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "nav", "header", "footer", "noscript", "svg", "template"}:
            self.hidden.append(tag)
        if tag == "title":
            self.title_depth += 1

    def handle_endtag(self, tag):
        if tag in self.hidden:
            self.hidden = self.hidden[:self.hidden.index(tag)]
        if tag == "title":
            self.title_depth = max(0, self.title_depth - 1)

    def handle_data(self, data):
        if self.title_depth:
            self.title.append(data)
        elif not self.hidden:
            self.text.append(data)


def source_from_response(response):
    if response["media_type"] == "text/plain":
        text, title = response["content"], response["url"]
    else:
        parser = _Article()
        parser.feed(response["content"])
        text, title = " ".join(parser.text), " ".join(parser.title)
    text = re.sub(r"\s+", " ", text).strip()[:12000]
    if not text:
        raise ValueError("Source has no extractable text.")
    host = urlsplit(response["url"]).hostname
    return {"title": title.strip()[:300] or host, "text": text,
            "source": response["url"], "publisher": host, "kind": "web_page",
            "updated_at": response.get("updated_at")}


class _SearchLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "result__a" in attrs.get("class", "").split():
            href = attrs.get("href", "")
            if href.startswith("//"):
                href = "https:" + href
            parts = urlsplit(href)
            if parts.hostname in {"duckduckgo.com", "www.duckduckgo.com"}:
                href = parse_qs(parts.query).get("uddg", [""])[0]
            try:
                url = public_url(href)
            except ValueError:
                return
            if url not in self.links:
                self.links.append(url)


class WebSearch:
    """Public HTML discovery, which can fail when the provider blocks automation."""

    def __init__(self, fetcher=None):
        self.fetcher = fetcher or PublicTextFetcher()

    def search(self, query, *, language="ar", limit=5):
        if language not in {"ar", "en"} or type(limit) is not int or not 1 <= limit <= 5:
            raise ValueError("Invalid search language or limit.")
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise ValueError("Query must contain 1–500 characters.")
        links, discovery_errors = [], []
        try:
            response = self.fetcher.fetch("https://html.duckduckgo.com/html/?" + urlencode({"q": query}))
            parser = _SearchLinks()
            parser.feed(response["content"])
            links = parser.links
            if not links:
                raise ValueError("No usable HTML results.")
        except (OSError, ValueError, http.client.HTTPException):
            discovery_errors.append({"provider": "DuckDuckGo", "error": "Discovery unavailable; tried Bing RSS."})
            try:
                response = self.fetcher.fetch("https://www.bing.com/search?" + urlencode({"format": "rss", "q": query}))
                root = ElementTree.fromstring(response["content"])
                for item in root.findall("./channel/item/link"):
                    try:
                        link = public_url(item.text or "")
                        if link not in links:
                            links.append(link)
                    except ValueError:
                        continue
            except ElementTree.ParseError as error:
                raise ValueError("Invalid search feed.") from error
        if not links:
            raise ValueError("No usable web results; search services may be unavailable.")
        results, errors = [], []
        errors.extend(discovery_errors)
        for url in links[:limit]:
            try:
                results.append(source_from_response(self.fetcher.fetch(url)))
            except (OSError, ValueError, http.client.HTTPException):
                errors.append({"source": url, "error": "Source could not be retrieved."})
        return {"sources": results, "errors": errors}

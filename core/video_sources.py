"""Discover explicit HTML video sources; no script execution or automatic download."""
from html.parser import HTMLParser
from urllib.parse import urljoin
from core.research_web import PublicTextFetcher, public_url


class VideoLinks(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.links = base, []
        self.media_depth = 0
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"video", "audio"}:
            self.media_depth += 1
        kind = "caption" if tag == "track" and self.media_depth and attrs.get("kind", "subtitles") in {"captions", "subtitles"} else "media" if tag in {"video", "audio"} or tag == "source" and self.media_depth else None
        if not kind or not attrs.get("src") or len(self.links) >= 30:
            return
        try:
            url = public_url(urljoin(self.base, attrs["src"]))
        except ValueError:
            return
        if not any(row["url"] == url for row in self.links):
            self.links.append({"kind": kind, "url": url, "language": attrs.get("srclang", "")[:30],
                               "label": attrs.get("label", "")[:150]})
    def handle_endtag(self, tag):
        if tag in {"video", "audio"}:
            self.media_depth = max(0, self.media_depth - 1)


def discover_video_sources(url, *, fetcher=None):
    response = (fetcher or PublicTextFetcher()).fetch(public_url(url))
    if response["media_type"] not in {"text/html", "application/xhtml+xml"}:
        raise ValueError("هذا الاختيار يحتاج رابط صفحة HTML.")
    parser = VideoLinks(response["url"])
    parser.feed(response["content"])
    return {"page": response["url"], "sources": parser.links, "untrusted": True,
            "downloaded": False, "requires_review": True,
            "note": "راجع الرابط قبل قراءته أو تنزيله بموافقة جديدة؛ الصفحات المعتمدة على JavaScript قد لا تعرض مصادر."}

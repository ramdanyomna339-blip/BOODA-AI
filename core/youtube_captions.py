"""Public YouTube captions, fixed hosts and bounded pinned HTTPS transport."""
import ipaddress
import math
import re
import socket
import time
from urllib.parse import parse_qs, urlsplit, urlunsplit
from core.research_web import _PinnedHTTPS, public_url


def youtube_video_id(url):
    parts = urlsplit(public_url(url))
    if parts.hostname == "youtu.be":
        value = parts.path.removeprefix("/")
    elif parts.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parts.path == "/watch":
            values = parse_qs(parts.query).get("v", [])
            value = values[0] if len(values) == 1 else ""
        elif parts.path.startswith(("/shorts/", "/embed/", "/live/")):
            value = parts.path.split("/")[-1]
        else:
            value = ""
    else:
        value = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        raise ValueError("استخدم رابط فيديو YouTube واحدًا صحيحًا.")
    return value


def pinned_youtube_session():
    import requests
    from requests.adapters import BaseAdapter
    class Adapter(BaseAdapter):
        def __init__(self):
            self.count, self.started = 0, time.monotonic()
        def send(self, request, **kwargs):
            self.count += 1
            if self.count > 8 or time.monotonic() - self.started > 60:
                raise ValueError("انتهت حدود قراءة ترجمة الفيديو.")
            parts = urlsplit(public_url(request.url))
            if parts.hostname not in {"www.youtube.com", "youtube.com", "www.youtube-nocookie.com", "youtubei.googleapis.com"}:
                raise ValueError("أوقفت قراءة رابط خارج مصادر YouTube المسموح بها.")
            if request.method not in {"GET", "POST"}:
                raise ValueError("طلب غير مدعوم.")
            if request.headers.get("Cookie") or request.headers.get("Authorization"):
                raise ValueError("قراءة الترجمة لا تستخدم حسابًا أو توافق تلقائيًا على طلب ملفات دخول/موافقة من الموقع.")
            body = request.body or b""
            if not isinstance(body, (bytes, str)) or len(body) > 100000:
                raise ValueError("طلب الفيديو أكبر من الحد المسموح.")
            addresses = {row[4][0] for row in socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)}
            if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
                raise ValueError("عنوان شبكة غير عام.")
            connection = _PinnedHTTPS(parts.hostname, sorted(addresses)[0])
            try:
                headers = dict(request.headers)
                headers["Accept-Encoding"] = "identity"
                headers.pop("Authorization", None)
                connection.request(request.method, urlunsplit(("", "", parts.path, parts.query, "")), body=body, headers=headers)
                source = connection.getresponse()
                if 300 <= source.status < 400 or source.getheader("Content-Encoding", "identity").lower() != "identity":
                    raise ValueError("تحويل الرابط أو ضغط الاستجابة غير مدعوم.")
                content = source.read(3_000_001)
                if len(content) > 3_000_000:
                    raise ValueError("استجابة الفيديو أكبر من الحد المسموح.")
                response = requests.Response()
                response.status_code, response._content = source.status, content
                response.headers.update(dict(source.getheaders()))
                response.url, response.request = request.url, request
                response.encoding = "utf-8"
                return response
            finally:
                connection.close()
        def close(self): pass
    session = requests.Session()
    session.trust_env = False
    session.mount("https://", Adapter())
    return session


def read_youtube_captions(url, *, language="ar", api=None):
    video_id = youtube_video_id(url)
    if language not in {"ar", "en"}:
        raise ValueError("اختر ar أو en للغة الترجمة.")
    session = None
    try:
        if api is None:
            from youtube_transcript_api import YouTubeTranscriptApi
            session = pinned_youtube_session()
            api = YouTubeTranscriptApi(http_client=session)
        transcript = api.fetch(video_id, languages=[language])
        rows = transcript.to_raw_data()
        if len(rows) > 3000:
            raise ValueError("الترجمة طويلة؛ استخدم فيديو أقصر.")
        segments = []
        for row in rows:
            start, duration = float(row["start"]), float(row["duration"])
            if not math.isfinite(start) or not math.isfinite(duration) or start < 0 or duration < 0:
                raise ValueError("توقيت الترجمة غير صالح.")
            segments.append({"start": start, "end": start + duration, "text": str(row["text"])[:2000]})
        text = "\n".join(row["text"] for row in segments)
        return {"source": "https://www.youtube.com/watch?v=" + video_id,
                "method": "youtube_public_captions", "language": transcript.language_code,
                "is_generated": transcript.is_generated, "segments": segments, "text": text[:30000],
                "truncated": len(text) > 30000, "requires_review": True, "untrusted": True,
                "audio_transcribed": False, "account_used": False}
    except (ValueError, ImportError):
        raise
    except Exception as error:
        raise RuntimeError("تعذر الحصول على ترجمة بهذه اللغة؛ قد تكون غير متاحة أو يطلب YouTube تسجيل الدخول. استخدم ملف ترجمة أو ملف فيديو محلي بإذنك.") from error
    finally:
        if session is not None:
            session.close()

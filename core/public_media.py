"""Download one explicit direct public media URL, pinned DNS, no redirects/cookies."""
import hashlib
import ipaddress
from pathlib import Path
import socket
import time
from urllib.parse import urlsplit, urlunsplit
import uuid

from core.research_web import _PinnedHTTPS, public_url

MEDIA_TYPES = {"video/mp4": ".mp4", "video/webm": ".webm", "audio/mpeg": ".mp3",
               "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/ogg": ".ogg",
               "audio/flac": ".flac", "audio/mp4": ".m4a"}


def download_public_media(url, output_root, *, connection_factory=_PinnedHTTPS,
                          resolver=socket.getaddrinfo, clock=time.monotonic, max_bytes=100_000_000):
    url = public_url(url)
    parts = urlsplit(url)
    addresses = {row[4][0] for row in resolver(parts.hostname, 443, type=socket.SOCK_STREAM)}
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("الرابط يجب أن يشير لعنوان إنترنت عام.")
    connection = connection_factory(parts.hostname, sorted(addresses)[0])
    destination = None
    created = False
    started = clock()
    try:
        connection.request("GET", urlunsplit(("", "", parts.path, parts.query, "")), headers={
            "User-Agent": "BoodaMedia/1.0", "Accept-Encoding": "identity"})
        response = connection.getresponse()
        media = response.getheader("Content-Type", "").split(";", 1)[0].lower()
        if response.status != 200 or media not in MEDIA_TYPES:
            raise ValueError("نحتاج رابط ملف صوت/فيديو مباشر؛ صفحة يوتيوب أو تحويل الرابط لا تكفي.")
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            raise ValueError("الوسائط المضغوطة عبر HTTP غير مدعومة.")
        length = response.getheader("Content-Length")
        if length is not None and (not length.isdecimal() or int(length) > max_bytes):
            raise ValueError("حجم الوسائط أكبر من 100 ميجابايت أو غير صالح.")
        output = Path(output_root).resolve()
        output.mkdir(parents=True, exist_ok=True)
        destination = output / ("download-" + uuid.uuid4().hex + MEDIA_TYPES[media])
        digest, total = hashlib.sha256(), 0
        with destination.open("xb") as stream:
            created = True
            while True:
                if clock() - started > 60:
                    raise ValueError("انتهت مهلة التنزيل؛ استخدم ملفًا أصغر.")
                chunk = response.read(min(65536, max_bytes - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("تجاوز التنزيل الحجم المسموح.")
                stream.write(chunk)
                digest.update(chunk)
        if not total or (length is not None and total != int(length)):
            raise ValueError("الملف فارغ أو غير مكتمل.")
        return {"path": str(destination), "bytes": total, "sha256": digest.hexdigest(),
                "source": url, "transcribed": False, "requires_review": True,
                "note": "التنزيل لا يشغّل الملف؛ التفريغ أو التشغيل يحتاج موافقة جديدة."}
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise
    finally:
        connection.close()

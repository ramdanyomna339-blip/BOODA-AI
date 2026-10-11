"""Read explicitly supplied public VTT/SRT captions, without downloading video."""
import html
import re
from core.research_web import PublicTextFetcher, public_url


def read_public_captions(url, *, fetcher=None):
    response = (fetcher or PublicTextFetcher()).fetch(public_url(url))
    content = response["content"].lstrip("\ufeff").replace("\r\n", "\n")
    if len(content) > 1_000_000:
        raise ValueError("ملف الترجمة أكبر من الحد المسموح.")
    timing = re.compile(r"(?m)^((?:\d{2}:)?\d{2}:\d{2}[.,]\d{3})\s+-->\s+((?:\d{2}:)?\d{2}:\d{2}[.,]\d{3})[^\n]*\n([^\n]*(?:\n(?!\n)[^\n]*)*)")
    segments = []
    for match in timing.finditer(content):
        if len(segments) >= 2000:
            raise ValueError("قسّم الترجمة إلى ملف أصغر قبل القراءة.")
        text = html.unescape(re.sub(r"<[^>]*>", "", match[3])).strip()[:2000]
        if text:
            segments.append({"start": match[1], "end": match[2], "text": text})
    if not segments:
        raise ValueError("الرابط ليس ملف ترجمة VTT/SRT مقروءًا؛ رابط صفحة الفيديو وحده لا يكفي.")
    return {"source": url, "method": "public_caption_file", "segments": segments,
            "text": "\n".join(row["text"] for row in segments)[:20000],
            "requires_review": True, "audio_transcribed": False, "executed": False}

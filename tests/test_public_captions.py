from types import SimpleNamespace
import pytest
from core.public_captions import read_public_captions


def fetcher(content):
    return SimpleNamespace(fetch=lambda url: {"content": content, "url": url, "media_type": "text/vtt"})


@pytest.mark.parametrize("content", ["WEBVTT\n\n00:00.000 --> 00:02.000\n<b>نص عربي</b>\n\n",
    "1\n00:00:00,000 --> 00:00:02,000\nنص عربي\n\n"])
def test_public_caption_text_preserves_arabic_without_claiming_transcription(content):
    result = read_public_captions("https://example.com/captions.vtt", fetcher=fetcher(content))
    assert result["text"] == "نص عربي"
    assert result["requires_review"] is True
    assert result["audio_transcribed"] is False


def test_video_html_is_not_a_caption_file():
    with pytest.raises(ValueError):
        read_public_captions("https://example.com/video", fetcher=fetcher("<html>Watch video</html>"))


def test_caption_url_cannot_contain_credentials():
    with pytest.raises(ValueError):
        read_public_captions("https://user:password@example.com/captions", fetcher=fetcher(""))

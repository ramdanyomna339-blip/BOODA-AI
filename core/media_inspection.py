"""Inspect local media without playback, microphone access or network access."""


def inspect_media(path):
    import av
    with av.open(str(path), options={"protocol_whitelist": "file",
                                    "format_whitelist": "mov,matroska,webm,mp3,wav,ogg,flac,aac"}) as media:
        return {"duration_seconds": media.duration / av.time_base if media.duration is not None else None,
                "streams": [{"type": stream.type, "codec": stream.codec_context.name,
                             "width": getattr(stream.codec_context, "width", None),
                             "height": getattr(stream.codec_context, "height", None),
                             "sample_rate": getattr(stream.codec_context, "sample_rate", None)}
                            for stream in list(media.streams)[:20]],
                "source": str(path), "played": False, "transcribed": False}

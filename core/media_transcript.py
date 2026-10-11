"""Offline speech-to-text; requires a user-selected local Whisper model."""
import json
import uuid
from pathlib import Path


def transcribe_local(path, *, model_path, output_root):
    if model_path is None or not Path(model_path).is_dir():
        raise ValueError("Select an existing local faster-whisper model directory first; no automatic model downloads.")
    from faster_whisper import WhisperModel
    import av
    import numpy as np
    chunks, samples = [], 0
    with av.open(str(path), options={"protocol_whitelist": "file",
                                    "format_whitelist": "mov,matroska,webm,mp3,wav,ogg,flac,aac"}) as media:
        if media.duration is not None and media.duration / av.time_base > 1800:
            raise ValueError("Split media longer than 30 minutes before transcription.")
        if not media.streams.audio:
            raise ValueError("This media file has no audio track.")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        def collect(frames):
            nonlocal samples
            for frame in frames:
                chunk = frame.to_ndarray().flatten()
                samples += chunk.size
                if samples > 1800 * 16000:
                    raise ValueError("Audio exceeds the 30-minute session limit.")
                chunks.append(chunk)
        for frame in media.decode(audio=0):
            collect(resampler.resample(frame))
        collect(resampler.resample(None))
    if not chunks:
        raise ValueError("No decodable audio found.")
    audio = np.concatenate(chunks).astype(np.float32) / 32768.0
    model = WhisperModel(str(model_path), device="cpu", compute_type="int8", local_files_only=True)
    segments, info = model.transcribe(audio, beam_size=3, vad_filter=True)
    rows = []
    for segment in segments:
        if segment.end > 1800 or len(rows) >= 2000:
            raise ValueError("Transcription is limited to 30 minutes per request; split longer media first.")
        rows.append({"start": segment.start, "end": segment.end, "text": segment.text.strip()})
    result = {"language": info.language, "language_probability": info.language_probability,
              "segments": rows, "text": "\n".join(row["text"] for row in rows),
              "source": str(path), "method": "local_whisper", "requires_review": True}
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    stem = "transcript-" + uuid.uuid4().hex
    (output / (stem + ".json")).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    text_path = output / (stem + ".txt")
    text_path.write_text(result["text"], encoding="utf-8")
    return {**result, "transcript_path": str(text_path.resolve())}

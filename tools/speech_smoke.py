"""End-to-end public sample audio in a generated video, with no microphone access."""
import json
import sys
import urllib.request
from pathlib import Path
from fractions import Fraction


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / ".desktop-deps"))
    import av
    from PIL import Image
    from core.media_transcript import transcribe_local
    output = root / "outputs" / "desktop_checks"
    output.mkdir(parents=True, exist_ok=True)
    audio = output / "public-sample.wav"
    if not audio.exists():
        with urllib.request.urlopen("https://raw.githubusercontent.com/ggml-org/whisper.cpp/master/samples/jfk.wav", timeout=30) as response:
            audio.write_bytes(response.read(2_000_000))
    video = output / "speech-video.mkv"
    with av.open(str(audio)) as source, av.open(str(video), "w") as target:
        sound = target.add_stream("pcm_s16le", rate=16000)
        sound.layout = "mono"
        visual = target.add_stream("ffv1", rate=1)
        visual.width, visual.height, visual.pix_fmt = 320, 180, "yuv420p"
        packets = []
        for frame in source.decode(audio=0):
            packets.extend(sound.encode(frame))
        packets.extend(sound.encode(None))
        for second in range(12):
            frame = av.VideoFrame.from_image(Image.new("RGB", (320, 180), "navy"))
            frame.pts, frame.time_base = second, Fraction(1, 1)
            packets.extend(visual.encode(frame))
        packets.extend(visual.encode(None))
        for packet in sorted(packets, key=lambda item: (item.dts or 0) * item.time_base):
            target.mux(packet)
    result = transcribe_local(video, model_path=root / ".local-ai-runtime/models/speech-tiny", output_root=output)
    normalized = result["text"].lower()
    result["known_sample_recognized"] = "country" in normalized and "ask" in normalized
    (output / "speech.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"recognized": result["known_sample_recognized"], "language": result["language"], "segments": len(result["segments"]), "report": str(output / "speech.json")}))
    if not result["known_sample_recognized"]:
        raise RuntimeError("Known audio sample recognition failed; inspect speech.json")


if __name__ == "__main__":
    main()

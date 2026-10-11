"""One public network attempt; no browser launch or account. Only report status."""
import json
import argparse
from pathlib import Path
import time
from core.youtube_captions import read_youtube_captions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=["ar", "en"], default="en")
    language = parser.parse_args().language
    start = time.monotonic()
    report = {"source": "https://www.youtube.com/watch?v=iG9CE55wbtY", "language": language,
              "account_used": False, "audio_downloaded": False}
    try:
        result = read_youtube_captions(report["source"], language=language)
        report.update(status="completed", segments=len(result["segments"]),
                      characters=len(result["text"]), is_generated=result["is_generated"])
    except Exception as error:
        report.update(status="unavailable", reason=str(error), error_type=type(error).__name__)
    report["seconds"] = round(time.monotonic() - start, 2)
    output = Path("outputs/desktop_checks/youtube")
    output.mkdir(parents=True, exist_ok=True)
    (output / ("report-" + language + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    if report["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

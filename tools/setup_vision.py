"""Download only public model data to the existing local runtime."""
from pathlib import Path
import urllib.request


def main():
    root = Path(__file__).resolve().parents[1] / ".local-ai-runtime" / "models" / "screen-vision"
    root.mkdir(parents=True, exist_ok=True)
    names = ["SmolVLM-500M-Instruct-Q8_0.gguf", "mmproj-SmolVLM-500M-Instruct-Q8_0.gguf"]
    for name in names:
        target = root / name
        if target.exists():
            print("Already present:", name, flush=True)
            continue
        url = "https://huggingface.co/ggml-org/SmolVLM-500M-Instruct-GGUF/resolve/main/" + name
        temporary = target.with_suffix(".download")
        print("Downloading:", name, flush=True)
        with urllib.request.urlopen(url, timeout=90) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        with temporary.open("rb") as header:
            magic = header.read(4)
        if temporary.stat().st_size < 1_000_000 or magic != b"GGUF":
            raise ValueError("Download was not a valid GGUF model.")
        temporary.replace(target)
        print("Ready:", target.name, target.stat().st_size, flush=True)


if __name__ == "__main__":
    main()

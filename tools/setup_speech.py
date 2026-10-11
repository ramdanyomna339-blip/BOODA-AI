"""Install multilingual tiny speech model data inside the project only."""
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / ".desktop-deps"))
    from huggingface_hub import snapshot_download
    destination = root / ".local-ai-runtime" / "models" / "speech-tiny"
    snapshot_download("Systran/faster-whisper-tiny", local_dir=str(destination),
        cache_dir=str(root / ".local-ai-runtime" / "download-cache"),
        allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.txt", "preprocessor_config.json"],
        max_workers=2, token=False)
    print(destination)


if __name__ == "__main__":
    main()

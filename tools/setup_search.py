"""Explicit installation of the multilingual search model; never called by search."""
from pathlib import Path


def main():
    from huggingface_hub import snapshot_download
    root = Path(__file__).resolve().parents[1]
    destination = root / ".local-ai-runtime/models/search-multilingual"
    snapshot_download(
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        local_dir=str(destination), token=False, max_workers=2,
        allow_patterns=["*.json", "*.txt", "*.safetensors", "1_Pooling/*", "README.md"],
    )
    print(destination)


if __name__ == "__main__":
    main()

"""Optional offline embeddings. Never download a model while answering a query."""
import os
import math
from pathlib import Path
from functools import lru_cache
from collections import OrderedDict
from threading import RLock


class LocalSemanticSearch:
    def __init__(self, model_path):
        path = Path(model_path).resolve()
        if not path.is_dir():
            raise ValueError("Semantic model must be a local directory.")
        from sentence_transformers import SentenceTransformer
        import torch
        # Small CPU batches otherwise spend most of their time scheduling threads.
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        self.model = SentenceTransformer(str(path), local_files_only=True,
                                         trust_remote_code=False, device="cpu",
                                         model_kwargs={"use_safetensors": True})
        self.cache = OrderedDict()
        self.lock = RLock()

    def vectors(self, texts):
        missing = list(dict.fromkeys(text for text in texts if text not in self.cache))
        width = max(16, min(96, self.model.max_seq_length - 2))
        windows, spans = [], []
        for text in missing:
            tokens = self.model.tokenizer.encode(text, add_special_tokens=False, verbose=False)
            parts = [self.model.tokenizer.decode(tokens[start:start + width])
                     for start in range(0, len(tokens), width)] or [""]
            spans.append((len(windows), len(windows) + len(parts)))
            windows.extend(parts)
        if windows:
            encoded = self.model.encode(windows, normalize_embeddings=True, batch_size=16, show_progress_bar=False)
            for text, (start, end) in zip(missing, spans):
                vector = encoded[start:end].mean(axis=0).tolist()
                length = math.sqrt(sum(value * value for value in vector)) or 1
                self.cache[text] = [value / length for value in vector]
        result = [self.cache[text] for text in texts]
        for text in texts:
            self.cache.move_to_end(text)
        while len(self.cache) > 2048:
            self.cache.popitem(last=False)
        return result

    def scores(self, query, texts):
        with self.lock:
            vectors = self.vectors([query, *texts])
            return [sum(a * b for a, b in zip(vectors[0], vector)) for vector in vectors[1:]]


@lru_cache(maxsize=1)
def configured_search():
    default = Path(__file__).resolve().parents[1] / ".local-ai-runtime/models/search-multilingual"
    path = os.environ.get("BOODA_EMBEDDING_MODEL") or (str(default) if default.is_dir() else None)
    if not path:
        return None
    try:
        return LocalSemanticSearch(path)
    except (ImportError, OSError, ValueError, RuntimeError):
        return None

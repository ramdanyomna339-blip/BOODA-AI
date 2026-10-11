"""Persistent CPU worker for Booda's optional local voice clone."""

from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import sys
import traceback
import types


def main():
    try:
        import torch
        torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))

        from huggingface_hub import hf_hub_download

        import numpy as np
        import soundfile as sf

        def local_model_cache(url, cache_dir=None):
            if not url.startswith("hf://"):
                raise ValueError("Unexpected SILMA resource URL.")
            parts = url[5:].split("/")
            repo_id, filename = "/".join(parts[:-1]), parts[-1]
            if filename == "model.pt":
                model_path = Path(os.environ["BOODA_SILMA_MODEL_PATH"])
                if model_path.is_file():
                    return str(model_path)
            if filename == "vocab.txt":
                vocab_path = Path(os.environ["BOODA_SILMA_VOCAB_PATH"])
                if vocab_path.is_file():
                    return str(vocab_path)
            return hf_hub_download(repo_id=repo_id, filename=filename, cache_dir=cache_dir, local_files_only=True)

        cache_module = types.ModuleType("cached_path")
        cache_module.cached_path = local_model_cache
        sys.modules["cached_path"] = cache_module
        for package_name in ("nemo_text_processing", "nemo_text_processing.text_normalization"):
            package = types.ModuleType(package_name)
            package.__path__ = []
            sys.modules[package_name] = package
        normalizer_module = types.ModuleType(
            "nemo_text_processing.text_normalization.normalize"
        )
        normalizer_module.Normalizer = None
        sys.modules[normalizer_module.__name__] = normalizer_module
        tashkeel_module = types.ModuleType("catt_tashkeel")
        tashkeel_module.CATTEncoderOnly = None
        sys.modules[tashkeel_module.__name__] = tashkeel_module

        import silma_tts.api as silma_api
        import silma_tts.infer.utils_infer as silma_infer

        def load_reference_audio(path):
            waveform, sample_rate = sf.read(path, dtype="float32", always_2d=True)
            return torch.from_numpy(np.ascontiguousarray(waveform.T)), sample_rate

        silma_infer.torchaudio.load = load_reference_audio

        with redirect_stdout(sys.stderr):
            engine = silma_api.SilmaTTS(
                enable_normalizer=False,
                force_tashkeel=False,
                hf_cache_dir=os.environ["BOODA_SILMA_CACHE_PATH"],
            )
        print(json.dumps({"ready": True}), flush=True)
    except Exception as error:
        print(json.dumps({"ready": False, "error": str(error)}), flush=True)
        traceback.print_exc(file=sys.stderr)
        return 1

    for line in sys.stdin:
        try:
            request = json.loads(line)
            output_path = Path(request["output_path"])
            with redirect_stdout(sys.stderr):
                engine.infer(
                    ref_file=request["reference_path"],
                    ref_text="أهلًا يا بوده، أنا بتكلم بالمصري بطريقتي العادية. النهارده الجو هادي.",
                    gen_text=request["text"],
                    file_wave=str(output_path),
                    show_info=lambda *args, **kwargs: print(*args, file=sys.stderr, **kwargs),
                    seed=None,
                    speed=1,
                    force_tashkeel=False,
                    normalize_numbers=False,
                )
            print(json.dumps({"ok": True, "output_path": str(output_path)}), flush=True)
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            print(json.dumps({"ok": False, "error": str(error)}), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

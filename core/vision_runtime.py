"""A separate local vision server; preserves an already-running service."""
from contextlib import contextmanager
from pathlib import Path
import subprocess
import time
import urllib.request


@contextmanager
def ensure_screen_vision(root=None):
    root = Path(root or Path(__file__).resolve().parents[1])
    endpoint = "http://127.0.0.1:8081/v1"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def ready():
        try:
            with opener.open(endpoint + "/models", timeout=2) as response:
                import json
                return any(item.get("id") == "screen-vision" for item in json.load(response).get("data", []))
        except (OSError, ValueError):
            return False
    if ready():
        yield endpoint
        return
    runtime = root / ".local-ai-runtime"
    model_dir = runtime / "models" / "screen-vision"
    model = model_dir / "SmolVLM-500M-Instruct-Q8_0.gguf"
    projector = model_dir / "mmproj-SmolVLM-500M-Instruct-Q8_0.gguf"
    binary = runtime / "bin" / "llama-server.exe"
    if not all(path.is_file() for path in (binary, model, projector)):
        raise RuntimeError("Vision runtime missing; run python -m tools.setup_vision first.")
    log_path = runtime / "screen-vision.log"
    with log_path.open("a", encoding="utf-8") as log:
        process = subprocess.Popen([str(binary), "-m", str(model), "--mmproj", str(projector),
            "--host", "127.0.0.1", "--port", "8081", "--alias", "screen-vision", "-c", "4096", "-ngl", "0", "--no-mmproj-offload"],
            cwd=root, stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 120
            while not ready():
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError(f"Vision server did not become ready; inspect {log_path}")
                time.sleep(0.5)
            yield endpoint
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

"""Manage Booda's loopback-only llama.cpp server and local smoke test."""

import os
import json
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


BASE_URL = "http://127.0.0.1:8080/v1"
MODEL_NAME = "qwen3-local"
HEALTH_URL = "http://127.0.0.1:8080/health"
DEFAULT_MODEL_RELATIVE_PATH = (
    Path(".local-ai-runtime")
    / "models"
    / "Qwen3-4B-Q2_K.gguf"
)
_SERVER_LIFECYCLE_LOCK = Lock()


def _is_healthy():
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(HEALTH_URL, timeout=1) as response:
            return response.status == 200
    except (URLError, TimeoutError, OSError):
        return False


def check_local_model_readiness():
    """Return the local API URL or report that its health endpoint is unavailable."""
    if not _is_healthy():
        raise RuntimeError(
            f"Local model server is not ready at {HEALTH_URL}."
        )
    return BASE_URL


def _check_running_model(expected_path):
    """Health alone cannot establish which model an existing server loaded."""
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open("http://127.0.0.1:8080/props", timeout=3) as response:
            properties = json.load(response)
        actual = properties.get("model_path")
        if not isinstance(actual, str) or Path(actual).resolve() != expected_path.resolve():
            raise ValueError("different or unknown model")
    except (URLError, TimeoutError, OSError, ValueError, TypeError, AttributeError) as error:
        raise RuntimeError(
            "A local server is already running, but its model does not match the selected file "
            "or cannot be verified. It was not stopped or silently reused. "
            f"Requested model: {expected_path}"
        ) from error


def _server_log_tail(log_path):
    try:
        return log_path.read_text(encoding="utf-8", errors="replace")[-3000:]
    except OSError:
        return ""


def resolve_local_model_path(root=None, model_path=None):
    project_root = (
        Path(root).resolve()
        if root
        else Path(__file__).resolve().parent.parent
    )
    configured_path = (
        model_path
        if model_path is not None
        else os.getenv("BOODA_LOCAL_MODEL_PATH")
    )
    if configured_path:
        candidate = Path(configured_path).expanduser()
        if not candidate.is_absolute():
            candidate = project_root / candidate
    else:
        candidate = project_root / DEFAULT_MODEL_RELATIVE_PATH
    return project_root, candidate.resolve()


def _missing_model_message(model_path, models_dir):
    available = sorted(path.name for path in models_dir.glob("*.gguf"))
    choices = ", ".join(available) if available else "(none)"
    return (
        f"Configured local model does not exist: {model_path}. "
        f"GGUF models present in {models_dir}: {choices}. "
        "Set BOODA_LOCAL_MODEL_PATH to an existing model; no model was selected automatically."
    )


class _LocalModelServer:
    def __init__(self, root, startup_timeout, model_path=None):
        self.project_root, self.model_path = resolve_local_model_path(
            root, model_path
        )
        self.startup_timeout = startup_timeout
        self.process = None
        self.log_path = self.project_root / ".local-ai-runtime" / "server.log"

    def start(self):
        runtime_dir = self.project_root / ".local-ai-runtime"
        binary = runtime_dir / "bin" / "llama-server.exe"
        models_dir = runtime_dir / "models"
        if not self.model_path.is_file():
            raise RuntimeError(
                _missing_model_message(self.model_path, models_dir)
            )
        if _is_healthy():
            _check_running_model(self.model_path)
            return check_local_model_readiness()
        if not binary.is_file():
            raise RuntimeError(f"Local llama.cpp server is missing: {binary}")

        thread_count = max(1, min(4, (os.cpu_count() or 2) // 2))
        command = [
            str(binary),
            "--host", "127.0.0.1",
            "--port", "8080",
            "--model", str(self.model_path),
            "--alias", MODEL_NAME,
            "--ctx-size", "4096",
            "--threads", str(thread_count),
            "--threads-batch", str(thread_count),
            "--batch-size", "128",
            "--ubatch-size", "64",
            "--parallel", "1",
            "--no-repack",
            "--jinja",
            "--reasoning", "off",
        ]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            with self.log_path.open("ab") as log_file:
                self.process = subprocess.Popen(
                    command,
                    cwd=runtime_dir,
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    creationflags=flags,
                )
        except OSError as error:
            raise RuntimeError(
                f"Could not start the local model server at {binary}: {error}"
            ) from error

        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if _is_healthy():
                return check_local_model_readiness()
            return_code = self.process.poll()
            if return_code is not None:
                details = _server_log_tail(self.log_path)
                raise RuntimeError(
                    "Local model server exited during startup "
                    f"(code {return_code}). Check the model and available memory. "
                    f"{details}"
                )
            time.sleep(0.5)
        details = _server_log_tail(self.log_path)
        raise RuntimeError(
            "Timed out waiting for the local model server on 127.0.0.1:8080. "
            f"Check {self.log_path}. {details}"
        )

    def stop(self):
        process = self.process
        self.process = None
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        except OSError as error:
            raise RuntimeError(
                f"Could not stop the local model server (pid {process.pid}): {error}"
            ) from error


@contextmanager
def ensure_local_model_server(root=None, *, startup_timeout=180, model_path=None):
    """Yield the local API URL and stop only the server this context starts."""
    with _SERVER_LIFECYCLE_LOCK:
        server = _LocalModelServer(root, startup_timeout, model_path)
        try:
            yield server.start()
        finally:
            server.stop()


def run_local_model_smoke_test():
    """Plan a general Arabic marketing goal and display local model output."""
    from core.console import configure_utf8_console
    from core.permission_manager import BoodaPermissionManager
    from core.planning import BoodaGoal
    from core.tool_registry import BoodaToolRegistry
    from core.llm_planner import OpenAICompatiblePlanner

    configure_utf8_console()
    with ensure_local_model_server() as base_url:
        capability_permissions = {"create_plan_artifact": ("save_file",)}
        planner = OpenAICompatiblePlanner(
            base_url=base_url,
            model=MODEL_NAME,
            api_key=None,
            timeout=180,
            max_plan_steps=7,
            min_plan_steps=3,
            local_planning=True,
            capability_permissions=capability_permissions,
        )
        registry = BoodaToolRegistry()
        registry.register("create_plan_artifact", lambda task: task.description)
        permissions = BoodaPermissionManager()
        permissions.add_permission("save_file", allowed=False)
        planner.configure_agent(registry=registry, permission_manager=permissions)
        goal = BoodaGoal(
            "local-study-smoke-test",
            "اكتبي خطة عربية لتحسين إعلان محلي وقياس نتائجه",
        )
        plan = planner.create_plan(goal, memory=None)
        print("خطة النموذج المحلي:")
        for step in plan.steps:
            print(f"- {step.title}: {step.description}")
            print(f"  الأداة: {step.capability}; الصلاحية المطلوبة: {step.permission_name}")
        return plan


if __name__ == "__main__":
    run_local_model_smoke_test()

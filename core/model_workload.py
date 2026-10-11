"""One local model request at a time across Booda processes, with bounded waiting."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

DEFAULT_DATABASE = Path(__file__).resolve().parents[1] / ".local-ai-runtime/model-workload.sqlite3"


class ModelBusyError(RuntimeError):
    pass


@contextmanager
def model_slot(endpoint, *, database=None, wait_seconds=10):
    if urlsplit(endpoint).hostname not in {"localhost", "127.0.0.1", "::1"}:
        yield
        return
    path = Path(database) if database else DEFAULT_DATABASE
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=wait_seconds, isolation_level=None)
    try:
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as error:
            if "locked" in str(error).lower() or "busy" in str(error).lower():
                raise ModelBusyError("النموذج المحلي مشغول بطلب آخر؛ انتظر قليلًا ثم أعد الطلب بنفسك.") from None
            raise
        yield
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()

from pathlib import Path

import pytest

from core.persistence import JsonObjectStore


def test_transient_windows_file_lock_retries_atomically(tmp_path, monkeypatch):
    store = JsonObjectStore(tmp_path / "state.json")
    store.save({"old": True})
    real = Path.replace
    attempts = []
    def replace(path, target):
        attempts.append(str(path))
        if len(attempts) < 3:
            error = PermissionError("Temporary sharing violation")
            error.winerror = 32
            raise error
        return real(path, target)
    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr("core.persistence.time.sleep", lambda delay: None)
    store.save({"new": True})
    assert store.load() == {"new": True} and len(attempts) == 3
    assert not list(tmp_path.glob("*.tmp"))


def test_persistent_failure_preserves_original_and_cleans_temporary_file(tmp_path, monkeypatch):
    store = JsonObjectStore(tmp_path / "state.json")
    store.save({"old": True})
    def replace(path, target):
        error = PermissionError("Persistent deny")
        error.winerror = 5
        raise error
    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr("core.persistence.time.sleep", lambda delay: None)
    with pytest.raises(PermissionError):
        store.save({"new": True})
    assert store.load() == {"old": True}
    assert not list(tmp_path.glob("*.tmp"))

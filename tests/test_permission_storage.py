from core.permission_manager import BoodaPermissionManager
from pathlib import Path
import json
import pytest


def test_interrupted_permission_save_preserves_previous_readable_state(tmp_path, monkeypatch):
    path = tmp_path / "permissions.json"
    manager = BoodaPermissionManager(file_path=path)
    manager.add_permission("save_file", allowed=False)
    def fail_replace(self, target):
        raise PermissionError("simulated interrupted replacement")
    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(PermissionError):
        manager.grant_permission("save_file")
    assert json.loads(path.read_text(encoding="utf-8")) == {"save_file": False}
    assert manager.is_allowed("save_file") is False
    assert not list(tmp_path.glob("*.tmp"))


def test_permission_state_survives_reopening(tmp_path):
    file_path = tmp_path / "security" / "permissions.json"

    first_manager = BoodaPermissionManager(file_path=file_path)
    first_manager.add_permission(
        name="send_message",
        allowed=False,
    )

    assert first_manager.grant_permission(
        "send_message",
        changed_by="Yomna",
    )

    second_manager = BoodaPermissionManager(file_path=file_path)
    restored_permission = second_manager.add_permission(
        name="send_message",
        allowed=False,
    )

    assert restored_permission.allowed is True

    assert second_manager.revoke_permission(
        "send_message",
        changed_by="Yomna",
    )

    third_manager = BoodaPermissionManager(file_path=file_path)
    restored_permission = third_manager.add_permission(
        name="send_message",
        allowed=True,
    )

    assert restored_permission.allowed is False

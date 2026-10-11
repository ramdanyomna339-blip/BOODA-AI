import pytest

from core.approval_manager import BoodaApprovalManager
from core.laptop import BoodaLaptopConnection, LAPTOP_READ, LAPTOP_WRITE
from core.permission_manager import BoodaPermissionManager


def permissions(read=True, write=True):
    manager = BoodaPermissionManager()
    manager.add_permission(LAPTOP_READ, allowed=read)
    manager.add_permission(LAPTOP_WRITE, allowed=write, risk_level="high")
    return manager


def approve(task):
    manager = BoodaApprovalManager()
    key, approval = manager.create_approval(LAPTOP_WRITE, "test", task_id=task.task_id)
    manager.approve_approval(key)
    return approval


def test_real_local_file_read_write_and_inventory(tmp_path):
    connection = BoodaLaptopConnection(tmp_path)
    write = connection.task_for("write_file", {"path": "note.txt", "content": "مرحبا بودا"})
    connection.execute(write, permission_manager=permissions(), approval=approve(write))
    assert write.status == "completed"
    read = connection.task_for("read_file", {"path": "note.txt"})
    result = connection.execute(read, permission_manager=permissions())
    assert result["text"] == "مرحبا بودا"
    listing = connection.execute(connection.task_for("list_files"), permission_manager=permissions())
    assert listing["entries"][0]["path"] == "note.txt"
    info = connection.execute(connection.task_for("system_info"), permission_manager=permissions())
    assert info["os"] and info["ui_control"] is False


@pytest.mark.parametrize("path", ["../outside.txt", "C:/outside.txt", "/outside.txt", "folder\\note.txt",
                                   ".env", "security/permissions.json", "secret.json", "note.txt:stream",
                                   "NUL.txt", "COM1.txt", "security./permissions.json", "note.txt "])
def test_paths_cannot_escape_or_access_secrets(tmp_path, path):
    connection = BoodaLaptopConnection(tmp_path)
    with pytest.raises(ValueError):
        connection._path(path)


def test_missing_read_permission_does_not_read(tmp_path):
    connection = BoodaLaptopConnection(tmp_path)
    task = connection.task_for("read_file", {"path": "not-present.txt"})
    assert connection.execute(task, permission_manager=permissions(read=False)) is None
    assert task.status == "failed"


def test_write_requires_exact_reviewed_request_and_no_overwrite(tmp_path):
    connection = BoodaLaptopConnection(tmp_path)
    task = connection.task_for("write_file", {"path": "note.txt", "content": "original"})
    approval = approve(task)
    task.metadata["parameters"]["content"] = "modified"
    with pytest.raises(ValueError):
        connection.execute(task, permission_manager=permissions(), approval=approval)
    assert not (tmp_path / "note.txt").exists()
    (tmp_path / "note.txt").write_text("keep")
    replacement = connection.task_for("write_file", {"path": "note.txt", "content": "overwrite"})
    connection.execute(replacement, permission_manager=permissions(), approval=approve(replacement))
    assert replacement.status == "uncertain"
    assert (tmp_path / "note.txt").read_text() == "keep"


def test_no_generic_commands_or_script_writes_are_exposed(tmp_path):
    connection = BoodaLaptopConnection(tmp_path)
    with pytest.raises(ValueError):
        connection.task_for("run_command", {"command": "whoami"})
    with pytest.raises(ValueError):
        connection._path("script.py", writing=True)

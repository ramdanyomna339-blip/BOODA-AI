from core.main import save_task_as_file
from core.permission_manager import BoodaPermissionManager
from core.task_manager import BoodaTaskManager


def test_save_file_permission_is_required(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)

    task_manager = BoodaTaskManager()
    task_manager.add_task(
        task_id="task-002",
        title="اعلان",
        description="بيع",
    )

    permission_manager = BoodaPermissionManager()
    permission_manager.add_permission(
        name="save_file",
        category="files",
        allowed=False,
    )

    monkeypatch.setattr("builtins.input", lambda _: "task-002")

    save_task_as_file(
        task_manager,
        permission_manager,
        audit_log=None,
    )

    task = task_manager.get_task("task-002")
    assert task.status == "failed"
    assert task.result == "Permission denied."
    assert not (tmp_path / "outputs").exists()
    assert "لم يتم حفظ الملف" in capsys.readouterr().out


def test_authorized_task_content_is_saved_to_file(
    monkeypatch,
    capsys,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)

    task_manager = BoodaTaskManager()
    task_manager.add_task(
        task_id="task-002",
        title="اعلان",
        description="بيع",
    )

    permission_manager = BoodaPermissionManager()
    permission_manager.add_permission(
        name="save_file",
        category="files",
        allowed=True,
    )

    monkeypatch.setattr("builtins.input", lambda _: "task-002")

    save_task_as_file(
        task_manager,
        permission_manager,
        audit_log=None,
    )

    task = task_manager.get_task("task-002")
    output_path = tmp_path / task.result

    assert task.status == "completed"
    assert output_path.exists()
    assert "العنوان: اعلان" in output_path.read_text(encoding="utf-8")
    assert "بيع" in output_path.read_text(encoding="utf-8")
    assert "تم حفظ محتوى المهمة في" in capsys.readouterr().out
from core.main import update_task_status
from core.task_manager import BoodaTaskManager


def test_completed_task_and_result_are_saved(monkeypatch, tmp_path):
    file_path = tmp_path / "tasks.json"
    task_manager = BoodaTaskManager(file_path=str(file_path))
    task_manager.add_task(
        task_id="task-001",
        title="مهمة تجريبية",
    )

    answers = iter(["task-001", "2", "تمت بنجاح"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    update_task_status(task_manager)

    reopened_manager = BoodaTaskManager(file_path=str(file_path))
    task = reopened_manager.get_task("task-001")

    assert task.status == "completed"
    assert task.result == "تمت بنجاح"


def test_update_reports_missing_task(monkeypatch, capsys):
    task_manager = BoodaTaskManager()
    monkeypatch.setattr("builtins.input", lambda _: "missing-task")

    update_task_status(task_manager)

    assert "المهمة غير موجودة." in capsys.readouterr().out
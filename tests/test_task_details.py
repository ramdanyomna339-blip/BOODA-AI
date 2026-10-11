from core.main import show_task_details
from core.task_manager import BoodaTaskManager


def test_task_details_show_saved_task(monkeypatch, capsys):
    task_manager = BoodaTaskManager()
    task = task_manager.add_task(
        task_id="task-001",
        title="مهمة تجريبية",
        description="وصف المهمة",
    )
    task.complete("تمت بنجاح")

    monkeypatch.setattr("builtins.input", lambda _: "task-001")
    show_task_details(task_manager)

    output = capsys.readouterr().out
    assert "task-001" in output
    assert "مهمة تجريبية" in output
    assert "وصف المهمة" in output
    assert "completed" in output
    assert "تمت بنجاح" in output


def test_task_details_reports_missing_task(monkeypatch, capsys):
    task_manager = BoodaTaskManager()
    monkeypatch.setattr("builtins.input", lambda _: "missing-task")

    show_task_details(task_manager)

    assert "المهمة غير موجودة." in capsys.readouterr().out

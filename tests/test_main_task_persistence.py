import builtins

import core.main as main_module
from core.audit_log import BoodaAuditLog
from core.task_manager import BoodaTaskManager


def test_demo_task_is_saved_and_shown_after_reopening(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)

    audit_log = BoodaAuditLog(tmp_path / "memory" / "audit_log.jsonl")
    answers = iter(["2", "6", "12", "6"])

    monkeypatch.setattr(
        main_module,
        "BoodaAuditLog",
        lambda: audit_log,
    )
    monkeypatch.setattr(
        builtins,
        "input",
        lambda prompt: next(answers),
    )

    main_module.main()
    main_module.main()

    task_manager = BoodaTaskManager(
        file_path=tmp_path / "memory" / "tasks.json",
    )
    task = task_manager.get_task("task-demo-001")
    output = capsys.readouterr().out

    assert task is not None
    assert task.status == "failed"
    assert task.result == "Approval expired."
    assert "task-demo-001: Expired approval test" in output
    assert "الحالة: failed" in output
    assert "Approval expired." in output
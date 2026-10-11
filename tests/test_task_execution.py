from core.approval_manager import BoodaApprovalManager
from core.main import simulate_saved_task
from core.permission_manager import BoodaPermissionManager
from core.risk import RiskLevel
from core.task_manager import BoodaTaskManager


def test_high_risk_task_requires_approval(monkeypatch, capsys, tmp_path):
    task_manager = BoodaTaskManager(
        file_path=str(tmp_path / "tasks.json")
    )
    task = task_manager.add_task(
        task_id="task-001",
        title="مهمة مالية",
    )

    permission_manager = BoodaPermissionManager()
    permission_manager.add_permission(
        name="spend_money",
        category="finance",
        risk_level=RiskLevel.HIGH,
        allowed=True,
    )

    approval_manager = BoodaApprovalManager()
    answers = iter(["task-001", "spend_money", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    simulate_saved_task(
        task_manager,
        permission_manager,
        approval_manager,
        audit_log=None,
    )

    assert task.status == "failed"
    assert task.result == "Approval required."
    assert "لم يتم تنفيذ المهمة" in capsys.readouterr().out


def test_approved_high_risk_task_runs_and_uses_approval(
    monkeypatch,
    capsys,
    tmp_path,
):
    task_manager = BoodaTaskManager(
        file_path=str(tmp_path / "tasks.json")
    )
    task = task_manager.add_task(
        task_id="task-002",
        title="مهمة مالية",
    )

    permission_manager = BoodaPermissionManager()
    permission_manager.add_permission(
        name="spend_money",
        category="finance",
        risk_level=RiskLevel.HIGH,
        allowed=True,
    )

    approval_manager = BoodaApprovalManager()
    approval_id, approval = approval_manager.create_approval(
        permission_name="spend_money",
        approved_by="Yomna",
        task_id="task-002",
    )
    approval_manager.approve_approval(approval_id)

    answers = iter(["task-002", "spend_money", approval_id])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    simulate_saved_task(
        task_manager,
        permission_manager,
        approval_manager,
        audit_log=None,
    )

    reopened_manager = BoodaTaskManager(
        file_path=str(tmp_path / "tasks.json")
    )
    saved_task = reopened_manager.get_task("task-002")

    assert saved_task.status == "completed"
    assert "تم التنفيذ التجريبي للمهمة" in saved_task.result
    assert approval.used is True
    assert "تم التنفيذ التجريبي للمهمة" in capsys.readouterr().out


def test_simulation_reports_missing_task(monkeypatch, capsys):
    task_manager = BoodaTaskManager()
    permission_manager = BoodaPermissionManager()
    approval_manager = BoodaApprovalManager()

    monkeypatch.setattr("builtins.input", lambda _: "missing-task")

    simulate_saved_task(
        task_manager,
        permission_manager,
        approval_manager,
        audit_log=None,
    )

    assert "المهمة غير موجودة." in capsys.readouterr().out
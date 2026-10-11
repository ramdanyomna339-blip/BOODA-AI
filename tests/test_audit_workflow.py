import builtins

import core.main as main_module
from core.approval_manager import BoodaApprovalManager
from core.audit_log import BoodaAuditLog
from core.audit_report import format_audit_events
from core.executor import BoodaExecutor
from core.permission_manager import BoodaPermissionManager
from core.permission_policy import BoodaPermissionPolicy
from core.risk import RiskLevel
from core.task import BoodaTask


def test_permission_changes_persist_and_can_be_reported(tmp_path):
    file_path = tmp_path / "audit_log.jsonl"
    audit_log = BoodaAuditLog(file_path)
    manager = BoodaPermissionManager(audit_log=audit_log)
    manager.add_permission("send_message", allowed=False)

    assert manager.grant_permission(
        "send_message",
        changed_by="Yomna",
    )
    assert manager.revoke_permission(
        "send_message",
        changed_by="Yomna",
    )

    reopened_log = BoodaAuditLog(file_path)
    events = reopened_log.get_events()

    assert [event.action for event in events] == [
        "permission_granted",
        "permission_revoked",
    ]
    assert all(event.requested_by == "Yomna" for event in events)
    assert all(event.outcome == "completed" for event in events)

    report = format_audit_events(events)
    assert "منح صلاحية" in report
    assert "سحب صلاحية" in report


def test_approved_execution_persists_with_approval_details(tmp_path):
    file_path = tmp_path / "audit_log.jsonl"
    audit_log = BoodaAuditLog(file_path)
    permission_manager = BoodaPermissionManager()
    permission_manager.add_permission(
        name="spend_money",
        category="finance",
        risk_level=RiskLevel.HIGH,
        allowed=True,
    )
    permission_policy = BoodaPermissionPolicy()
    approval_manager = BoodaApprovalManager()

    _, approval = approval_manager.create_approval(
        permission_name="spend_money",
        approved_by="Yomna",
        task_id="task-workflow-001",
    )
    approval.approve()

    task = BoodaTask("task-workflow-001", "Buy supplies")

    def purchase():
        return "Purchase complete."

    result = BoodaExecutor().execute(
        task=task,
        action=purchase,
        permission_manager=permission_manager,
        permission_name="spend_money",
        permission_policy=permission_policy,
        approval=approval,
        audit_log=audit_log,
        requested_by="Yomna",
    )

    reopened_log = BoodaAuditLog(file_path)
    events = reopened_log.get_events(task_id="task-workflow-001")

    assert result == "Purchase complete."
    assert [event.action for event in events] == [
        "approval_reserved",
        "execution_started",
        "purchase",
    ]
    assert events[-1].outcome == "completed"
    assert events[-1].approval_required is True
    assert events[-1].approval_granted is True
    assert events[-1].approved_by == "Yomna"


def test_main_menu_grant_persists_after_reopening(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)

    audit_log = BoodaAuditLog(tmp_path / "audit_log.jsonl")
    answers = iter(
        [
            "3",
            "send_message",
            "Yomna",
            "6",
            "5",
            "6",
        ]
    )

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

    output = capsys.readouterr().out
    events = audit_log.get_events()

    assert len(events) == 1
    assert events[0].action == "permission_granted"
    assert events[0].permission_name == "send_message"
    assert events[0].requested_by == "Yomna"
    assert "تم منحها الصلاحية: send_message" in output
    assert "- send_message: مسموحة" in output
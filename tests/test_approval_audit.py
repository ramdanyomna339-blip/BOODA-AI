from core.approval_manager import BoodaApprovalManager
from core.audit_log import BoodaAuditLog
from core.audit_report import format_audit_events
from core.executor import BoodaExecutor
from core.permission_manager import BoodaPermissionManager
from core.permission_policy import BoodaPermissionPolicy
from core.risk import RiskLevel
from core.task import BoodaTask


def test_approval_lifecycle_is_audited_and_persisted(tmp_path):
    file_path = tmp_path / "audit_log.jsonl"
    audit_log = BoodaAuditLog(file_path)
    approval_manager = BoodaApprovalManager(audit_log=audit_log)

    approval_id, approval = approval_manager.create_approval(
        permission_name="spend_money",
        approved_by="Yomna",
        reason="Approved purchase.",
        task_id="task-approval-001",
        created_by="Yomna",
    )

    assert approval_manager.approve_approval(approval_id) is True

    permission_manager = BoodaPermissionManager()
    permission_manager.add_permission(
        name="spend_money",
        category="finance",
        risk_level=RiskLevel.HIGH,
        allowed=True,
    )

    task = BoodaTask("task-approval-001", "Buy supplies")

    def purchase():
        return "Purchase complete."

    result = BoodaExecutor().execute(
        task=task,
        action=purchase,
        permission_manager=permission_manager,
        permission_name="spend_money",
        permission_policy=BoodaPermissionPolicy(),
        approval=approval,
        audit_log=audit_log,
        requested_by="Yomna",
    )

    assert result == "Purchase complete."
    assert approval_manager.revoke_approval(
        approval_id,
        revoked_by="Yomna",
    ) is True

    reopened_log = BoodaAuditLog(file_path)
    events = reopened_log.get_events(task_id="task-approval-001")

    assert [event.action for event in events] == [
        "approval_created",
        "approval_granted",
        "approval_reserved",
        "execution_started",
        "purchase",
        "approval_revoked",
    ]
    assert all(event.approval_id == approval_id for event in events)
    assert events[1].approval_granted is True
    assert events[2].outcome == "reserved"
    assert events[3].outcome == "started"
    assert events[4].approval_used is True
    assert events[5].approval_granted is False

    report = format_audit_events(events)
    assert "إنشاء موافقة" in report
    assert "اعتماد موافقة" in report
    assert "إلغاء موافقة" in report
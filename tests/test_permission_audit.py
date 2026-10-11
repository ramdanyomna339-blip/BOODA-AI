from core.audit_log import BoodaAuditLog
from core.audit_report import format_audit_events
from core.permission_manager import BoodaPermissionManager


def test_grant_and_revoke_are_recorded(tmp_path):
    audit_log = BoodaAuditLog(tmp_path / "audit_log.jsonl")
    manager = BoodaPermissionManager(audit_log=audit_log)
    permission = manager.add_permission(
        name="send_message",
        allowed=False,
    )

    assert manager.grant_permission(
        "send_message",
        changed_by="Yomna",
    ) is True
    assert permission.allowed is True

    assert manager.revoke_permission(
        "send_message",
        changed_by="Yomna",
    ) is True
    assert permission.allowed is False

    events = audit_log.get_events()

    assert len(events) == 2
    assert events[0].action == "permission_granted"
    assert events[0].permission_name == "send_message"
    assert events[0].requested_by == "Yomna"
    assert events[0].task_id is None
    assert events[0].outcome == "completed"

    assert events[1].action == "permission_revoked"
    assert events[1].requested_by == "Yomna"
    assert events[1].outcome == "completed"

    report = format_audit_events(events)
    assert "منح صلاحية" in report
    assert "سحب صلاحية" in report


def test_missing_permission_change_is_recorded_as_rejected(tmp_path):
    audit_log = BoodaAuditLog(tmp_path / "audit_log.jsonl")
    manager = BoodaPermissionManager(audit_log=audit_log)

    result = manager.revoke_permission(
        "unknown_permission",
        changed_by="Yomna",
    )

    event = audit_log.get_events()[0]

    assert result is False
    assert event.action == "permission_revoked"
    assert event.permission_name == "unknown_permission"
    assert event.outcome == "rejected"
    assert event.rejection_reason == "Permission not found."
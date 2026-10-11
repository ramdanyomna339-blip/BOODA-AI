from datetime import datetime, timezone

from core.approval_manager import BoodaApprovalManager
from core.audit_log import BoodaAuditLog
from core.executor import BoodaExecutor
from core.permission_manager import BoodaPermissionManager
from core.permission_policy import BoodaPermissionPolicy
from core.risk import RiskLevel
from core.task import BoodaTask


def test_audit_log_records_successful_action(tmp_path):
    audit_log = BoodaAuditLog(tmp_path / "audit_log.jsonl")
    permission_manager = BoodaPermissionManager()
    permission_manager.add_permission(
        name="send_message",
        category="communication",
        allowed=True,
    )
    task = BoodaTask("task-audit-001", "Send a message")

    def send_message():
        return "Message sent."

    result = BoodaExecutor().execute(
        task=task,
        action=send_message,
        permission_manager=permission_manager,
        permission_name="send_message",
        permission_policy=BoodaPermissionPolicy(),
        audit_log=audit_log,
        requested_by="Yomna",
    )

    events = audit_log.get_events()
    event = events[-1]

    assert result == "Message sent."
    assert event.action == "send_message"
    assert event.task_id == "task-audit-001"
    assert event.task_title == "Send a message"
    assert event.requested_by == "Yomna"
    assert event.permission_name == "send_message"
    assert event.approval_required is False
    assert event.approval_granted is None
    assert event.approved_by is None
    assert event.outcome == "completed"
    assert event.rejection_reason is None
    assert event.timestamp.tzinfo == timezone.utc
    assert isinstance(event.timestamp, datetime)
    assert [event.action for event in events] == [
        "execution_started",
        "send_message",
    ]


def test_audit_log_records_permission_rejection(tmp_path):
    audit_log = BoodaAuditLog(tmp_path / "audit_log.jsonl")
    task = BoodaTask("task-audit-002", "Send a message")

    result = BoodaExecutor().execute(
        task=task,
        action=lambda: "Message sent.",
        permission_manager=BoodaPermissionManager(),
        permission_name="send_message",
        audit_log=audit_log,
    )

    events = audit_log.get_events()
    event = events[-1]

    assert result is None
    assert task.status == "failed"
    assert event.permission_name == "send_message"
    assert event.outcome == "rejected"
    assert event.rejection_reason == "Permission not found."


def test_audit_log_records_approval_details(tmp_path):
    audit_log = BoodaAuditLog(tmp_path / "audit_log.jsonl")
    permission_manager = BoodaPermissionManager()
    permission_policy = BoodaPermissionPolicy()
    approval_manager = BoodaApprovalManager()

    permission_manager.add_permission(
        name="spend_money",
        category="finance",
        risk_level=RiskLevel.HIGH,
        allowed=True,
    )

    _, approval = approval_manager.create_approval(
        permission_name="spend_money",
        approved_by="Yomna",
        reason="Approved purchase.",
        task_id="task-audit-003",
    )
    approval.approve()

    task = BoodaTask("task-audit-003", "Buy supplies")

    result = BoodaExecutor().execute(
        task=task,
        action=lambda: "Purchase complete.",
        permission_manager=permission_manager,
        permission_name="spend_money",
        permission_policy=permission_policy,
        approval=approval,
        audit_log=audit_log,
        requested_by="Yomna",
    )

    event = audit_log.get_events()[-1]

    assert result == "Purchase complete."
    assert event.approval_required is True
    assert event.approval_granted is True
    assert event.approved_by == "Yomna"
    assert event.outcome == "completed"
    assert [item.action for item in audit_log.get_events()] == [
        "approval_reserved",
        "execution_started",
        "<lambda>",
    ]


def test_audit_log_records_action_failure(tmp_path):
    audit_log = BoodaAuditLog(tmp_path / "audit_log.jsonl")
    permission_manager = BoodaPermissionManager()
    permission_manager.add_permission("run_action", allowed=True)
    task = BoodaTask("task-audit-004", "Run an action")

    def fail_action():
        raise ValueError("Action failed.")

    result = BoodaExecutor().execute(
        task=task,
        action=fail_action,
        permission_manager=permission_manager,
        permission_name="run_action",
        permission_policy=BoodaPermissionPolicy(),
        audit_log=audit_log,
    )

    events = audit_log.get_events()
    event = events[-1]

    assert result is None
    assert task.status == "uncertain"
    assert event.outcome == "uncertain"
    assert "may have occurred" in event.rejection_reason
    assert events[0].action == "execution_started"


def test_audit_log_keeps_events_after_reopening(tmp_path):
    file_path = tmp_path / "audit_log.jsonl"
    task = BoodaTask("task-audit-005", "Save this event")

    first_log = BoodaAuditLog(file_path)
    first_log.record(
        action="save_event",
        task=task,
        requested_by="Yomna",
        permission_name="save_file",
        outcome="completed",
    )

    reopened_log = BoodaAuditLog(file_path)
    events = reopened_log.get_events()

    assert len(events) == 1
    assert events[0].task_id == "task-audit-005"
    assert events[0].requested_by == "Yomna"
    assert events[0].outcome == "completed"
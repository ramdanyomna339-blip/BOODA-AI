from datetime import datetime, timezone

from core.audit_log import BoodaAuditEvent
from core.audit_report import format_audit_events


def test_audit_report_formats_event_in_arabic():
    event = BoodaAuditEvent(
        timestamp=datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc),
        action="send_message",
        task_id="task-001",
        task_title="Send a message",
        requested_by="Yomna",
        permission_name="send_message",
        approval_required=False,
        approval_granted=None,
        approved_by=None,
        outcome="rejected",
        rejection_reason="Permission denied.",
    )

    report = format_audit_events([event])

    assert "العملية: send_message" in report
    assert "المهمة: Send a message (task-001)" in report
    assert "النتيجة: اترفضت" in report
    assert "السبب: Permission denied." in report


def test_audit_report_handles_empty_events():
    assert format_audit_events([]) == "مفيش عمليات مسجلة."
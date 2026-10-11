from datetime import datetime, timedelta, timezone

from core.audit_log import BoodaAuditLog
from core.task import BoodaTask


def record_event(audit_log, task_id, title):
    task = BoodaTask(task_id, title)
    return audit_log.record(
        action="test_action",
        task=task,
        outcome="completed",
    )


def test_audit_log_can_filter_events_by_task(tmp_path):
    audit_log = BoodaAuditLog(tmp_path / "audit_log.jsonl")
    record_event(audit_log, "task-001", "First task")
    record_event(audit_log, "task-002", "Second task")
    record_event(audit_log, "task-001", "First task again")

    events = audit_log.get_events(task_id="task-001")

    assert len(events) == 2
    assert all(event.task_id == "task-001" for event in events)


def test_audit_log_can_filter_events_by_day(tmp_path):
    audit_log = BoodaAuditLog(tmp_path / "audit_log.jsonl")
    recorded_event = record_event(
        audit_log,
        "task-003",
        "Today's task",
    )
    today = recorded_event.timestamp.date().isoformat()

    events = audit_log.get_events(day=today)

    assert len(events) == 1
    assert events[0].task_id == "task-003"


def test_audit_log_day_filter_can_return_no_events(tmp_path):
    audit_log = BoodaAuditLog(tmp_path / "audit_log.jsonl")
    record_event(audit_log, "task-004", "Today's task")
    yesterday = (
        datetime.now(timezone.utc).date() - timedelta(days=1)
    ).isoformat()

    events = audit_log.get_events(day=yesterday)

    assert events == []
"""Queries for overdue and upcoming tasks using their ISO 8601 deadlines."""

from datetime import date, datetime, time, timedelta


def parse_due_at(value, *, local_timezone=None):
    """Parse a date or timestamp; date-only deadlines end at local day's end."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("due_at must be an ISO 8601 date or timestamp.")
    local_timezone = local_timezone or datetime.now().astimezone().tzinfo
    value = value.strip()
    try:
        if len(value) == 10:
            deadline_date = date.fromisoformat(value)
            return datetime.combine(deadline_date, time.max, tzinfo=local_timezone)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("due_at must be an ISO 8601 date or timestamp.") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_timezone)
    return parsed


class BoodaScheduler:
    def __init__(self, task_manager):
        self.task_manager = task_manager

    @staticmethod
    def _now(as_of=None):
        if as_of is None:
            return datetime.now().astimezone()
        if isinstance(as_of, str):
            return parse_due_at(as_of)
        if not isinstance(as_of, datetime):
            raise ValueError("as_of must be a date-time or ISO 8601 string.")
        if as_of.tzinfo is None:
            return as_of.astimezone()
        return as_of

    def get_overdue_tasks(self, *, as_of=None, project_id=None):
        now = self._now(as_of)
        tasks = [
            task for task in self.task_manager.list_tasks(project_id=project_id)
            if task.due_at
            and task.status in {"pending", "running"}
            and parse_due_at(task.due_at) < now
        ]
        return sorted(tasks, key=lambda task: parse_due_at(task.due_at))

    def get_upcoming_tasks(self, *, days=7, as_of=None, project_id=None):
        if not isinstance(days, int) or days < 0:
            raise ValueError("days must be a non-negative integer.")
        now = self._now(as_of)
        end = now + timedelta(days=days)
        tasks = [
            task for task in self.task_manager.list_tasks(project_id=project_id)
            if task.due_at
            and task.status in {"pending", "running"}
            and now <= parse_due_at(task.due_at) <= end
        ]
        return sorted(tasks, key=lambda task: parse_due_at(task.due_at))

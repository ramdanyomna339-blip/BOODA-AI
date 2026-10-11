import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class BoodaAuditEvent:
    timestamp: datetime
    action: str
    task_id: Optional[str]
    task_title: Optional[str]
    requested_by: Optional[str]
    permission_name: Optional[str]
    approval_required: bool
    approval_granted: Optional[bool]
    approved_by: Optional[str]
    outcome: str
    rejection_reason: Optional[str] = None
    approval_id: Optional[str] = None
    approval_used: Optional[bool] = None


class BoodaAuditLog:
    def __init__(self, file_path="memory/audit_log.jsonl"):
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._events = []
        self._load_events()

    def _load_events(self):
        if not self.file_path.exists():
            return

        with self.file_path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue

                data = json.loads(line)
                data["timestamp"] = datetime.fromisoformat(data["timestamp"])
                self._events.append(BoodaAuditEvent(**data))

    def record(
        self,
        *,
        action,
        task=None,
        task_id=None,
        task_title=None,
        requested_by=None,
        permission_name=None,
        approval_required=False,
        approval=None,
        approval_id=None,
        outcome,
        rejection_reason=None,
    ):
        if task is not None:
            task_id = task.task_id
            task_title = task.title

        if approval is not None:
            if approval_id is None:
                approval_id = getattr(approval, "approval_id", None)

        event = BoodaAuditEvent(
            timestamp=datetime.now(timezone.utc),
            action=action,
            task_id=task_id,
            task_title=task_title,
            requested_by=requested_by,
            permission_name=permission_name,
            approval_required=approval_required,
            approval_granted=(
                approval.is_approved if approval is not None else None
            ),
            approved_by=(
                approval.approved_by if approval is not None else None
            ),
            outcome=outcome,
            rejection_reason=rejection_reason,
            approval_id=approval_id,
            approval_used=(
                approval.used if approval is not None else None
            ),
        )

        event_data = asdict(event)
        event_data["timestamp"] = event.timestamp.isoformat()
        line = json.dumps(event_data, ensure_ascii=False)

        with self.file_path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")

        self._events.append(event)
        return event

    def get_events(self, task_id=None, day=None):
        events = self._events

        if task_id is not None:
            events = [
                event for event in events if event.task_id == task_id
            ]

        if day is not None:
            if isinstance(day, str):
                day = date.fromisoformat(day)

            events = [
                event for event in events if event.timestamp.date() == day
            ]

        return list(events)
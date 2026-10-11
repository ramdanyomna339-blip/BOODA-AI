"""Append-only domain event log for goals, projects, tasks, and jobs."""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class BoodaEventLog:
    def __init__(self, file_path="memory/events.jsonl"):
        self.file_path = Path(file_path)

    def record(self, event_type, *, entity_type, entity_id, details=None):
        if not event_type or not entity_type or not entity_id:
            raise ValueError("Events require a type and entity identity.")
        event = {
            "event_id": f"event-{uuid4().hex}",
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "details": dict(details or {}),
        }
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with self.file_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        return event

    def get_events(self, *, entity_type=None, entity_id=None, event_type=None):
        if not self.file_path.exists():
            return []
        events = []
        with self.file_path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                event = json.loads(line)
                if entity_type is not None and event["entity_type"] != entity_type:
                    continue
                if entity_id is not None and event["entity_id"] != entity_id:
                    continue
                if event_type is not None and event["event_type"] != event_type:
                    continue
                events.append(event)
        return events

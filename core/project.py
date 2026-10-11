"""Project records used to organize goals and tasks."""

from dataclasses import dataclass, field
from typing import Any


PROJECT_STATUSES = {"active", "completed", "archived"}


@dataclass
class BoodaProject:
    project_id: str
    title: str
    description: str = ""
    goal_id: str | None = None
    status: str = "active"
    due_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.project_id, str) or not self.project_id.strip():
            raise ValueError("Project id must not be empty.")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("Project title must not be empty.")
        if self.status not in PROJECT_STATUSES:
            raise ValueError(f"Project status must be one of {sorted(PROJECT_STATUSES)}.")
        if self.due_at is not None:
            from core.scheduler import parse_due_at

            parse_due_at(self.due_at)
        self.metadata = dict(self.metadata or {})
